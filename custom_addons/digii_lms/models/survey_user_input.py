# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SurveyUserInput(models.Model):
    _inherit = 'survey.user_input'

    exam_attempt_id = fields.Many2one('digii.exam.attempt', 'Tentative examen')
    remaining_time = fields.Integer('Temps restant (sec)', compute='_compute_remaining_time')

    @api.depends('exam_attempt_id.start_time', 'survey_id.time_limit_minutes')
    def _compute_remaining_time(self):
        for rec in self:
            if not rec.survey_id.enable_timer or not rec.exam_attempt_id:
                rec.remaining_time = 0
                continue

            if rec.state == 'done':
                rec.remaining_time = 0
                continue

            elapsed = (fields.Datetime.now() - rec.exam_attempt_id.start_time).total_seconds()
            limit = rec.survey_id.time_limit_minutes * 60
            rec.remaining_time = max(0, int(limit - elapsed))

    def _mark_done(self):
        res = super()._mark_done()
        for rec in self:
            if rec.exam_attempt_id:
                rec.exam_attempt_id._finalize_attempt()
        return res