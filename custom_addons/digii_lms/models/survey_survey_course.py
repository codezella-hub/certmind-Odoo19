# -*- coding: utf-8 -*-
"""
Liaison Examen <-> Cours (digii_lms).

Ce fichier ajoute UNIQUEMENT le lien pédagogique entre un examen
(survey.survey en mode is_exam) et un cours (slide.channel) :

    - course_id      : le cours auquel l'examen est rattaché.
                       Un cours -> plusieurs examens (Many2one côté examen).
    - exam_tag_ids   : les tags du cours, recopiés automatiquement sur
                       l'examen (miroir en lecture seule, tenu à jour).

Pourquoi ici et pas dans digii_exam_manager ?
    digii_exam_manager ne dépend PAS de website_slides : il ne connaît
    donc ni slide.channel ni slide.channel.tag. Toute la logique cours/tags
    appartient au domaine LMS, qui dépend des deux modules.

Note : on n'active PAS l'ancien fichier survey_survey.py (digii.exam.attempt,
scoring parallèle, etc.) qui est volontairement débranché et entrerait en
conflit avec la logique native survey.user_input utilisée par l'exam manager.
"""
from odoo import api, fields, models


class SurveySurveyCourse(models.Model):
    _inherit = 'survey.survey'

    # ------------------------------------------------------------------
    # Lien vers le cours
    # ------------------------------------------------------------------
    course_id = fields.Many2one(
        'slide.channel',
        string='Cours associé',
        ondelete='set null',
        index=True,
        help="Cours auquel cet examen est rattaché. "
             "Un cours peut avoir plusieurs examens. "
             "Visible uniquement en mode examen.",
    )

    # ------------------------------------------------------------------
    # Tags hérités du cours (miroir en lecture seule)
    # ------------------------------------------------------------------
    exam_tag_ids = fields.Many2many(
        comodel_name='slide.channel.tag',
        relation='survey_survey_slide_channel_tag_rel',
        column1='survey_id',
        column2='tag_id',
        string='Tags du cours',
        compute='_compute_exam_tag_ids',
        store=True,
        readonly=True,
        help="Tags récupérés automatiquement depuis le cours associé. "
             "Servent à la recherche et au filtrage côté portail.",
    )

    @api.depends('course_id', 'course_id.tag_ids')
    def _compute_exam_tag_ids(self):
        """L'examen reçoit tous les tags de son cours.

        Recalculé automatiquement quand :
          - on change le cours de l'examen, ou
          - on modifie les tags du cours lui-même.
        """
        for survey in self:
            if survey.course_id:
                survey.exam_tag_ids = [(6, 0, survey.course_id.tag_ids.ids)]
            else:
                survey.exam_tag_ids = [(5, 0, 0)]
