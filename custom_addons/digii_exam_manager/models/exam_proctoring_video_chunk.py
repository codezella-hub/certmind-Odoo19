# -*- coding: utf-8 -*-
"""
Enregistrement video PAR MORCEAUX — version robuste.

Le navigateur envoie un morceau WebM toutes les 10 s pendant l'examen.
Chaque morceau est stocke en ir.attachment. La video finale est
(re)construite a partir de TOUS les morceaux, ce qui couvre tous les cas :

  * Fin normale        : le dernier morceau arrive apres la fin de
                         l'examen -> assemblage immediat, sur le serveur,
                         sans dependre du navigateur.
  * Exclusion          : idem (le navigateur envoie la video avant de
                         rediriger).
  * Onglet ferme,      : le CRON assemble les morceaux recus des qu'aucun
    coupure reseau       nouveau morceau n'arrive depuis 1 minute.
  * Page rechargee     : chaque chargement de page = un nouvel
    (F5) en cours        "enregistrement" (recording_id). Les segments sont
                         mis bout a bout avec ffmpeg, dans l'ordre d'arrivee.
  * Morceau renvoye    : un morceau deja recu (meme recording_id + index)
    apres une erreur     est ignore : pas de doublon.
  * Morceau tardif     : il remet la session "a assembler" ; la video est
                         reconstruite avec lui.

ffmpeg (present dans l'image Docker) remuxe la video : duree et barre de
progression correctes dans le lecteur. Sans ffmpeg, on retombe sur une
simple concatenation des octets (lisible, mais sans duree).

Les morceaux sont conserves 24 h apres l'assemblage (pour pouvoir
reconstruire), puis supprimes par le CRON.
"""
import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CHUNK_MARKER = 'digii_proctoring_video_chunk'
MAX_CHUNK_BYTES = 20 * 1024 * 1024          # 10 s ~ 0,7 Mo : marge large
RECORDING_ID_RE = re.compile(r'^[A-Za-z0-9]{1,32}$')
CHUNK_NAME_RE = re.compile(r'^video_chunk_(\d{6})_([A-Za-z0-9]{1,32})_(\d{1,6})\.webm$')
IDLE_BEFORE_ASSEMBLY = timedelta(minutes=1)  # plus de morceau depuis 1 min
KEEP_CHUNKS = timedelta(days=1)              # purge des morceaux apres 24 h
FFMPEG_TIMEOUT = 600


