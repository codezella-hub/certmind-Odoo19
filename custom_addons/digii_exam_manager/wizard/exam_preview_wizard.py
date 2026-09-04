# -*- coding: utf-8 -*-
import random

from odoo import api, fields, models
from odoo.exceptions import UserError


class ExamPreviewWizard(models.TransientModel):
    """
    Wizard de prévisualisation des questions avant génération.

    Permet à l'utilisateur de :
    1. Voir combien de questions sont disponibles par règle
    2. Simuler un tirage aléatoire et voir les questions qui seraient sélectionnées
    3. Confirmer la génération ou annuler

    Ce wizard ne modifie rien tant que l'utilisateur ne confirme pas.
    """
    _name = 'exam.preview.wizard'
    _description = 'Prévisualisation des questions avant génération'

    survey_id = fields.Many2one(
        'survey.survey',
        string='Examen',
        required=True,
        readonly=True,
        ondelete='cascade',
    )

    # Lignes de prévisualisation (une par règle)
    preview_line_ids = fields.One2many(
        'exam.preview.wizard.line',
        'wizard_id',
        string='Règles',
        readonly=True,
    )

    # Toutes les questions simulées à plat (pour affichage dans la vue)
    all_question_preview_ids = fields.One2many(
        'exam.preview.wizard.question',
        'wizard_id',
        string='Toutes les questions simulées',
        readonly=True,
    )

    # Résumé global
    total_requested = fields.Integer(
        'Total demandé',
        compute='_compute_totals',
    )
    total_available = fields.Integer(
        'Total disponible',
        compute='_compute_totals',
    )
    total_will_generate = fields.Integer(
        'Total qui sera généré',
        compute='_compute_totals',
    )
    has_warnings = fields.Boolean(
        'Avertissements',
        compute='_compute_totals',
    )

    @api.depends('preview_line_ids.count_requested',
                 'preview_line_ids.count_available',
                 'preview_line_ids.count_will_generate')
    def _compute_totals(self):
        for wiz in self:
            wiz.total_requested     = sum(wiz.preview_line_ids.mapped('count_requested'))
            wiz.total_available     = sum(wiz.preview_line_ids.mapped('count_available'))
            wiz.total_will_generate = sum(wiz.preview_line_ids.mapped('count_will_generate'))
            wiz.has_warnings        = any(
                line.count_available < line.count_requested
                for line in wiz.preview_line_ids
            )

    # -------------------------------------------------------------------------
    # Méthode de création : calcul automatique des previews
    # -------------------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        survey_id = self.env.context.get('default_survey_id') or \
                    self.env.context.get('active_id')
        if not survey_id:
            return res

        survey = self.env['survey.survey'].browse(survey_id)
        if not survey.exists() or not survey.is_exam:
            raise UserError("Ce survey n'est pas configuré comme un examen.")
        if not survey.generation_rule_ids:
            raise UserError("Veuillez d'abord définir des règles de génération.")

        res['survey_id'] = survey.id

        lines = []
        all_questions = []

        for rule in survey.generation_rule_ids.sorted('sequence'):
            pool = rule._get_question_pool()
            count_available = len(pool)
            count_will_generate = min(rule.count, count_available)

            # Simuler le tirage (avec couverture si activee sur la regle)
            sampled_ids, _w = rule.pick_question_ids()
            if sampled_ids:
                sampled_questions = self.env['survey.question'].browse(sampled_ids)
            else:
                sampled_questions = self.env['survey.question']

            # Construire les sous-lignes (questions simulées)
            question_lines = []
            for q in sampled_questions:
                q_vals = {
                    'question_id':      q.id,
                    'question_title':   q.title,
                    'question_type':    q.question_type,
                    'cognitive_type':   q.cognitive_type,
                    'exam_category_id': q.exam_category_id.id if q.exam_category_id else False,
                    'exam_subcategory_id': q.exam_subcategory_id.id if q.exam_subcategory_id else False,
                    'exam_difficulty':  q.exam_difficulty,
                    'rule_name':        rule.name,
                    'has_warning':      count_available < rule.count,
                }
                question_lines.append((0, 0, q_vals))
                all_questions.append((0, 0, q_vals))

            lines.append((0, 0, {
                'rule_id':              rule.id,
                'rule_name':            rule.name,
                'category_name':        (
                                            (rule.exam_category_id.name + ' / ' + rule.exam_subcategory_id.name)
                                            if rule.exam_subcategory_id
                                            else (rule.exam_category_id.name if rule.exam_category_id else 'Toutes')
                                        ),
                'difficulty':           rule.exam_difficulty or 'tous',
                'cognitive_type_label': (dict(rule._fields['cognitive_type'].selection).get(
                                            rule.cognitive_type, 'Tous')
                                         if rule.cognitive_type else 'Tous'),
                'count_requested':      rule.count,
                'count_available':      count_available,
                'count_will_generate':  count_will_generate,
                'question_preview_ids': question_lines,
            }))

        res['preview_line_ids']         = lines
        res['all_question_preview_ids'] = all_questions
        return res

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def action_confirm_generate(self):
        """
        Confirme et lance la génération réelle des questions.
        """
        self.ensure_one()
        return self.survey_id.action_generate_exam_questions()

    def action_resimulate(self):
        """Relance une simulation complète (toutes les règles)."""
        self.ensure_one()
        return self._resimulate()

    def _resimulate(self):
        """Reconstruit la simulation via write() (robuste pour un transient).
        Re-tire toutes les règles."""
        self.ensure_one()

        # Supprimer les anciennes lignes.
        self.preview_line_ids.unlink()
        self.all_question_preview_ids.unlink()

        lines = []
        all_questions = []

        for rule in self.survey_id.generation_rule_ids.sorted('sequence'):
            pool = rule._get_question_pool()
            count_available = len(pool)
            count_will_generate = min(rule.count, count_available)

            if count_will_generate > 0:
                sampled_ids, _w = rule.pick_question_ids()
                sampled_questions = self.env['survey.question'].browse(sampled_ids)
            else:
                sampled_questions = self.env['survey.question']

            question_lines = []
            for q in sampled_questions:
                q_vals = {
                    'question_id':         q.id,
                    'question_title':      q.title,
                    'question_type':       q.question_type,
                    'cognitive_type':      q.cognitive_type,
                    'exam_category_id':    q.exam_category_id.id if q.exam_category_id else False,
                    'exam_subcategory_id': q.exam_subcategory_id.id if q.exam_subcategory_id else False,
                    'exam_difficulty':     q.exam_difficulty,
                    'rule_name':           rule.name,
                    'has_warning':         count_available < rule.count,
                }
                question_lines.append((0, 0, q_vals))
                all_questions.append((0, 0, dict(q_vals)))

            lines.append((0, 0, {
                'rule_id':              rule.id,
                'rule_name':            rule.name,
                'category_name':        (
                                            (rule.exam_category_id.name + ' / ' + rule.exam_subcategory_id.name)
                                            if rule.exam_subcategory_id
                                            else (rule.exam_category_id.name if rule.exam_category_id else 'Toutes')
                                        ),
                'difficulty':           rule.exam_difficulty or 'tous',
                'cognitive_type_label': (dict(rule._fields['cognitive_type'].selection).get(
                                            rule.cognitive_type, 'Tous')
                                         if rule.cognitive_type else 'Tous'),
                'count_requested':      rule.count,
                'count_available':      count_available,
                'count_will_generate':  count_will_generate,
                'question_preview_ids': question_lines,
            }))

        self.write({
            'preview_line_ids':         lines,
            'all_question_preview_ids': all_questions,
        })

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'exam.preview.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }

