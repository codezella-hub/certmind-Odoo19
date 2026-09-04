# -*- coding: utf-8 -*-
"""
Analyse de proctoring EN LOCAL dans Odoo (sans microservice externe).

Ce modele etend exam.proctoring.session pour executer le pipeline d'IA
(porte depuis l'ancien microservice FastAPI) directement dans Odoo, mais
via un CRON en arriere-plan afin de ne jamais bloquer l'interface.

Flux :
  1. action_analyze_video() : marque la session 'processing' (retour immediat)
  2. Le CRON _cron_run_pending_analyses() prend les sessions 'processing'
     et lance l'analyse lourde une par une (hors requete web).
  3. Le resultat (score, events, PDF) est stocke sur la session.
"""
import base64
import logging
import os
import tempfile

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class ProctoringSessionAiLocal(models.Model):
    _inherit = 'exam.proctoring.session'

    # Indique que l'analyse tourne en local (pas via microservice).
    ai_local_engine = fields.Boolean(
        "Analyse locale (Odoo)", default=True,
        help="Si coché, l'analyse IA s'exécute dans Odoo via le CRON, "
             "sans microservice externe.")

    # Progression reelle de l'analyse locale (0-100), mise a jour en direct.
    ai_progress = fields.Integer("Progression IA (%)", default=0, copy=False)

    # ------------------------------------------------------------------
    # Lancement de l'analyse (retour immediat, traitement en CRON)
    # ------------------------------------------------------------------
    def action_analyze_video_local(self):
        """
        Prepare l'analyse locale : passe la session en 'processing'.
        Le CRON (toutes les minutes) fait le travail lourd en arriere-plan.
        Retour immediat = l'interface n'est jamais bloquee.
        """
        self.ensure_one()
        if not self._has_analyzable_video():
            return self._notify(
                _("Aucune vidéo à analyser pour cette session."), 'warning')

        # Reinitialise l'etat IA. Le CRON prendra la session au prochain tour.
        self.write({
            'ai_analysis_state': 'processing',
            'ai_task_id': 'local-%d' % self.id,
            'ai_risk_score': 0,
            'ai_risk_level': False,
            'ai_alerts_count': 0,
            'ai_conclusion': False,
            'ai_interpretation': False,
            'ai_recommendation': False,
            'ai_report': False,
            'ai_progress': 0,
        })
        return self._notify(
            _("Analyse lancée. Le résultat apparaîtra dans une minute."),
            'success')

    # ------------------------------------------------------------------
    # CRON : traite les sessions en attente (coeur du traitement)
    # ------------------------------------------------------------------
    @api.model
    def _cron_run_pending_analyses(self, limit=3):
        """
        Analyse les sessions 'processing' une par une.
        Traite les sessions marquees 'processing' par le bouton d'analyse.
        
        
        limit : nombre max de sessions traitees par execution du CRON.
        """
        pending = self.search([
            ('ai_analysis_state', '=', 'processing'),
            ('ai_local_engine', '=', True),
        ], limit=limit, order='id asc')

        if not pending:
            return

        _logger.info("[Proctoring IA local] %d session(s) à analyser (CRON)",
                     len(pending))
        for session in pending:
            # Chaque session dans son propre commit : si l'une plante,
            # les autres ne sont pas perdues.
            try:
                session._run_local_analysis()
                self.env.cr.commit()
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "[Proctoring IA local] Echec session %s", session.id)
                session.write({
                    'ai_analysis_state': 'error',
                    'ai_conclusion': _("Erreur pendant l'analyse."),
                })
                self.env.cr.commit()

    # ------------------------------------------------------------------
    # Le travail lourd : appelle le pipeline d'IA porte
    # ------------------------------------------------------------------
    @api.model
    def _check_ai_libs(self):
        """
        Verifie la presence des librairies lourdes du pipeline.

        Elles ne sont volontairement PAS declarees dans le manifest :
        Odoo les importerait toutes au moment de l'installation, ce qui
        fait crasher le processus (conflits de bibliotheques natives).
        On les verifie donc ici, juste avant l'analyse.
        """
        manquantes = []
        for nom in ('cv2', 'numpy', 'mediapipe', 'ultralytics', 'torch'):
            try:
                __import__(nom)
            except Exception:  # noqa: BLE001
                manquantes.append(nom)
        if manquantes:
            raise Exception(
                "Librairies Python manquantes pour l'analyse : %s. "
                "Installez-les dans l'environnement Odoo "
                "(voir requirements.txt)." % ', '.join(manquantes))

    def _run_local_analysis(self):
        """Execute le pipeline complet sur la video de la session."""
        self.ensure_one()

        # Verification explicite, avec un message clair si une lib manque.
        self._check_ai_libs()

        # Import tardif : ces libs (cv2, mediapipe...) ne sont chargees
        # que lors de l'analyse, pas au demarrage ni a l'installation.
        from ..pipeline.analyzer import analyze_video
        from ..pipeline.report_generator import generate_report

        # Passer la cle Groq (parametre systeme Odoo) au pipeline via env,
        # car le pipeline est du Python pur (pas d'acces a Odoo).
        groq_key = self.env['ir.config_parameter'].sudo().get_param(
            'digii_proctoring_ai.groq_api_key', '')
        if groq_key:
            os.environ['GROQ_API_KEY'] = groq_key

        # 1. Recuperer la video (champ binaire OU Minio) et l'ecrire sur disque.
        video_bytes = self._get_local_video_bytes()
        if not video_bytes:
            raise Exception("Vidéo introuvable (ni en base, ni sur Minio).")
        tmp_dir = tempfile.mkdtemp(prefix='proctor_')
        video_path = os.path.join(tmp_dir, 'session_%d.webm' % self.id)
        with open(video_path, 'wb') as f:
            f.write(video_bytes)

        try:
            # 2. Analyse : on enregistre la progression reelle au fil de l'eau.
            #    Un commit a chaque etape rend la progression visible en direct
            #    dans l'interface (sinon elle ne serait ecrite qu'a la fin).
            def _on_progress(pct):
                try:
                    pct = max(0, min(int(pct), 99))  # 100% reserve a la fin
                    self.env.cr.execute(
                        "UPDATE exam_proctoring_session SET ai_progress = %s "
                        "WHERE id = %s", (pct, self.id))
                    self.env.cr.commit()
                except Exception:  # noqa: BLE001
                    pass  # la progression est cosmetique, on n'echoue jamais dessus

            result = analyze_video(
                'local-%d' % self.id, video_path, on_progress=_on_progress)

            # 3. Injecter les metadonnees candidat/examen pour le rapport.
            result.candidate_name = self.partner_id.name or ''
            result.exam_name = self.survey_id.title or ''
            if self.create_date:
                result.exam_date = self.create_date.strftime('%d/%m/%Y')

            # 4. Generer le rapport PDF.
            report_path = os.path.join(tmp_dir, 'report_%d.pdf' % self.id)
            pdf_b64 = False
            try:
                generate_report(result, report_path)
                with open(report_path, 'rb') as f:
                    pdf_b64 = base64.b64encode(f.read())
            except Exception as exc:  # noqa: BLE001
                _logger.warning("[Proctoring IA local] PDF non genere : %s", exc)

            # 5. Stocker le resultat sur la session.
            interp = result.interpretation
            vals = {
                'ai_analysis_state': 'done',
                'ai_progress': 100,
                'ai_risk_score': result.risk_score,
                'ai_risk_level': result.risk_level.value
                if hasattr(result.risk_level, 'value') else result.risk_level,
                'ai_alerts_count': result.stats.total_alerts,
            }
            if interp is not None:
                vals['ai_conclusion'] = getattr(interp, 'conclusion', '')
                vals['ai_interpretation'] = getattr(interp, 'interpretation', '')
                vals['ai_recommendation'] = getattr(interp, 'recommendation', '')
            if pdf_b64:
                vals['ai_report'] = pdf_b64
                vals['ai_report_filename'] = 'rapport_proctoring_%d.pdf' % self.id
            self.write(vals)
            _logger.info("[Proctoring IA local] Session %s : score %s",
                         self.id, result.risk_score)
        finally:
            # Nettoyage des fichiers temporaires.
            try:
                for fn in os.listdir(tmp_dir):
                    os.remove(os.path.join(tmp_dir, fn))
                os.rmdir(tmp_dir)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Recuperation de la video (champ binaire OU Minio via LiveKit Egress)
    # ------------------------------------------------------------------
    def _has_analyzable_video(self):
        """Vrai s'il existe une video (en base ou sur Minio)."""
        self.ensure_one()
        return bool(self.video_recording or self.video_minio_key)

    def _get_local_video_bytes(self):
        """
        Retourne les octets de la video pour l'analyse.
        Priorite : champ binaire video_recording, sinon telechargement Minio.
        """
        self.ensure_one()
        if self.video_recording:
            return base64.b64decode(self.video_recording)
        if self.video_minio_key:
            return self._download_video_from_minio()
        return None

    def _download_video_from_minio(self):
        """Telecharge la video depuis Minio via boto3."""
        self.ensure_one()
        LK = self.env['livekit.config'].sudo()
        try:
            minio = LK._get_minio_config()
        except Exception as exc:  # noqa: BLE001
            _logger.error("[Proctoring IA local] Config Minio illisible : %s", exc)
            return None

        bucket = minio['bucket']
        key = self.video_minio_key or LK.video_key_for_session(self)
        try:
            import boto3
            from botocore.client import Config
            s3 = boto3.client(
                's3',
                endpoint_url=minio['endpoint'],
                aws_access_key_id=minio['access_key'],
                aws_secret_access_key=minio['secret_key'],
                region_name='us-east-1',
                config=Config(signature_version='s3v4'),
            )
            obj = s3.get_object(Bucket=bucket, Key=key)
            data = obj['Body'].read()
            _logger.info("[Proctoring IA local] Vidéo Minio récupérée (%d octets)",
                         len(data))
            return data
        except ImportError:
            raise Exception(
                "boto3 requis pour lire la vidéo depuis Minio. "
                "Installez-le : pip install boto3")
        except Exception as exc:  # noqa: BLE001
            _logger.error("[Proctoring IA local] Échec téléchargement Minio "
                          "(bucket=%s, key=%s) : %s", bucket, key, exc)
            raise Exception("Impossible de télécharger la vidéo depuis Minio : %s"
                            % exc)

    # ------------------------------------------------------------------
    def _notify(self, message, kind='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': message,
                'type': kind,
                'sticky': False,
            },
        }