def assemble_webm(segments, workdir):
    """Assemble une liste de segments WebM (bytes) en une seule video.

    Chaque segment est un enregistrement complet (en-tete + donnees).
    Retourne les octets de la video finale.
    """
    segments = [seg for seg in segments if seg]
    if not segments:
        return b''

    paths = []
    for i, data in enumerate(segments):
        path = os.path.join(workdir, 'seg_%03d.webm' % i)
        with open(path, 'wb') as f:
            f.write(data)
        paths.append(path)

    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg:
        out = os.path.join(workdir, 'final.webm')
        base = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error']
        if len(paths) == 1:
            cmd = base + ['-i', paths[0], '-c', 'copy', out]
        else:
            listing = os.path.join(workdir, 'list.txt')
            with open(listing, 'w') as f:
                for path in paths:
                    f.write("file '%s'\n" % path)
            cmd = base + ['-f', 'concat', '-safe', '0', '-i', listing,
                          '-c', 'copy', out]
        try:
            subprocess.run(cmd, check=True, timeout=FFMPEG_TIMEOUT,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if os.path.getsize(out) > 0:
                with open(out, 'rb') as f:
                    return f.read()
        except Exception as exc:  # noqa: BLE001
            detail = getattr(exc, 'stderr', b'') or b''
            _logger.warning('[Proctoring video] ffmpeg KO (%s) %s -> concatenation brute',
                            exc, detail[-500:].decode('utf-8', 'replace'))
    else:
        _logger.warning('[Proctoring video] ffmpeg absent -> concatenation brute')

    # Repli : le premier segment seul est parfaitement lisible ; les
    # suivants sont ajoutes (lus par la plupart des navigateurs).
    return b''.join(segments)


class ExamProctoringSessionVideoChunk(models.Model):
    _inherit = 'exam.proctoring.session'

    video_chunk_last_upload = fields.Datetime(
        'Dernier morceau video recu', readonly=True, copy=False)
    video_chunk_seq = fields.Integer(
        'Nb morceaux recus', readonly=True, copy=False, default=0)
    video_finalized = fields.Boolean(
        'Video assemblee', readonly=True, copy=False,
        help="Vrai quand tous les morceaux recus sont dans la video finale.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _video_chunk_domain(self):
        self.ensure_one()
        return [
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('description', '=', CHUNK_MARKER),
        ]

    def _video_chunks(self):
        # Nom zero-padde sur le numero d'arrivee -> tri = ordre d'arrivee.
        return self.env['ir.attachment'].sudo().search(
            self._video_chunk_domain(), order='name asc')

    def _try_lock(self):
        """Verrou de ligne non bloquant. False si un autre process assemble."""
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    'SELECT id FROM exam_proctoring_session '
                    'WHERE id = %s FOR UPDATE NOWAIT', (self.id,))
            return True
        except Exception:  # noqa: BLE001  (LockNotAvailable)
            return False

    def _exam_is_over(self):
        return self.state not in ('waiting', 'authorized', 'in_exam')

    # ------------------------------------------------------------------
    # Reception d'un morceau
    # ------------------------------------------------------------------
    def store_video_chunk(self, recording_id, index, data):
        """Stocke un morceau. Idempotent sur (recording_id, index)."""
        self.ensure_one()
        if not RECORDING_ID_RE.match(recording_id or ''):
            raise UserError("recording_id invalide.")
        if not 0 <= index <= 999999:
            raise UserError("index invalide.")
        if not data:
            raise UserError("Morceau vide.")
        if len(data) > MAX_CHUNK_BYTES:
            raise UserError("Morceau trop volumineux.")

        # Serialise les envois d'une meme session (numero d'arrivee fiable).
        self.env.cr.execute(
            'SELECT video_chunk_seq FROM exam_proctoring_session '
            'WHERE id = %s FOR UPDATE', (self.id,))
        seq = (self.env.cr.fetchone()[0] or 0) + 1

        suffix = '_%s_%d.webm' % (recording_id, index)
        if any(name.endswith(suffix) for name in self._video_chunks().mapped('name')):
            return False  # deja recu (renvoi apres une erreur reseau)

        self.env['ir.attachment'].sudo().create({
            'name': 'video_chunk_%06d%s' % (seq, suffix),
            'raw': data,
            'res_model': self._name,
            'res_id': self.id,
            'description': CHUNK_MARKER,
            'mimetype': 'video/webm',
        })
        self.sudo().write({
            'video_chunk_seq': seq,
            'video_chunk_last_upload': fields.Datetime.now(),
            'video_finalized': False,
        })
        return True

    # ------------------------------------------------------------------
    # Assemblage
    # ------------------------------------------------------------------
    def rebuild_video(self):
        """(Re)construit video_recording a partir de tous les morceaux."""
        self.ensure_one()
        if not self._try_lock():
            _logger.info('[Proctoring video] Session %s deja en cours d\'assemblage',
                         self.id)
            return False

        chunks = self._video_chunks()
        if not chunks:
            return bool(self.video_recording)

        # Regroupe par enregistrement (recording_id), dans l'ordre d'arrivee.
        recordings = {}
        for chunk in chunks:
            match = CHUNK_NAME_RE.match(chunk.name or '')
            if not match:
                continue
            _seq, rec_id, index = match.groups()
            recordings.setdefault(rec_id, []).append((int(index), chunk))

        segments = []
        for rec_id, items in recordings.items():
            items.sort(key=lambda item: item[0])
            indexes = [index for index, _c in items]
            missing = sorted(set(range(indexes[-1] + 1)) - set(indexes))
            if missing:
                _logger.warning('[Proctoring video] Session %s, enregistrement %s : '
                                'morceaux manquants %s', self.id, rec_id, missing)
            if indexes[0] != 0:
                # Sans le morceau 0 (en-tete WebM), le segment est illisible.
                _logger.warning('[Proctoring video] Session %s, enregistrement %s '
                                'ignore : morceau 0 absent', self.id, rec_id)
                continue
            segments.append(b''.join(c.raw or b'' for _i, c in items))

        workdir = tempfile.mkdtemp(prefix='proctor_video_')
        try:
            data = assemble_webm(segments, workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        if not data:
            return bool(self.video_recording)

        self.sudo().write({
            'video_recording': base64.b64encode(data),
            'video_filename': 'recording_%s.webm' % (self.name or self.id),
            'video_finalized': True,
        })
        _logger.info('[Proctoring video] Session %s : %d morceaux, %d enregistrement(s) '
                     '-> %d octets', self.id, len(chunks), len(segments), len(data))
        return True

    def finalize_video_chunks(self):
        """Assemble si necessaire. Retourne True si une video existe."""
        self.ensure_one()
        if self.video_finalized:
            return bool(self.video_recording)
        self.rebuild_video()
        return bool(self.video_recording)

    # ------------------------------------------------------------------
    # CRON : filet de securite + menage
    # ------------------------------------------------------------------
    @api.model
    def _cron_finalize_video_chunks(self):
        now = fields.Datetime.now()
        pending = self.sudo().search([
            ('video_finalized', '=', False),
            ('video_chunk_last_upload', '!=', False),
            ('video_chunk_last_upload', '<', now - IDLE_BEFORE_ASSEMBLY),
        ])
        for session in pending:
            try:
                session.rebuild_video()
                self.env.cr.commit()
            except Exception:  # noqa: BLE001
                self.env.cr.rollback()
                _logger.exception('[Proctoring video] Echec assemblage session %s',
                                  session.id)

        # Menage : morceaux des sessions assemblees depuis plus de 24 h.
        old = self.sudo().search([
            ('video_finalized', '=', True),
            ('video_chunk_last_upload', '<', now - KEEP_CHUNKS),
        ])
        for session in old:
            chunks = session._video_chunks()
            if chunks:
                chunks.unlink()
                self.env.cr.commit()
