# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from random import sample


class SurveySurvey(models.Model):
    _inherit = 'survey.survey'

    # === EXAM FIELDS ===
    is_exam = fields.Boolean('Est un Examen', default=False)

    # Link to course
    course_id = fields.Many2one('slide.channel', string='Cours')

    # Certificate
    enable_certificate = fields.Boolean('Activer certificat', default=False)
    passing_score = fields.Float('Score minimum (%)', default=50.0)

    # Random questions
    use_random_questions = fields.Boolean('Questions aléatoires', default=False)
    number_of_questions = fields.Integer('Nombre de questions à afficher', default=10)

    # Attempts
    max_attempts = fields.Integer('Tentatives maximum', default=3)

    # Timer
    enable_timer = fields.Boolean('Activer minuterie', default=False)
    time_limit_minutes = fields.Integer('Durée (minutes)', default=60)

    # AI
    enable_ai_evaluation = fields.Boolean('Évaluation AI', default=False)

    # Stats
    attempt_ids = fields.One2many('digii.exam.attempt', 'exam_id', string='Tentatives')
    attempt_count = fields.Integer('Total tentatives', compute='_compute_attempt_count')

    @api.depends('attempt_ids')
    def _compute_attempt_count(self):
        for rec in self:
            rec.attempt_count = len(rec.attempt_ids)

    @api.constrains('use_random_questions', 'number_of_questions')
    def _check_random_questions(self):
        for rec in self:
            if rec.use_random_questions:
                total = len(rec.question_ids)
                if rec.number_of_questions > total:
                    raise ValidationError(
                        f'Nombre de questions ({rec.number_of_questions}) > total ({total})'
                    )

    def _check_student_access(self, student_id):
        """Vérifier accès étudiant via digii.class"""
        self.ensure_one()
        if not self.is_exam or not self.course_id:
            return True

        classes = self.env['digii.class'].search([
            ('course_ids', 'in', self.course_id.id),
            ('student_ids', 'in', student_id)
        ])

        if not classes:
            raise UserError("Vous n'êtes pas inscrit à une classe contenant ce cours.")
        return True

    def _check_attempt_limit(self, student_id):
        """Vérifier limite de tentatives"""
        self.ensure_one()
        count = self.env['digii.exam.attempt'].search_count([
            ('exam_id', '=', self.id),
            ('student_id', '=', student_id)
        ])
        if count >= self.max_attempts:
            raise UserError(f'Limite de {self.max_attempts} tentatives atteinte.')
        return True

    def _get_random_questions(self):
        """Sélectionner questions aléatoires"""
        self.ensure_one()
        if not self.use_random_questions:
            return self.question_ids

        all_ids = self.question_ids.ids
        if len(all_ids) <= self.number_of_questions:
            return self.question_ids

        selected = sample(all_ids, self.number_of_questions)
        return self.env['survey.question'].browse(selected)

    def action_start_exam(self):
        """Démarrer un examen"""
        self.ensure_one()
        student = self.env.user

        # Validations
        self._check_student_access(student.id)
        self._check_attempt_limit(student.id)

        # Créer survey.user_input (modèle Odoo existant)
        user_input = self.env['survey.user_input'].create({
            'survey_id': self.id,
            'partner_id': student.partner_id.id,
            'state': 'in_progress',
        })

        # Créer tentative
        attempt = self.env['digii.exam.attempt'].create({
            'exam_id': self.id,
            'student_id': student.id,
            'user_input_id': user_input.id,
            'start_time': fields.Datetime.now(),
        })

        # Questions aléatoires
        if self.use_random_questions:
            selected = self._get_random_questions()
            attempt.selected_question_ids = [(6, 0, selected.ids)]

        return {
            'type': 'ir.actions.act_url',
            'url': f'/survey/start/{self.access_token}?answer_token={user_input.access_token}',
            'target': 'self',
        }