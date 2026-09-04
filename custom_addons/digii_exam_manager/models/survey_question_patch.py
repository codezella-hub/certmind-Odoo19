# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SurveyQuestionPatch(models.Model):
    """
    Extension de survey.question pour :
    1. Rendre survey_id optionnel (nullable) → question indépendante dans la banque
    2. Ajouter les champs de classification (catégorie, difficulté)
    3. Flag is_bank_question pour distinguer banque vs question d'examen
    """
    _inherit = 'survey.question'

    # --- Rendre survey_id optionnel ---
    # On redéfinit le champ pour passer ondelete='cascade' → 'set null'
    # et supprimer l'obligation implicite du champ
    survey_id = fields.Many2one(
        'survey.survey',
        string='Survey',
        ondelete='set null',        # était 'cascade' → on ne supprime plus la question si le survey est supprimé
        required=False,             # devient optionnel → question peut exister sans survey (banque)
        index='btree_not_null',
    )

    # --- Champs banque de questions ---
    is_bank_question = fields.Boolean(
        'Question banque',
        default=False,
        help="Si coché, cette question appartient à la banque et n'est pas directement liée à un examen.",
    )
    exam_category_id = fields.Many2one(
        'exam.category',
        string='Catégorie',
        index=True,
        domain="[('parent_id', '=', False)]",
        help="Catégorie thématique de la question (ex: Python, SQL, Réseau...). "
             "Seules les catégories de premier niveau peuvent etre choisies ici. "
             "Pour affiner, utilisez la sous-catégorie.",
    )
    exam_subcategory_id = fields.Many2one(
        'exam.category',
        string='Sous-catégorie',
        index=True,
        domain="[('parent_id', '=', exam_category_id)]",
        help="Sous-catégorie thématique de la question (ex: Python > POO, SQL > JOIN). "
             "La sous-catégorie est filtrée automatiquement selon la catégorie choisie. "
             "Optionnel : laissez vide si la question est generique a la categorie.",
    )
    exam_difficulty = fields.Selection([
        ('easy',   'Facile'),
        ('medium', 'Moyen'),
        ('hard',   'Difficile'),
    ], string='Difficulté', index=True)

    # Type cognitif de la question (taxonomie de Bloom simplifiee).
    # NOTE : on n'utilise PAS 'question_type' car ce nom existe deja dans
    # le module survey natif (type technique : simple_choice, text_box...).
    cognitive_type = fields.Selection([
        ('memory',        'Mémoire (restitution)'),
        ('comprehension', 'Compréhension'),
        ('application',   'Application'),
        ('analysis',      'Analyse'),
        ('experience',    'Expérience pratique'),
    ], string='Type cognitif', index=True,
        help="Type cognitif : ce que la question demande au candidat.\n"
             "- Mémoire : se souvenir d'un fait\n"
             "- Compréhension : expliquer, interpréter\n"
             "- Application : utiliser dans un cas concret\n"
             "- Analyse : décomposer, comparer, critiquer\n"
             "- Expérience : savoir-faire pratique, terrain")

    # Taux de reussite reel (calcule apres les examens - preparation niveau 4).
    success_rate = fields.Float(
        'Taux de réussite (%)', readonly=True, default=0.0,
        help="Pourcentage de candidats ayant bien répondu. Se remplit "
             "automatiquement au fil des examens. 0 tant qu'il n'y a pas "
             "assez de données.")
    times_answered = fields.Integer(
        'Nombre de fois posée', readonly=True, default=0,
        help="Combien de fois cette question a été répondue en examen.")

    # --- Onchanges pour la coherence cat / sous-cat ---
    @api.onchange('exam_category_id')
    def _onchange_exam_category_id(self):
        """Si on change la cat parente et que la sous-cat actuelle ne lui
        appartient pas, on vide la sous-cat pour eviter les incoherences."""
        if self.exam_subcategory_id and self.exam_subcategory_id.parent_id != self.exam_category_id:
            self.exam_subcategory_id = False

    @api.onchange('exam_subcategory_id')
    def _onchange_exam_subcategory_id(self):
        """Si on choisit une sous-cat sans avoir choisi de cat parente,
        on remplit auto la cat parente."""
        if self.exam_subcategory_id and not self.exam_category_id:
            self.exam_category_id = self.exam_subcategory_id.parent_id

    @api.constrains('exam_category_id', 'exam_subcategory_id')
    def _check_subcategory_consistency(self):
        """Verifier que la sous-cat est bien fille de la cat principale."""
        for q in self:
            if q.exam_subcategory_id and q.exam_category_id:
                if q.exam_subcategory_id.parent_id != q.exam_category_id:
                    raise ValidationError(_(
                        "La sous-categorie '%(sub)s' n'appartient pas a la "
                        "categorie '%(cat)s'.",
                        sub=q.exam_subcategory_id.name,
                        cat=q.exam_category_id.name,
                    ))

    # Référence à la question source dans la banque
    # (rempli uniquement sur les copies générées dans un examen)
    bank_question_id = fields.Many2one(
        'survey.question',
        string='Question source (banque)',
        ondelete='set null',
        help="Question originale dans la banque dont cette question est une copie.",
        domain=[('is_bank_question', '=', True)],
    )

    # Marqueur : élément (question OU section) créé par la génération auto.
    # Permet de tout nettoyer proprement à la régénération (y compris les
    # sections is_page, qui n'ont pas de bank_question_id).
    exam_generated_item = fields.Boolean(
        'Élément généré (examen)',
        default=False,
        copy=False,
        index=True,
        help="Coché sur les questions ET sections créées automatiquement "
             "lors de la génération aléatoire d'un examen.",
    )

    # --- Compute : scoring_type devient safe quand survey_id est False ---
    # Le champ scoring_type est un related de survey_id.scoring_type
    # On le redéfinit pour ne pas crasher quand survey_id est vide
    scoring_type = fields.Selection(
        related='survey_id.scoring_type',
        string='Scoring Type',
        readonly=True,
        # store=False par défaut sur un related → pas de pb de migration
    )

    # ------------------------------------------------------------------
    # Recalcul manuel de survey.exam_category_ids
    # ------------------------------------------------------------------
    # survey.survey.exam_category_ids ne peut PAS être recalculé via
    # @api.depends('question_ids.exam_category_id', ...) : question_ids
    # est un One2many non stocké côté survey.survey, et Odoo plante avec
    # "Cannot convert survey.survey.question_ids to SQL because it is not
    # stored" dès qu'une question est créée/copiée (ex: génération
    # aléatoire des questions d'examen). On déclenche donc le recalcul
    # manuellement ici, côté survey.question (qui a bien survey_id stocké).

    @api.model_create_multi
    def create(self, vals_list):
        questions = super().create(vals_list)
        surveys = questions.mapped('survey_id')
        if surveys:
            surveys._trigger_exam_category_ids_recompute()
        return questions

    def write(self, vals):
        old_surveys = self.mapped('survey_id') if 'survey_id' in vals else self.env['survey.survey']
        res = super().write(vals)
        if {'exam_category_id', 'exam_subcategory_id', 'survey_id'} & vals.keys():
            surveys = old_surveys | self.mapped('survey_id')
            if surveys:
                surveys._trigger_exam_category_ids_recompute()
        return res

    def unlink(self):
        surveys = self.mapped('survey_id')
        res = super().unlink()
        if surveys:
            surveys._trigger_exam_category_ids_recompute()
        return res
