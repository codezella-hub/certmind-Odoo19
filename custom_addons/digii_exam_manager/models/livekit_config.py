# -*- coding: utf-8 -*-
"""
LiveKit configuration + JWT generation + Egress (enregistrement serveur).

Paramètres ir.config_parameter utilisés :

    digii_exam_manager.livekit_url          wss://livekit.mondomaine.com
    digii_exam_manager.livekit_api_key      devkey
    digii_exam_manager.livekit_api_secret   secret

    digii_exam_manager.minio_endpoint       http://minio:9000
    digii_exam_manager.minio_access_key     minioadmin
    digii_exam_manager.minio_secret_key     minioadmin
    digii_exam_manager.minio_bucket         exam-recordings
    digii_exam_manager.minio_public_url     http://localhost:9000

Convention de nommage des rooms :
    proc_<survey_id>_<partner_id>   — une room par candidat

Egress :
    LiveKit Egress enregistre la room côté serveur en MP4 directement
    dans Minio. Odoo démarre l'Egress quand le candidat passe en
    in_exam, et l'arrête quand l'examen est terminé.
    Le procteur peut ensuite streamer la vidéo depuis Minio via une
    URL pré-signée affichée dans la fiche certificat.
"""
import time
import logging

import jwt          # PyJWT, livré avec Odoo
try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from odoo import models, api

_logger = logging.getLogger(__name__)

DEFAULT_URL              = 'ws://localhost:7880'
DEFAULT_KEY              = 'devkey'
DEFAULT_SECRET           = 'p919yuLsAbqLWtT5BjlxznGVD7lBPAzAznI5zFIoWYS3hzmX'  # 32+ caracteres exiges par LiveKit 1.11+
DEFAULT_MINIO_ENDPOINT   = 'http://minio:9000'
DEFAULT_MINIO_ACCESS_KEY = 'minioadmin'
DEFAULT_MINIO_SECRET_KEY = 'minioadmin'
DEFAULT_MINIO_BUCKET     = 'exam-recordings'
DEFAULT_MINIO_PUBLIC_URL = 'http://localhost:9000'
TOKEN_TTL = 3600


