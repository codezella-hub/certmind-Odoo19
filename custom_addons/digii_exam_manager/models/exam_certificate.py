# -*- coding: utf-8 -*-
import base64
import secrets

from odoo import api, fields, models
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class ExamCertificate(models.Model):
    """
    Certificat d'examen.

    Workflow : pending -> approved / rejected

    v7 : lien vers la session de proctoring + player video Minio integre.
    Le procteur regarde la video directement dans cette fiche avant
    d'approuver ou rejeter le certificat.
    """
    _name = 'exam.certificate'
    _description = "Certificat d'examen"
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        'Numero de certificat',
        readonly=True, copy=False, default='Brouillon', tracking=True,
    )
    survey_id = fields.Many2one(
        'survey.survey', string='Examen',
        required=True, ondelete='restrict', readonly=True,
    )
    user_input_id = fields.Many2one(
        'survey.user_input', string="Session d'examen",
        required=True, ondelete='cascade', readonly=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Candidat',
        required=True, ondelete='restrict', readonly=True, tracking=True,
    )

    score_obtained  = fields.Float('Score obtenu (%)', readonly=True, digits=(5, 2))
    date_completion = fields.Datetime('Date de completion', readonly=True)

    state = fields.Selection([
        ('pending',  'En attente'),
        ('approved', 'Approuve'),
        ('rejected', 'Rejete'),
    ], string='Statut', default='pending', required=True, tracking=True)

    approved_by   = fields.Many2one('res.users', string='Approuve par', readonly=True)
    date_approved = fields.Datetime("Date d'approbation", readonly=True)

    rejection_reason = fields.Text('Motif de rejet', readonly=True, tracking=True)
    rejected_by      = fields.Many2one('res.users', string='Rejete par', readonly=True)

    # ------------------------------------------------------------------
    # Verification publique (QR code + page /certificate/verify/<token>)
    # ------------------------------------------------------------------
    verification_token = fields.Char(
        'Jeton de verification',
        compute='_compute_verification_token', store=True,
        readonly=True, copy=False, index=True,
        help="Identifiant aleatoire non devinable utilise dans l'URL "
             "publique de verification du certificat.",
    )
    verification_url = fields.Char(
        'URL de verification',
        compute='_compute_verification_url',
    )
    qr_code = fields.Binary(
        'QR code de verification',
        compute='_compute_qr_code',
    )

    @api.depends('create_date')
    def _compute_verification_token(self):
        for cert in self:
            if not cert.verification_token:
                cert.verification_token = secrets.token_urlsafe(16)

    @api.depends('verification_token')
    def _compute_verification_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for cert in self:
            if cert.verification_token:
                cert.verification_url = '%s/certificate/verify/%s' % (
                    base, cert.verification_token)
            else:
                cert.verification_url = False

    @api.depends('verification_url')
    def _compute_qr_code(self):
        Report = self.env['ir.actions.report'].sudo()
        for cert in self:
            if not cert.verification_url:
                cert.qr_code = False
                continue
            try:
                img = Report.barcode(
                    'QR', cert.verification_url,
                    width=180, height=180, quiet=1,
                )
                cert.qr_code = base64.b64encode(img)
            except Exception as exc:
                _logger.warning('[Certificate] Generation QR KO : %s', exc)
                cert.qr_code = False

    certificate_template_id = fields.Many2one(
        'exam.certificate.template', string='Template',
        compute='_compute_certificate_template_id', store=True, readonly=False,
    )

    body_text_rendered = fields.Text('Texte rendu', compute='_compute_body_text_rendered')

    # ------------------------------------------------------------------
    # Lien proctoring + video Minio
    # ------------------------------------------------------------------
    proctoring_session_id = fields.Many2one(
        'exam.proctoring.session',
        string='Session de proctoring',
        readonly=True,
        help="Session de surveillance liee a cet examen.",
    )
    has_video = fields.Boolean(
        'Video disponible',
        compute='_compute_has_video',
        store=True,
    )
    video_stream_url = fields.Char(
        'URL de la video',
        compute='_compute_video_stream_url',
        store=False,
    )
    # Player HTML genere cote Python — widget="html" dans la vue
    # Cela evite l'utilisation de t-if / t-att interdits en Odoo 19
    video_player_html = fields.Html(
        'Player video',
        compute='_compute_video_player_html',
        sanitize=False,
        store=False,
    )

    # ------------------------------------------------------------------
    # Analyse IA (delegue a la session de proctoring liee)
    # Les champs "related" refletent l'etat de l'analyse de la session,
    # pour afficher le resultat directement sur la fiche certificat.
    # ------------------------------------------------------------------
    ai_analysis_state = fields.Selection(
        related='proctoring_session_id.ai_analysis_state',
        string='Etat analyse IA', readonly=True,
    )
    ai_risk_score = fields.Integer(
        related='proctoring_session_id.ai_risk_score',
        string='Score de risque', readonly=True,
    )
    ai_risk_level = fields.Selection(
        related='proctoring_session_id.ai_risk_level',
        string='Niveau de risque', readonly=True,
    )
    ai_alerts_count = fields.Integer(
        related='proctoring_session_id.ai_alerts_count',
        string='Nb alertes', readonly=True,
    )
    ai_conclusion = fields.Text(
        related='proctoring_session_id.ai_conclusion',
        string='Conclusion IA', readonly=True,
    )
    ai_interpretation = fields.Text(
        related='proctoring_session_id.ai_interpretation',
        string='Interpretation IA', readonly=True,
    )
    ai_recommendation = fields.Text(
        related='proctoring_session_id.ai_recommendation',
        string='Recommandation IA', readonly=True,
    )
    ai_report = fields.Binary(
        related='proctoring_session_id.ai_report',
        string='Rapport PDF IA', readonly=True,
    )
    ai_report_filename = fields.Char(
        related='proctoring_session_id.ai_report_filename',
        string='Nom rapport', readonly=True,
    )

    def action_analyze_video(self):
        """Lance l'analyse IA sur la session de proctoring liee."""
        self.ensure_one()
        if not self.proctoring_session_id:
            from odoo.exceptions import UserError
            raise UserError("Aucune session de proctoring liee a ce certificat.")
        return self.proctoring_session_id.action_analyze_video()

    def action_fetch_ai_result(self):
        """Recupere le resultat de l'analyse depuis la session liee."""
        self.ensure_one()
        if not self.proctoring_session_id:
            from odoo.exceptions import UserError
            raise UserError("Aucune session de proctoring liee a ce certificat.")
        return self.proctoring_session_id.action_fetch_ai_result()

    def get_ai_progress(self):
        """Delegue la progression a la session de proctoring liee."""
        self.ensure_one()
        if not self.proctoring_session_id:
            return {'state': 'not_started', 'progress': 0}
        return self.proctoring_session_id.get_ai_progress()

    @api.depends('proctoring_session_id', 'proctoring_session_id.has_video_recording')
    def _compute_has_video(self):
        for cert in self:
            cert.has_video = bool(
                cert.proctoring_session_id
                and cert.proctoring_session_id.has_video_recording
            )

    @api.depends('proctoring_session_id', 'proctoring_session_id.video_minio_key',
                 'proctoring_session_id.video_recording')
    def _compute_video_stream_url(self):
        LK = self.env['exam.livekit.config']
        for cert in self:
            sess = cert.proctoring_session_id
            if sess and sess.video_minio_key:
                # Cas Egress/Minio
                try:
                    cert.video_stream_url = LK.get_video_stream_url(sess)
                except Exception as exc:
                    _logger.warning('[Certificate] URL video KO : %s', exc)
                    cert.video_stream_url = False
            elif sess and sess.video_recording:
                # Cas enregistrement local (WebM stocké dans Odoo)
                filename = sess.video_filename or 'recording.webm'
                cert.video_stream_url = (
                    '/web/content/exam.proctoring.session/%s/video_recording'
                    '?filename=%s&download=false' % (sess.id, filename)
                )
            else:
                cert.video_stream_url = False

    @api.depends('video_stream_url')
    def _compute_video_player_html(self):
        for cert in self:
            url = cert.video_stream_url
            if url:
                # Le champ est sanitize=False -> on peut embarquer un vrai <video>.
                cert.video_player_html = (
                    '<div style="background:#111;padding:12px;border-radius:8px;">'
                    '<p style="color:#ccc;font-size:13px;margin:0 0 8px 0;">'
                    '<b>&#127909; Enregistrement vidéo de l\'examen</b></p>'
                    '<video controls preload="metadata" '
                    'style="width:100%;max-height:480px;border-radius:6px;background:#000;">'
                    '<source src="' + url + '"/>'
                    'Votre navigateur ne supporte pas la lecture vidéo.'
                    '</video>'
                    '<p style="margin:8px 0 0 0;">'
                    '<a href="' + url + '" target="_blank" '
                    'style="color:#9ecbff;font-size:13px;text-decoration:none;">'
                    '&#11015; Télécharger / ouvrir dans un onglet</a></p>'
                    '</div>'
                )
            else:
                cert.video_player_html = (
                    '<p style="color:#888;padding:16px;text-align:center;">'
                    'Aucune video disponible pour le moment.'
                    '</p>'
                )

    # ------------------------------------------------------------------
    # Computes existants
    # ------------------------------------------------------------------

    @api.depends('survey_id.certificate_template_id')
    def _compute_certificate_template_id(self):
        default_template = self.env['exam.certificate.template'].search(
            [('is_default', '=', True)], limit=1
        )
        for cert in self:
            if cert.survey_id.certificate_template_id:
                cert.certificate_template_id = cert.survey_id.certificate_template_id
            else:
                cert.certificate_template_id = default_template

    @api.depends('certificate_template_id', 'partner_id', 'survey_id',
                 'score_obtained', 'date_approved', 'name')
    def _compute_body_text_rendered(self):
        for cert in self:
            template = cert.certificate_template_id
            if template and template.body_text:
                try:
                    cert.body_text_rendered = template.body_text.format(
                        candidate=cert.partner_id.name or '',
                        exam=cert.survey_id.title or '',
                        score=round(cert.score_obtained, 1),
                        date=(cert.date_approved or cert.date_completion or
                              fields.Datetime.now()).strftime('%d/%m/%Y'),
                        certificate_number=cert.name or '',
                    )
                except (KeyError, ValueError):
                    cert.body_text_rendered = template.body_text
            else:
                cert.body_text_rendered = ''

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_approve(self):
        self.ensure_one()
        if self.state != 'pending':
            raise UserError("Seuls les certificats en attente peuvent etre approuves.")
        sequence = self.env['ir.sequence'].next_by_code('exam.certificate') or 'CERT-0000'
        self.write({
            'state':         'approved',
            'name':          sequence,
            'approved_by':   self.env.uid,
            'date_approved': fields.Datetime.now(),
        })

        # Envoi de l'email de felicitations au candidat (si une adresse existe)
        if self.partner_id.email:
            template = self.env.ref(
                'digii_exam_manager.mail_template_certificate_approved',
                raise_if_not_found=False,
            )
            if template:
                try:
                    template.send_mail(self.id, force_send=True)
                except Exception as exc:
                    _logger.warning(
                        '[Certificate] Envoi email approbation KO : %s', exc)

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'exam.certificate',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'current',
        }

    def action_reject(self):
        self.ensure_one()
        if self.state != 'pending':
            raise UserError("Seuls les certificats en attente peuvent etre rejetes.")
        return {
            'type':      'ir.actions.act_window',
            'name':      'Rejeter le certificat',
            'res_model': 'exam.certificate.reject.wizard',
            'view_mode': 'form',
            'target':    'new',
            'context':   {'default_certificate_id': self.id},
        }

    def action_reset_to_pending(self):
        for cert in self:
            if cert.state != 'rejected':
                raise UserError("Seuls les certificats rejetes peuvent etre remis en attente.")
            cert.write({
                'state':            'pending',
                'rejection_reason': False,
                'rejected_by':      False,
            })

    def action_preview_certificate(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/exam/certificate/%s/admin-preview' % self.id,
            'target': 'new',
        }

    def action_refresh_video_url(self):
        """Recharge l'URL presignee Minio (24h)."""
        self.ensure_one()
        # Forcer le recalcul en invalidant le cache
        self.invalidate_recordset(['video_stream_url', 'video_player_html', 'has_video'])
        return {'type': 'ir.actions.client', 'tag': 'reload'}
