# -*- coding: utf-8 -*-
from odoo import models, fields


class DigiiExamCertificate(models.Model):
    _name = 'digii.exam.certificate'
    _description = 'Certificat examen'

    certificate_number = fields.Char('N° certificat', required=True, copy=False, readonly=True,
                                     default=lambda self: self.env['ir.sequence'].next_by_code(
                                         'digii.exam.certificate'))

    student_id = fields.Many2one('res.users', 'Étudiant', required=True)
    exam_id = fields.Many2one('survey.survey', 'Examen', required=True)
    attempt_id = fields.Many2one('digii.exam.attempt', 'Tentative', required=True)
    course_id = fields.Many2one('slide.channel', related='exam_id.course_id', store=True)

    score = fields.Float('Score (%)', required=True)
    issue_date = fields.Date('Date émission', required=True, default=fields.Date.today)