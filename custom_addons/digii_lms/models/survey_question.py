# -*- coding: utf-8 -*-
from odoo import models, fields


class SurveyQuestion(models.Model):
    _inherit = 'survey.question'

    # Ajouter type True/False
    question_type = fields.Selection(
        selection_add=[('true_false', 'Vrai/Faux')],
        ondelete={'true_false': 'cascade'}
    )

    correct_answer_true_false = fields.Boolean(
        'Réponse correcte (V/F)',
        help='Pour questions Vrai/Faux'
    )