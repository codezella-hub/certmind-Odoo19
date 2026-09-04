# -*- coding: utf-8 -*-
"""
Proposition de regle de generation produite par le co-pilote IA.

Modele persistant (pas transitoire) pour pouvoir afficher les cartes,
recalculer la faisabilite, et tracer l'historique par session.

La faisabilite reprend EXACTEMENT la logique de filtrage de
exam.generation.rule._get_question_pool : on compte les questions de la
banque (is_bank_question=True, sans survey) qui correspondent aux filtres,
afin d'avertir l'admin si le pool est insuffisant.
"""
from odoo import api, fields, models, _


class DigiiAiRuleProposal(models.Model):
    _name = 'digii.ai.rule.proposal'
    _description = 'Proposition de regle (co-pilote IA)'
    _order = 'sequence, id'

    session_id = fields.Many2one(
        'digii.ai.generation.session', string='Session IA',
        required=True, ondelete='cascade', index=True,
    )
    survey_id = fields.Many2one(
        'survey.survey', string='Examen cible',
        required=True, ondelete='cascade',
    )
    sequence = fields.Integer('Sequence', default=10)
    name = fields.Char('Libelle', required=True, default='Regle IA')

    exam_category_id = fields.Many2one('exam.category', string='Categorie')
    exam_subcategory_id = fields.Many2one('exam.category', string='Sous-categorie')
    exam_difficulty = fields.Selection([
        ('easy', 'Facile'),
        ('medium', 'Moyen'),
        ('hard', 'Difficile'),
    ], string='Difficulte')

    cognitive_type = fields.Selection([
        ('memory', 'Mémoire'),
        ('comprehension', 'Compréhension'),
        ('application', 'Application'),
        ('analysis', 'Analyse'),
        ('experience', 'Expérience'),
    ], string='Type cognitif')

    reason = fields.Char('Justification', help="Pourquoi l'IA propose cette règle.")

    count = fields.Integer('Nb questions demandees', default=5)

    available_count = fields.Integer(
        'Questions disponibles', compute='_compute_available_count',
    )
    is_feasible = fields.Boolean(
        'Faisable', compute='_compute_available_count',
    )

    state = fields.Selection([
        ('proposed', 'Proposee'),
        ('accepted', 'Acceptee'),
        ('rejected', 'Rejetee'),
    ], string='Statut', default='proposed', required=True)

    rule_id = fields.Many2one(
        'exam.generation.rule', string='Regle creee', readonly=True,
        help="Regle reelle creee sur l'examen lors de l'acceptation.",
    )

    # ------------------------------------------------------------------
    # Faisabilite : meme logique que exam.generation.rule._get_question_pool
    # ------------------------------------------------------------------

    @api.depends('exam_category_id', 'exam_subcategory_id', 'exam_difficulty', 'count')
    def _compute_available_count(self):
        for prop in self:
            available = len(prop._get_question_pool())
            prop.available_count = available
            prop.is_feasible = available >= prop.count

    def _get_question_pool(self):
        self.ensure_one()
        Question = self.env['survey.question']
        domain = [
            ('is_bank_question', '=', True),
            ('survey_id', '=', False),
            ('is_page', '=', False),
        ]
        if self.exam_subcategory_id:
            domain += [('exam_subcategory_id', '=', self.exam_subcategory_id.id)]
        elif self.exam_category_id:
            child_ids = self.exam_category_id.child_ids.ids
            all_cat_ids = [self.exam_category_id.id] + child_ids
            domain += [
                '|',
                ('exam_category_id', 'in', all_cat_ids),
                ('exam_subcategory_id', 'in', all_cat_ids),
            ]
        if self.exam_difficulty:
            domain += [('exam_difficulty', '=', self.exam_difficulty)]
        if self.cognitive_type:
            domain += [('cognitive_type', '=', self.cognitive_type)]
        return Question.search(domain)

    # ------------------------------------------------------------------
    # Acceptation -> creation de la vraie regle
    # ------------------------------------------------------------------

    def accept(self):
        """Cree la vraie exam.generation.rule sur l'examen cible."""
        created = self.env['exam.generation.rule']
        for prop in self:
            if prop.state == 'accepted' and prop.rule_id:
                continue
            rule = self.env['exam.generation.rule'].create({
                'survey_id': prop.survey_id.id,
                'name': prop.name,
                'exam_category_id': prop.exam_category_id.id or False,
                'exam_subcategory_id': prop.exam_subcategory_id.id or False,
                'exam_difficulty': prop.exam_difficulty or False,
                'cognitive_type': prop.cognitive_type or False,
                'count': prop.count,
            })
            prop.write({'state': 'accepted', 'rule_id': rule.id})
            created |= rule
        return created

    def reject(self):
        self.write({'state': 'rejected'})
        return True

    # ------------------------------------------------------------------
    # Serialisation pour le frontend
    # ------------------------------------------------------------------

    def _ai_card_data(self):
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'category': self.exam_category_id.name or '',
            'subcategory': self.exam_subcategory_id.name or '',
            'difficulty': self.exam_difficulty or '',
            'difficulty_label': dict(
                self._fields['exam_difficulty'].selection).get(
                self.exam_difficulty, ''),
            'count': self.count,
            'available_count': self.available_count,
            'is_feasible': self.is_feasible,
            'state': self.state,
            'cognitive_type': self.cognitive_type or '',
            'cognitive_label': dict(
                self._fields['cognitive_type'].selection).get(
                self.cognitive_type, ''),
            'reason': self.reason or '',
        }
