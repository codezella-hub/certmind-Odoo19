# -*- coding: utf-8 -*-
from odoo import models, fields

class SurveyUserInputLine(models.Model):
    _inherit = 'survey.user_input_line'

    ai_feedback = fields.Text('Feedback AI')
    ai_score = fields.Float('Score AI')
    answer_true_false = fields.Boolean('Réponse V/F')