class ExamPreviewWizardLine(models.TransientModel):
    """
    Une ligne du wizard = une règle de génération avec ses questions simulées.
    """
    _name = 'exam.preview.wizard.line'
    _description = 'Ligne de prévisualisation'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'exam.preview.wizard',
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)

    # Infos de la règle
    rule_id       = fields.Many2one('exam.generation.rule', string='Règle', readonly=True)
    rule_name     = fields.Char('Règle', readonly=True)
    category_name = fields.Char('Catégorie', readonly=True)
    difficulty    = fields.Char('Difficulté', readonly=True)
    cognitive_type_label = fields.Char('Type cognitif', readonly=True)

    # Compteurs
    count_requested     = fields.Integer('Demandé', readonly=True)
    count_available     = fields.Integer('Disponible', readonly=True)
    count_will_generate = fields.Integer('Sera généré', readonly=True)

    has_warning = fields.Boolean(
        'Avertissement',
        compute='_compute_has_warning',
    )

    @api.depends('count_available', 'count_requested')
    def _compute_has_warning(self):
        for line in self:
            line.has_warning = line.count_available < line.count_requested

    # Questions simulées liées à cette règle
    question_preview_ids = fields.One2many(
        'exam.preview.wizard.question',
        'line_id',
        string='Questions simulées',
        readonly=True,
    )


class ExamPreviewWizardQuestion(models.TransientModel):
    """
    Une question simulée dans le wizard de prévisualisation.
    """
    _name = 'exam.preview.wizard.question'
    _description = 'Question simulée dans la prévisualisation'

    # Lien vers la ligne de règle (pour affichage groupé par règle)
    line_id = fields.Many2one(
        'exam.preview.wizard.line',
        ondelete='cascade',
    )

    # Lien direct vers le wizard (pour affichage à plat dans all_question_preview_ids)
    wizard_id = fields.Many2one(
        'exam.preview.wizard',
        ondelete='cascade',
    )

    question_id = fields.Many2one(
        'survey.question',
        string='Question',
        readonly=True,
    )
    question_title    = fields.Char('Titre', readonly=True)
    rule_name         = fields.Char('Règle', readonly=True)
    has_warning       = fields.Boolean('Avertissement', readonly=True)
    cognitive_type    = fields.Selection([
        ('memory',        'Mémoire'),
        ('comprehension', 'Compréhension'),
        ('application',   'Application'),
        ('analysis',      'Analyse'),
        ('experience',    'Expérience'),
    ], string='Type cognitif', readonly=True)
    question_type     = fields.Selection([
        ('simple_choice',   'Choix unique'),
        ('multiple_choice', 'Choix multiple'),
        ('text_box',        'Texte long'),
        ('char_box',        'Texte court'),
        ('numerical_box',   'Numérique'),
        ('scale',           'Échelle'),
        ('date',            'Date'),
        ('datetime',        'Date/Heure'),
        ('matrix',          'Matrice'),
    ], string='Type', readonly=True)
    exam_category_id  = fields.Many2one('exam.category', string='Catégorie', readonly=True)
    exam_subcategory_id = fields.Many2one('exam.category', string='Sous-catégorie', readonly=True)
    exam_difficulty   = fields.Selection([
        ('easy',   'Facile'),
        ('medium', 'Moyen'),
        ('hard',   'Difficile'),
    ], string='Difficulté', readonly=True)