class LiveKitConfig(models.AbstractModel):
    _name = 'exam.livekit.config'
    _description = 'LiveKit + Minio settings helper'

    # ------------------------------------------------------------------
    # Lecture des paramètres
    # ------------------------------------------------------------------

    @api.model
    def _get_livekit_url(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return ICP.get_param('digii_exam_manager.livekit_url', DEFAULT_URL)

    @api.model
    def _get_livekit_credentials(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return (
            ICP.get_param('digii_exam_manager.livekit_api_key', DEFAULT_KEY),
            ICP.get_param('digii_exam_manager.livekit_api_secret', DEFAULT_SECRET),
        )

    @api.model
    def _get_minio_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'endpoint':   ICP.get_param('digii_exam_manager.minio_endpoint',   DEFAULT_MINIO_ENDPOINT),
            'access_key': ICP.get_param('digii_exam_manager.minio_access_key', DEFAULT_MINIO_ACCESS_KEY),
            'secret_key': ICP.get_param('digii_exam_manager.minio_secret_key', DEFAULT_MINIO_SECRET_KEY),
            'bucket':     ICP.get_param('digii_exam_manager.minio_bucket',     DEFAULT_MINIO_BUCKET),
            'public_url': ICP.get_param('digii_exam_manager.minio_public_url', DEFAULT_MINIO_PUBLIC_URL),
        }

    # ------------------------------------------------------------------
    # Nommage
    # ------------------------------------------------------------------

    @api.model
    def room_name_for_session(self, session):
        return f'proc_{session.survey_id.id}_{session.partner_id.id}'

    @api.model
    def video_key_for_session(self, session):
        """Clé objet Minio (chemin) du MP4 de la session."""
        return f'session_{session.id}.mp4'

    # ------------------------------------------------------------------
    # JWT
    # ------------------------------------------------------------------

    @api.model
    def build_token(self, identity, room, name=None, can_publish=False,
                    can_subscribe=True, ttl=TOKEN_TTL):
        key, secret = self._get_livekit_credentials()
        now = int(time.time())
        payload = {
            'iss': key,
            'sub': identity,
            'nbf': now,
            'exp': now + ttl,
            'name': name or identity,
            'video': {
                'roomJoin': True,
                'room': room,
                'canPublish': can_publish,
                'canSubscribe': can_subscribe,
                'canPublishData': True,
            },
        }
        token = jwt.encode(payload, secret, algorithm='HS256')
        if isinstance(token, bytes):
            token = token.decode('utf-8')
        return token

    @api.model
    def _build_admin_token(self):
        """Token admin pour les appels API LiveKit Egress."""
        key, secret = self._get_livekit_credentials()
        now = int(time.time())
        payload = {
            'iss': key,
            'sub': 'odoo_server',
            'nbf': now,
            'exp': now + 300,
            'video': {
                'roomCreate':    True,
                'roomList':      True,
                'roomAdmin':     True,
                'roomRecord':    True,   # requis pour Egress
                'canPublish':    True,
                'canSubscribe':  True,
                'canPublishData': True,
                'hidden':        True,   # participant invisible dans la room
            },
        }
        token = jwt.encode(payload, secret, algorithm='HS256')
        if isinstance(token, bytes):
            token = token.decode('utf-8')
        return token

    @api.model
    def _livekit_http_url(self):
        url = self._get_livekit_url()
        return url.replace('wss://', 'https://').replace('ws://', 'http://')

    # ------------------------------------------------------------------
    # Egress API
    # ------------------------------------------------------------------

    @api.model
    def start_egress(self, session):
        """
        Démarre un RoomCompositeEgress LiveKit.
        La vidéo MP4 est écrite directement dans Minio.
        Retourne l'egress_id (str) ou None si échec.

        IMPORTANT : l'endpoint Minio envoyé à Egress doit être l'adresse
        interne Docker (http://minio:9000), pas localhost.
        On utilise un paramètre séparé 'minio_docker_endpoint' pour ça.
        """
        if not HAS_REQUESTS:
            _logger.warning('[Egress] requests non disponible.')
            return None

        minio = self._get_minio_config()
        room  = self.room_name_for_session(session)
        key   = self.video_key_for_session(session)
        base  = self._livekit_http_url()
        token = self._build_admin_token()

        # Endpoint Minio VU PAR EGRESS (container Docker) = adresse interne
        # Différent de minio_endpoint qui est vu par Odoo (Windows)
        ICP = self.env['ir.config_parameter'].sudo()
        minio_docker_endpoint = ICP.get_param(
            'digii_exam_manager.minio_docker_endpoint',
            'http://minio:9000'   # valeur par défaut = nom Docker
        )

        _logger.warning('[Egress] minio_docker_endpoint pour Egress: %s', minio_docker_endpoint)

        payload = {
            'room_name': room,
            'layout': 'grid',
            'file_outputs': [{
                'file_type': 'MP4',
                'filepath': key,
                's3': {
                    'access_key':       minio['access_key'],
                    'secret':           minio['secret_key'],
                    'region':           'us-east-1',
                    'endpoint':         minio_docker_endpoint,
                    'bucket':           minio['bucket'],
                    'force_path_style': True,
                },
            }],
        }

        try:
            url_egress = f"{base}/twirp/livekit.Egress/StartRoomCompositeEgress"
            _logger.warning('[Egress] Appel URL: %s room=%s', url_egress, room)
            _logger.warning('[Egress] Payload: %s', payload)
            resp = _requests.post(
                url_egress,
                json=payload,
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type':  'application/json',
                },
                timeout=10,
            )
            _logger.warning('[Egress] HTTP status: %s body: %s', resp.status_code, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()
            egress_id = data.get('egress_id')
            _logger.warning('[Egress] Demarre egress_id=%s room=%s', egress_id, room)
            return egress_id
        except Exception as exc:
            _logger.warning('[Egress] ECHEC COMPLET: %s', exc, exc_info=True)
            return None

    @api.model
    def stop_egress(self, egress_id):
        """Arrête un Egress — LiveKit finalise le MP4 dans Minio."""
        if not HAS_REQUESTS or not egress_id:
            return
        base  = self._livekit_http_url()
        token = self._build_admin_token()
        try:
            resp = _requests.post(
                f"{base}/twirp/livekit.Egress/StopEgress",
                json={'egress_id': egress_id},
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type':  'application/json',
                },
                timeout=10,
            )
            resp.raise_for_status()
            _logger.info('[Egress] Arrêté egress_id=%s', egress_id)
        except Exception as exc:
            _logger.warning('[Egress] Échec arrêt egress_id=%s : %s', egress_id, exc)

    # ------------------------------------------------------------------
    # URL de streaming Minio
    # ------------------------------------------------------------------

    @api.model
    def get_video_stream_url(self, session):
        """
        Retourne une URL présignée Minio (valide 24h) pour lire le MP4.
        Utilise boto3 si disponible, sinon URL directe (réseau interne).
        """
        minio  = self._get_minio_config()
        bucket = minio['bucket']
        key    = self.video_key_for_session(session)

        try:
            import boto3
            from botocore.client import Config
            s3 = boto3.client(
                's3',
                endpoint_url          = minio['endpoint'],
                aws_access_key_id     = minio['access_key'],
                aws_secret_access_key = minio['secret_key'],
                region_name           = 'us-east-1',
                config                = Config(signature_version='s3v4'),
            )
            url = s3.generate_presigned_url(
                'get_object',
                Params    = {'Bucket': bucket, 'Key': key},
                ExpiresIn = 86400,
            )
            return url
        except ImportError:
            _logger.debug('[Minio] boto3 absent, URL directe utilisée.')
        except Exception as exc:
            _logger.warning('[Minio] boto3 erreur : %s', exc)

        # Fallback URL directe
        public = minio['public_url'].rstrip('/')
        return f"{public}/{bucket}/{key}"
