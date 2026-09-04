# -*- coding: utf-8 -*-
from odoo import models, fields, api


class DigiiExamAttempt(models.Model):
    _name = 'digii.exam.attempt'
    _description = 'Tentative examen'
    _order = 'start_time desc'

    student_id = fields.Many2one('res.users', 'Étudiant', required=True)
    exam_id = fields.Many2one('survey.survey', 'Examen', required=True)
    user_input_id = fields.Many2one('survey.user_input', 'Réponse Survey')

    score = fields.Float('Score (%)', compute='_compute_score', store=True)
    start_time = fields.Datetime('Début', required=True, default=fields.Datetime.now)
    end_time = fields.Datetime('Fin')
    time_spent = fields.Integer('Temps (min)', compute='_compute_time_spent', store=True)

    state = fields.Selection([
        ('in_progress', 'En cours'),
        ('completed', 'Terminé'),
        ('passed', 'Réussi'),
        ('failed', 'Échoué'),
    ], default='in_progress', required=True)

    ai_remark = fields.Text('Remarque AI')
    teacher_remark = fields.Text('Remarque professeur')

    selected_question_ids = fields.Many2many('survey.question', 'Questions sélectionnées')

    certificate_id = fields.Many2one('digii.exam.certificate', 'Certificat')
    passed = fields.Boolean('Réussi', compute='_compute_passed', store=True)

    course_id = fields.Many2one('slide.channel', related='exam_id.course_id', store=True)
    attempt_number = fields.Integer('N° tentative', compute='_compute_attempt_number', store=True)

    @api.depends('user_input_id.scoring_success')
    def _compute_score(self):
        for rec in self:
            rec.score = rec.user_input_id.scoring_success if rec.user_input_id else 0.0

    @api.depends('start_time', 'end_time')
    def _compute_time_spent(self):
        for rec in self:
            if rec.start_time and rec.end_time:
                delta = rec.end_time - rec.start_time
                rec.time_spent = int(delta.total_seconds() / 60)
            else:
                rec.time_spent = 0

    @api.depends('score', 'exam_id.passing_score')
    def _compute_passed(self):
        for rec in self:
            rec.passed = rec.score >= rec.exam_id.passing_score

    @api.depends('student_id', 'exam_id', 'start_time')
    def _compute_attempt_number(self):
        for rec in self:
            previous = self.search_count([
                ('exam_id', '=', rec.exam_id.id),
                ('student_id', '=', rec.student_id.id),
                ('start_time', '<', rec.start_time)
            ])
            rec.attempt_number = previous + 1

    def _finalize_attempt(self):
        self.ensure_one()
        self.end_time = fields.Datetime.now()

        if self.passed:
            self.state = 'passed'
            if self.exam_id.enable_certificate:
                self._generate_certificate()
        else:
            self.state = 'failed'

    def _generate_certificate(self):
        self.ensure_one()
        cert = self.env['digii.exam.certificate'].create({
            'student_id': self.student_id.id,
            'exam_id': self.exam_id.id,
            'attempt_id': self.id,
            'score': self.score,
            'issue_date': fields.Date.today(),
        })
        self.certificate_id = cert.id