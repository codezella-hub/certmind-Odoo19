# -*- coding: utf-8 -*-
import json

from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError


class SurveyUserInputPatch(models.Model):
    """
    Extension de survey.user_input :
    - Crée automatiquement un exam.certificate quand un candidat
      termine un examen (is_exam=True) et atteint le score de certification.
    - Empêche de repasser un examen déjà terminé (une seule tentative).
    - Lie la session de proctoring au certificat créé afin que le
      procteur retrouve la vidéo directement dans la fiche certificat.
    """
    _inherit = 'survey.user_input'

    certificate_id = fields.Many2one(
        'exam.certificate', string='Certificat', readonly=True, copy=False,
    )

    # ------------------------------------------------------------------
    # REJET / DISQUALIFICATION
    # Marque cet examen comme « rejeté » lorsque le procteur rejette ou
    # exclut le candidat, ou quand son certificat est rejeté.
    # ------------------------------------------------------------------
    is_proctoring_rejected = fields.Boolean(
        'Examen rejeté', default=False, copy=False, readonly=True,
        help="Coché lorsque le candidat a été rejeté/exclu sur cet examen.",
    )
    proctoring_rejection_reason = fields.Text(
        'Motif du rejet', copy=False, readonly=True,
    )

    def mark_exam_rejected(self, reason=''):
        """Marque le(s) user_input comme rejeté(s) sur l'examen."""
        for ui in self:
            ui.sudo().write({
                'is_proctoring_rejected': True,
                'proctoring_rejection_reason': reason or 'Rejeté par le procteur.',
            })
        return True

    # ------------------------------------------------------------------
    # GRILLE DE NAVIGATION
    # ------------------------------------------------------------------

    def get_answered_question_ids(self):
        self.ensure_one()
        lines = self.user_input_line_ids.filtered(lambda l: not l.skipped)
        return list(set(lines.mapped('question_id').ids))

    def get_question_grid_json(self):
        """Construit les donnees de la grille de navigation laterale.

        Pour permettre la NAVIGATION (saut direct a une question/section) tout
        en respectant le mode natif `questions_layout`, on expose pour chaque
        question :
          - id        : id de la question (cible en mode page_per_question)
          - num       : numero d'affichage (1..N)
          - title     : intitule
          - page_id   : id de la section parente (cible en mode
                        page_per_section ; False si la question n'a pas de
                        section)

        On expose aussi le mode `layout` du survey pour que le JS sache
        comment se comporter au clic :
          - one_page          -> scroll vers la question (tout est dans le DOM)
          - page_per_question -> saut serveur en ciblant question.id
          - page_per_section  -> saut serveur en ciblant page_id (section)
        """
        self.ensure_one()
        questions = self.predefined_question_ids
        if not questions:
            questions = self.survey_id.question_ids.filtered(lambda q: not q.is_page)
        grid = [
            {
                'id':      q.id,
                'num':     i + 1,
                'title':   q.title or '',
                'page_id': q.page_id.id if q.page_id else False,
            }
            for i, q in enumerate(questions)
        ]
        answered = self.get_answered_question_ids()
        return {
            'grid_json':    json.dumps(grid),
            'answered_json': json.dumps(answered),
            'layout':       self.survey_id.questions_layout or 'page_per_question',
        }

    # ------------------------------------------------------------------
    # ANTI-REPASSAGE
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            survey_id  = vals.get('survey_id')
            partner_id = vals.get('partner_id')
            if not survey_id or not partner_id:
                continue
            survey = self.env['survey.survey'].sudo().browse(survey_id)
            if not survey.exists():
                continue
            if not (survey.is_exam or survey.is_certification):
                continue
            existing = self.sudo().search([
                ('survey_id',  '=', survey_id),
                ('partner_id', '=', partner_id),
                ('state',      '=', 'done'),
            ], limit=1)
            if existing:
                raise UserError(_(
                    "Vous avez déjà passé cet examen. "
                    "Une seule tentative est autorisée."
                ))
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # _mark_done — point central de fin d'examen
    # ------------------------------------------------------------------

    def _mark_done(self):
        """
        Surcharge : après le traitement natif Odoo,
        1. Clôture la session de proctoring et arrête l'Egress.
        2. Crée le certificat si le score est atteint.
        3. Lie la session de proctoring au certificat
           (pour que le procteur voie la vidéo dans la fiche certif).
        """
        res = super()._mark_done()

        for user_input in self:
            survey = user_input.survey_id

            # --------------------------------------------------------
            # 1. Clôturer la session de proctoring
            # --------------------------------------------------------
            proctoring_session = self.env['exam.proctoring.session'].sudo().search([
                ('user_input_id', '=', user_input.id),
                ('state', 'in', ('in_exam', 'authorized')),
            ], limit=1)

            if not proctoring_session:
                # Fallback par survey + partner si user_input_id pas encore lié
                proctoring_session = self.env['exam.proctoring.session'].sudo().search([
                    ('survey_id',  '=', survey.id),
                    ('partner_id', '=', user_input.partner_id.id),
                    ('state', 'in', ('in_exam', 'authorized')),
                ], limit=1)

            if proctoring_session:
                proctoring_session.action_complete()
                proctoring_session._notify_proctor('exam_completed', {
                    'session_id':   proctoring_session.id,
                    'partner_name': user_input.partner_id.name or '',
                })

            # --------------------------------------------------------
            # 2. Vérifications pour la création du certificat
            # --------------------------------------------------------
            if not survey.is_certification:
                continue
            if not survey.scoring_success_min:
                continue
            if user_input.scoring_percentage < survey.scoring_success_min:
                continue

            existing = self.env['exam.certificate'].search([
                ('user_input_id', '=', user_input.id),
            ], limit=1)
            if existing:
                continue

            partner = user_input.partner_id
            if not partner:
                continue

            # --------------------------------------------------------
            # 3. Créer le certificat en statut pending
            # --------------------------------------------------------
            cert = self.env['exam.certificate'].create({
                'survey_id':            survey.id,
                'user_input_id':        user_input.id,
                'partner_id':           partner.id,
                'score_obtained':       user_input.scoring_percentage,
                'date_completion':      fields.Datetime.now(),
                'state':                'pending',
                # Lien vers la session de proctoring → la vidéo sera visible
                # directement dans la fiche certificat
                'proctoring_session_id': proctoring_session.id if proctoring_session else False,
            })
            user_input.certificate_id = cert.id

            # Mettre à jour la session de proctoring avec le lien retour
            if proctoring_session:
                proctoring_session.sudo().write({'certificate_id': cert.id})

        return res
