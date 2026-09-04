# -*- coding: utf-8 -*-
import base64
import json
import logging

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)


class ExamProctoringSession(models.Model):
    """
    Session de proctoring pour un candidat.

    Workflow :
        waiting    -> Le candidat a ouvert sa camera et attend l'autorisation
        authorized -> Le procteur a autorisé -> le candidat peut démarrer
        rejected   -> Le procteur a rejeté (triche, identité non vérifiée...)
        in_exam    -> Le candidat a lancé l'examen
        completed  -> L'examen est terminé
        expired    -> Session expirée (timeout)

    Enregistrement vidéo (LiveKit Egress) :
        Quand l'examen démarre (action_start_exam), Odoo appelle
        LiveKit Egress API. LiveKit enregistre la room en MP4 et écrit
        le fichier directement dans Minio. A la fin (action_complete),
        Odoo arrête l'Egress. Le procteur retrouve l'URL de la vidéo
        dans la fiche certificat liée.
    """
    _name = 'exam.proctoring.session'
    _description = 'Session de proctoring'
    _order = 'create_date desc'
    _inherit = ['mail.thread']

    name = fields.Char(
        'Référence',
        readonly=True,
        copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('exam.proctoring.session') or 'PROC-0000',
    )

    survey_id = fields.Many2one(
        'survey.survey', string='Examen',
        required=True, ondelete='cascade', readonly=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Candidat',
        required=True, ondelete='cascade', readonly=True,
    )
    user_id = fields.Many2one(
        'res.users', string='Utilisateur', readonly=True,
    )

    state = fields.Selection([
        ('waiting',    'En attente'),
        ('authorized', 'Autorisé'),
        ('rejected',   'Rejeté'),
        ('in_exam',    'En examen'),
        ('completed',  'Terminé'),
        ('expired',    'Expiré'),
    ], string='Statut', default='waiting', required=True, tracking=True)

    # WebRTC Signaling
    offer_sdp      = fields.Text('Offer SDP', readonly=True)
    answer_sdp     = fields.Text('Answer SDP', readonly=True)
    ice_candidates = fields.Text('ICE Candidates (JSON)', readonly=True, default='[]')

    # Procteur
    proctor_id       = fields.Many2one('res.users', string='Procteur', readonly=True)
    rejection_reason = fields.Text('Motif de rejet')

    # Timestamps
    date_authorized  = fields.Datetime('Date autorisation', readonly=True)
    date_exam_start  = fields.Datetime("Date début d'examen", readonly=True)
    date_completed   = fields.Datetime('Date fin', readonly=True)

    # Token d'accès portail
    access_token = fields.Char('Token d\'accès', readonly=True, copy=False, index=True)

    # Lien vers le user_input
    user_input_id = fields.Many2one(
        'survey.user_input', string="Session d'examen", readonly=True,
    )

    # ---------------------------------------------------------------
    # LiveKit Egress — enregistrement côté serveur
    # ---------------------------------------------------------------
    egress_id = fields.Char(
        'LiveKit Egress ID',
        readonly=True,
        help="Identifiant de l'enregistrement Egress LiveKit en cours.",
    )
    video_minio_key = fields.Char(
        'Clé Minio de la vidéo',
        readonly=True,
        help="Chemin de l'objet MP4 dans le bucket Minio.",
    )

    # ---------------------------------------------------------------
    # Enregistrement local (MediaRecorder navigateur → WebM)
    # Chaîne 100% Odoo, sans LiveKit/Minio/Docker. Le navigateur
    # enregistre la caméra et envoie le blob à /exam/proctoring/upload-recording
    # qui le stocke ici en pièce jointe.
    # ---------------------------------------------------------------
    video_recording = fields.Binary(
        'Enregistrement vidéo (local)',
        attachment=True,
        copy=False,
        help="Vidéo WebM enregistrée côté navigateur et téléversée à la fin de l'examen.",
    )
    video_filename = fields.Char(
        'Nom du fichier vidéo',
        copy=False,
    )

    has_video_recording = fields.Boolean(
        'Vidéo enregistrée',
        compute='_compute_has_video_recording',
        store=True,
    )

    @api.depends('video_minio_key', 'video_recording')
    def _compute_has_video_recording(self):
        for session in self:
            session.has_video_recording = bool(
                session.video_minio_key or session.video_recording
            )

    def action_open_video(self):
        """Ouvre l'enregistrement local dans une page lecteur HTML5 (lecture en ligne)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/exam/proctoring/recording/%s' % self.id,
            'target': 'new',
        }

    # Lien vers le certificat généré (rempli par survey_user_input_patch)
    certificate_id = fields.Many2one(
        'exam.certificate',
        string='Certificat',
        readonly=True,
    )

    # ---------------------------------------------------------------
    # Analyse IA (microservice de detection de triche)
    # ---------------------------------------------------------------
    ai_task_id = fields.Char(
        'ID tache IA', readonly=True, copy=False,
        help="Identifiant de la tache renvoye par le microservice IA.",
    )
    ai_analysis_state = fields.Selection([
        ('not_started', 'Non analyse'),
        ('processing',  'Analyse en cours'),
        ('done',        'Analyse terminee'),
        ('error',       'Erreur'),
    ], string='Etat analyse IA', default='not_started',
        readonly=True, copy=False, tracking=True)

    ai_risk_score = fields.Integer(
        'Score de risque', readonly=True, copy=False,
        help="Score de triche 0-100 calcule par l'IA.",
    )
    ai_risk_level = fields.Selection([
        ('none',      'Aucun risque'),
        ('suspect',   'Suspect'),
        ('high',      'Tres suspect'),
        ('very_high', 'Triche probable'),
    ], string='Niveau de risque', readonly=True, copy=False)

    ai_alerts_count = fields.Integer('Nb alertes', readonly=True, copy=False)

    # Textes generes par le LLM (Groq)
    ai_conclusion = fields.Text('Conclusion IA', readonly=True, copy=False)
    ai_interpretation = fields.Text('Interpretation IA', readonly=True, copy=False)
    ai_recommendation = fields.Text('Recommandation IA', readonly=True, copy=False)

    # Rapport PDF genere par le microservice
    ai_report = fields.Binary('Rapport PDF IA', readonly=True, copy=False, attachment=True)
    ai_report_filename = fields.Char('Nom du rapport', readonly=True, copy=False)

    # ---------------------------------------------------------------
    # Actions procteur
    # ---------------------------------------------------------------

    def action_authorize(self):
        self.ensure_one()
        if self.state != 'waiting':
            raise UserError("Seules les sessions en attente peuvent être autorisées.")

        vals = {
            'state':           'authorized',
            'proctor_id':      self.env.uid,
            'date_authorized': fields.Datetime.now(),
        }

        # Egress LiveKit/Minio : OPTIONNEL (désactivé par défaut).
        # Activez-le avec le paramètre digii_exam_manager.use_egress = True.
        # Sinon, on s'appuie uniquement sur l'enregistrement LOCAL (WebM),
        # et on ne renseigne PAS video_minio_key (sinon le certificat
        # chercherait une vidéo Minio inexistante).
        if self._egress_enabled():
            LK = self.env['exam.livekit.config']
            egress_id = LK.start_egress(self)
            if egress_id:
                vals['egress_id'] = egress_id
                vals['video_minio_key'] = LK.video_key_for_session(self)

        self.write(vals)
        self._notify_candidate('authorized', {
            'message': "Vous êtes autorisé à commencer l'examen.",
        })
        return True

    @api.model
    def _egress_enabled(self):
        """True si l'enregistrement serveur LiveKit/Minio (Egress) est activé.
        Par défaut False → enregistrement 100% local (WebM dans Odoo)."""
        return self.env['ir.config_parameter'].sudo().get_param(
            'digii_exam_manager.use_egress', 'False'
        ) in ('True', 'true', '1')

    def action_reject(self, reason=''):
        self.ensure_one()
        if self.state not in ('waiting', 'authorized'):
            raise UserError("Cette session ne peut plus être rejetée.")
        reason = reason or 'Rejeté par le procteur.'
        self.write({
            'state':            'rejected',
            'proctor_id':       self.env.uid,
            'rejection_reason': reason,
        })

        # Marquer l'examen (user_input) comme rejeté, s'il existe déjà
        if self.user_input_id:
            self.user_input_id.mark_exam_rejected(reason)

        # Enregistrer un strike pour ce candidat
        self.env['exam.strike'].record_strike(
            self.partner_id, 'proctoring_reject', reason=reason,
            survey=self.survey_id, session=self,
        )

        self._notify_candidate('rejected', {
            'message': reason or 'Votre session a été rejetée.',
        })
        return True

    def action_exclude(self, reason=''):
        """Exclusion d'un candidat EN COURS d'examen (par le procteur).
        Termine la session, marque l'examen rejeté et enregistre un strike."""
        self.ensure_one()
        if self.state not in ('in_exam', 'authorized', 'waiting'):
            raise UserError(
                "Cette session ne peut plus être exclue (état : %s)." % self.state
            )
        reason = reason or 'Exclu par le procteur.'
        self.write({
            'state':            'completed',
            'date_completed':   fields.Datetime.now(),
            'rejection_reason': reason,
            'proctor_id':       self.env.uid,
        })

        # Clôturer le user_input et le marquer rejeté
        user_input = self.user_input_id
        if user_input:
            if user_input.state not in ('done', 'expired'):
                try:
                    user_input.sudo()._mark_done()
                except Exception:
                    user_input.sudo().write({'state': 'expired'})
            user_input.mark_exam_rejected(reason)

        # Enregistrer un strike
        self.env['exam.strike'].record_strike(
            self.partner_id, 'exclusion', reason=reason,
            survey=self.survey_id, session=self,
        )

        self._notify_proctor('exam_completed', {
            'session_id':   self.id,
            'partner_name': self.partner_id.name or '',
            'excluded':     True,
        })
        self._notify_candidate('excluded', {'message': reason})
        return True

    def action_start_exam(self):
        """Le candidat démarre l'examen."""
        self.ensure_one()
        if self.state != 'authorized':
            raise UserError("Vous devez être autorisé pour démarrer l'examen.")

        vals = {
            'state':           'in_exam',
            'date_exam_start': fields.Datetime.now(),
        }

        # Fallback Egress uniquement s'il est activé et pas encore démarré.
        if self._egress_enabled() and not self.egress_id:
            LK = self.env['exam.livekit.config']
            egress_id = LK.start_egress(self)
            if egress_id:
                vals['egress_id'] = egress_id
                vals['video_minio_key'] = LK.video_key_for_session(self)

        self.write(vals)
        return True

    def action_start_exam_record_only(self):
        """
        Demarre l'examen en mode ENREGISTREMENT SEUL (sans proctoring).
        Le candidat n'a pas besoin d'etre autorise : la video est
        enregistree en arriere-plan mais aucun procteur ne surveille en
        direct. La video reste analysable par l'IA apres l'examen.
        """
        self.ensure_one()
        # On accepte de demarrer depuis 'waiting' directement (pas besoin
        # de passer par 'authorized').
        if self.state not in ('waiting', 'authorized'):
            raise UserError("Cette session ne peut pas demarrer.")

        vals = {
            'state':           'in_exam',
            'date_exam_start': fields.Datetime.now(),
        }

        # Demarre l'enregistrement Egress (comme le proctoring).
        if self._egress_enabled() and not self.egress_id:
            LK = self.env['exam.livekit.config']
            egress_id = LK.start_egress(self)
            if egress_id:
                vals['egress_id'] = egress_id
                vals['video_minio_key'] = LK.video_key_for_session(self)

        self.write(vals)
        return True

    def action_complete(self):
        """Marque la session comme terminée et arrête l'Egress."""
        self.ensure_one()
        if self.state not in ('in_exam', 'authorized'):
            return

        # Arrêter l'enregistrement Egress
        if self.egress_id:
            try:
                self.env['exam.livekit.config'].stop_egress(self.egress_id)
            except Exception as exc:
                _logger.warning('[Proctoring] Egress stop failed: %s', exc)

        self.write({
            'state':          'completed',
            'date_completed': fields.Datetime.now(),
        })

    # ---------------------------------------------------------------
    # Analyse IA — envoi de la video au microservice
    # ---------------------------------------------------------------

    @api.model
    def _get_ai_service_url(self):
        """URL du microservice IA (Parametres > Technique > Parametres systeme)."""
        return self.env['ir.config_parameter'].sudo().get_param(
            'digii_exam_manager.proctoring_ai_url',
            'http://localhost:8000',
        ).rstrip('/')

    def _get_video_bytes(self):
        """Retourne les octets de la video (WebM stocke en base64)."""
        self.ensure_one()
        if self.video_recording:
            return base64.b64decode(self.video_recording)
        return None

    def action_analyze_video(self):
        """Lance (ou relance) l'analyse IA de la video.

        Si le module d'analyse LOCALE (digii_proctoring_ai) est installe,
        on l'utilise en priorite : l'analyse tourne dans Odoo via un CRON,
        sans microservice externe. Sinon, on retombe sur le microservice HTTP.
        """
        self.ensure_one()

        # --- Moteur LOCAL prioritaire (si le module est installe) ---
        if hasattr(self, 'action_analyze_video_local'):
            return self.action_analyze_video_local()

        # --- Sinon : microservice HTTP (ancien mode) ---
        video_bytes = self._get_video_bytes()
        if not video_bytes:
            raise UserError("Aucune video enregistree pour cette session.")

        url = self._get_ai_service_url() + '/analyze/video'
        filename = self.video_filename or ('session_%s.webm' % self.id)

        _logger.info('[Proctoring IA] Envoi video session %s -> %s', self.id, url)

        # Metadonnees pour personnaliser le rapport PDF.
        exam_date = ''
        if self.create_date:
            exam_date = self.create_date.strftime('%d/%m/%Y')
        meta = {
            'candidate_name': self.partner_id.name or '',
            'exam_name': self.survey_id.title or '',
            'exam_date': exam_date,
        }

        try:
            response = requests.post(
                url,
                files={'file': (filename, video_bytes, 'video/webm')},
                data=meta,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.ConnectionError:
            self.ai_analysis_state = 'error'
            raise UserError(
                "Impossible de joindre le service d'analyse IA.\n"
                "Verifiez qu'il tourne (uvicorn) et que l'URL est correcte "
                "dans Parametres systeme (digii_exam_manager.proctoring_ai_url)."
            )
        except requests.exceptions.RequestException as exc:
            self.ai_analysis_state = 'error'
            raise UserError("Erreur lors de l'envoi au service IA : %s" % exc)

        task_id = data.get('task_id')
        if not task_id:
            self.ai_analysis_state = 'error'
            raise UserError("Reponse invalide du service IA (pas de task_id).")

        # On repart de zero : nouveau task_id, ancien resultat efface.
        self.write({
            'ai_task_id':        task_id,
            'ai_analysis_state': 'processing',
            'ai_risk_score':     0,
            'ai_risk_level':     False,
            'ai_alerts_count':   0,
            'ai_conclusion':     False,
            'ai_interpretation': False,
            'ai_recommendation': False,
            'ai_report':         False,
            'ai_report_filename': False,
        })
        _logger.info('[Proctoring IA] Tache creee : %s', task_id)

        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   "Analyse lancee",
                'message': "La video est en cours d'analyse. Le resultat "
                           "apparaitra automatiquement, ou cliquez sur "
                           "'Rafraichir l'analyse'.",
                'type':    'success',
                'sticky':  False,
            },
        }

    def get_ai_progress(self):
        """
        Methode legere appelee par le widget OWL pour connaitre la
        progression. Retourne un dict simple (pas d'action UI).
        Interroge le microservice et met a jour la session si terminee.
        """
        self.ensure_one()

        # Pas d'analyse en cours : on renvoie juste l'etat courant.
        if not self.ai_task_id or self.ai_analysis_state != 'processing':
            return {
                'state': self.ai_analysis_state or 'not_started',
                'progress': 100 if self.ai_analysis_state == 'done' else 0,
                'risk_score': self.ai_risk_score,
                'risk_level': self.ai_risk_level or '',
                'alerts_count': self.ai_alerts_count,
            }

        # Mode LOCAL : le CRON met a jour la session directement. On ne
        # fait aucun appel HTTP, on renvoie l'etat + la progression reelle.
        if hasattr(self, 'action_analyze_video_local'):
            if self.ai_analysis_state == 'done':
                progress = 100
            elif self.ai_analysis_state == 'error':
                progress = 0
            else:
                # Progression reelle stockee par le pipeline (ai_progress),
                # avec un plancher a 5% pour montrer que ca demarre.
                progress = max(5, getattr(self, 'ai_progress', 0) or 0)
            # Relit depuis la base pour avoir la valeur commitee par le CRON.
            try:
                self.env.cr.execute(
                    "SELECT ai_analysis_state, ai_progress FROM "
                    "exam_proctoring_session WHERE id = %s", (self.id,))
                row = self.env.cr.fetchone()
            except Exception:  # noqa: BLE001
                # Colonne ai_progress absente (module local non installe).
                row = None
            if row:
                db_state, db_progress = row
                if db_state == 'done':
                    progress = 100
                elif db_state == 'error':
                    progress = 0
                elif db_progress:
                    progress = max(5, db_progress)
                return {
                    'state': db_state or 'processing',
                    'progress': progress,
                    'risk_score': self.ai_risk_score,
                    'risk_level': self.ai_risk_level or '',
                    'alerts_count': self.ai_alerts_count,
                }
            return {
                'state': self.ai_analysis_state or 'processing',
                'progress': progress,
                'risk_score': self.ai_risk_score,
                'risk_level': self.ai_risk_level or '',
                'alerts_count': self.ai_alerts_count,
            }

        # Analyse en cours : on interroge le microservice.
        base_url = self._get_ai_service_url()
        try:
            resp = requests.get(
                '%s/analyze/status/%s' % (base_url, self.ai_task_id),
                timeout=10,
            )
        except requests.exceptions.RequestException:
            return {'state': 'processing', 'progress': self._peek_progress()}

        # Tache disparue (service redemarre) : on remet a zero.
        if resp.status_code == 404:
            self.write({'ai_task_id': False, 'ai_analysis_state': 'not_started'})
            return {'state': 'not_started', 'progress': 0,
                    'error': 'Analyse perdue (service redemarre). Relancez.'}

        try:
            data = resp.json()
        except ValueError:
            return {'state': 'processing', 'progress': 0}

        state = data.get('status')
        progress = data.get('progress', 0)

        if state == 'error':
            self.ai_analysis_state = 'error'
            return {'state': 'error', 'progress': 0,
                    'error': data.get('error_message', 'Erreur inconnue')}

        if state != 'done':
            # Toujours en cours : on renvoie la progression.
            return {'state': 'processing', 'progress': progress}

        # Termine : on rapatrie le resultat complet.
        try:
            self._fetch_ai_result_core()
        except Exception as exc:
            _logger.warning('[Proctoring IA] Fetch final echoue : %s', exc)
            return {'state': 'processing', 'progress': 95}

        return {
            'state': 'done',
            'progress': 100,
            'risk_score': self.ai_risk_score,
            'risk_level': self.ai_risk_level or '',
            'alerts_count': self.ai_alerts_count,
        }

    def _peek_progress(self):
        """Valeur de progression de repli (best-effort)."""
        return 50

    def action_fetch_ai_result(self):
        """Interroge le microservice pour recuperer le score et le rapport.
        Version bouton : renvoie une notification UI."""
        self.ensure_one()
        result_state, progress = self._fetch_ai_result_core()

        if result_state == 'not_ready':
            return {
                'type': 'ir.actions.client',
                'tag':  'display_notification',
                'params': {
                    'title':   "Analyse en cours",
                    'message': "Progression : %s%%. Reessayez bientot." % progress,
                    'type':    'warning',
                    'sticky':  False,
                },
            }
        if result_state == 'done':
            return {
                'type': 'ir.actions.client',
                'tag':  'display_notification',
                'params': {
                    'title':   "Analyse terminee",
                    'message': "Score de risque : %s/100 (%s)." % (
                        self.ai_risk_score, self.ai_risk_level),
                    'type':    'success',
                    'sticky':  False,
                },
            }
        return True

    def _fetch_ai_result_core(self):
        """
        Logique metier de recuperation (sans UI). Retourne un tuple
        (etat, progression) :
          ('not_ready', pct) : analyse pas encore finie
          ('done', 100)      : resultat recupere et stocke
        Utilisable par le bouton ET par le cron.
        """
        self.ensure_one()
        if not self.ai_task_id:
            raise UserError("Aucune analyse en cours. Lancez d'abord l'analyse.")

        # Mode LOCAL : le CRON de digii_proctoring_ai remplit deja la session.
        # Rien a recuperer via HTTP : on renvoie l'etat courant.
        if hasattr(self, 'action_analyze_video_local'):
            if self.ai_analysis_state == 'done':
                return ('done', 100)
            if self.ai_analysis_state == 'error':
                return ('error', 0)
            return ('not_ready', 50)

        base_url = self._get_ai_service_url()

        # 1. Verifier le statut
        try:
            status_resp = requests.get(
                '%s/analyze/status/%s' % (base_url, self.ai_task_id),
                timeout=15,
            )
        except requests.exceptions.ConnectionError:
            raise UserError(
                "Impossible de joindre le service d'analyse IA.\n"
                "Verifiez qu'il tourne (uvicorn)."
            )
        except requests.exceptions.RequestException as exc:
            raise UserError("Erreur de connexion au service IA : %s" % exc)

        # Tache introuvable : le service a ete redemarre (memoire effacee).
        # On remet l'etat a zero pour permettre de relancer l'analyse.
        if status_resp.status_code == 404:
            self.write({
                'ai_task_id':        False,
                'ai_analysis_state': 'not_started',
            })
            raise UserError(
                "L'analyse precedente n'existe plus (le service a ete "
                "redemarre). Cliquez sur 'Analyser la video (IA)' pour "
                "relancer une nouvelle analyse."
            )

        try:
            status_resp.raise_for_status()
            status_data = status_resp.json()
        except requests.exceptions.RequestException as exc:
            raise UserError("Erreur de connexion au service IA : %s" % exc)

        state = status_data.get('status')
        progress = status_data.get('progress', 0)

        if state == 'error':
            self.ai_analysis_state = 'error'
            raise UserError(
                "L'analyse a echoue : %s"
                % status_data.get('error_message', 'raison inconnue')
            )

        if state != 'done':
            return 'not_ready', progress

        # 2. Recuperer le resultat JSON
        try:
            result_resp = requests.get(
                '%s/analyze/result/%s' % (base_url, self.ai_task_id),
                timeout=15,
            )
            result_resp.raise_for_status()
            result = result_resp.json()
        except requests.exceptions.RequestException as exc:
            raise UserError("Erreur recuperation resultat : %s" % exc)

        vals = {
            'ai_analysis_state': 'done',
            'ai_risk_score':     result.get('risk_score', 0),
            'ai_risk_level':     result.get('risk_level', 'none'),
            'ai_alerts_count':   len(result.get('events', [])),
        }

        interp = result.get('interpretation') or {}
        if interp:
            vals.update({
                'ai_conclusion':     interp.get('conclusion', ''),
                'ai_interpretation': interp.get('interpretation', ''),
                'ai_recommendation': interp.get('recommendation', ''),
            })

        # 3. Recuperer le PDF
        if result.get('report_available'):
            try:
                report_resp = requests.get(
                    '%s/analyze/report/%s' % (base_url, self.ai_task_id),
                    timeout=30,
                )
                report_resp.raise_for_status()
                vals['ai_report'] = base64.b64encode(report_resp.content)
                vals['ai_report_filename'] = 'rapport_proctoring_%s.pdf' % self.id
            except requests.exceptions.RequestException as exc:
                _logger.warning('[Proctoring IA] PDF non recupere : %s', exc)

        self.write(vals)
        _logger.info(
            '[Proctoring IA] Resultat session %s : score=%s niveau=%s',
            self.id, vals['ai_risk_score'], vals['ai_risk_level'],
        )
        return 'done', 100

    # ---------------------------------------------------------------
    # WebRTC Signaling
    # ---------------------------------------------------------------

    def set_offer(self, sdp):
        self.ensure_one()
        if self.offer_sdp == sdp:
            return
        self.sudo().write({'offer_sdp': sdp, 'answer_sdp': False, 'ice_candidates': '[]'})
        self.sudo()._notify_proctor('new_offer', {
            'session_id':   self.id,
            'partner_name': self.partner_id.name,
        })

    def set_answer(self, sdp):
        self.ensure_one()
        self.sudo().write({'answer_sdp': sdp})
        self.sudo()._notify_candidate('answer_sdp', {'sdp': sdp})

    def add_ice_candidate(self, candidate, source='candidate'):
        self.ensure_one()
        try:
            candidates = json.loads(self.ice_candidates or '[]')
        except (json.JSONDecodeError, TypeError):
            candidates = []
        candidates.append({'candidate': candidate, 'source': source})
        self.sudo().write({'ice_candidates': json.dumps(candidates)})
        if source == 'candidate':
            self.sudo()._notify_proctor('ice_candidate', {
                'session_id': self.id,
                'candidate':  candidate,
            })
        else:
            self.sudo()._notify_candidate('ice_candidate', {'candidate': candidate})

    # ---------------------------------------------------------------
    # Notifications bus Odoo
    # ---------------------------------------------------------------

    def _notify_candidate(self, event_type, data):
        self.ensure_one()
        channel = f'exam_proctoring_candidate_{self.partner_id.id}'
        payload = {'type': event_type, 'session_id': self.id, **data}
        self.env['bus.bus']._sendone(channel, 'exam_proctoring', payload)

    def _notify_proctor(self, event_type, data):
        channel = f'exam_proctoring_dashboard_{self.survey_id.id}'
        payload = {'type': event_type, **data}
        self.env['bus.bus']._sendone(channel, 'exam_proctoring', payload)

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    @api.model
    def _generate_access_token(self):
        import secrets
        return secrets.token_urlsafe(32)

    @api.model
    def create_session(self, survey_id, partner_id):
        existing = self.sudo().search([
            ('survey_id',  '=', survey_id),
            ('partner_id', '=', partner_id),
            ('state', 'in', ('waiting', 'authorized', 'in_exam')),
        ], limit=1)
        if existing:
            return existing

        token = self._generate_access_token()
        user  = self.env['res.users'].sudo().search(
            [('partner_id', '=', partner_id)], limit=1)

        return self.sudo().create({
            'survey_id':    survey_id,
            'partner_id':   partner_id,
            'user_id':      user.id if user else False,
            'access_token': token,
            'state':        'waiting',
        })
