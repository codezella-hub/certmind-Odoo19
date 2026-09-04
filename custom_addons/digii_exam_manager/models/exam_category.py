# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ExamCategory(models.Model):
    """
    Categorie de questions avec hierarchie a 2 NIVEAUX MAXIMUM :

        Categorie parente  (parent_id = False)
            +-- Sous-categorie  (parent_id = parente)

    Une categorie ne peut avoir QUE des sous-categories de premier niveau.
    Une sous-categorie ne peut PAS avoir d'enfants.

    Pour la generation de questions :
      - Si une regle filtre sur une categorie parente seule -> on inclut
        AUSSI toutes les questions de ses sous-categories.
      - Si une regle filtre sur une sous-categorie -> filtre exact.
    """
    _name = 'exam.category'
    _description = 'Categorie de questions'
    _order = 'parent_id, name'
    # Active la hierarchie native Odoo (parent_path)
    _parent_name = 'parent_id'
    _parent_store = True

    name = fields.Char('Nom', required=True, translate=True)
    description = fields.Text('Description')
    color = fields.Integer('Couleur', default=0)
    active = fields.Boolean('Actif', default=True)

    # ------------------------------------------------------------------
    # HIERARCHIE : parent / enfants
    # ------------------------------------------------------------------
    parent_id = fields.Many2one(
        'exam.category',
        string='Categorie parente',
        ondelete='cascade',
        index=True,
        # Le parent ne peut etre qu'une categorie de niveau 1
        # (pas une sous-categorie)
        domain="[('parent_id', '=', False)]",
        help="Si renseigne, cette categorie est une sous-categorie. "
             "On ne peut choisir comme parent qu'une categorie de premier "
             "niveau (sans parent elle-meme).",
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many(
        'exam.category',
        'parent_id',
        string='Sous-categories',
    )
    is_subcategory = fields.Boolean(
        'Est une sous-categorie',
        compute='_compute_is_subcategory',
        store=True,
    )
    child_count = fields.Integer(
        'Nb sous-categories',
        compute='_compute_child_count',
    )

    # ------------------------------------------------------------------
    # CONTRAINTES : enforcer le 2 niveaux strict
    # ------------------------------------------------------------------
    @api.constrains('parent_id')
    def _check_max_2_levels(self):
        for cat in self:
            # 1) Le parent ne peut pas avoir lui-meme un parent
            if cat.parent_id and cat.parent_id.parent_id:
                raise ValidationError(_(
                    "Hierarchie limitee a 2 niveaux : la categorie '%(parent)s' "
                    "est deja une sous-categorie. Vous ne pouvez pas en faire "
                    "le parent de '%(child)s'.",
                    parent=cat.parent_id.name,
                    child=cat.name or '',
                ))
            # 2) Si cette categorie a deja des enfants, on ne peut pas
            #    lui donner un parent (sinon ses enfants deviendraient
            #    petits-enfants -> 3 niveaux).
            if cat.parent_id and cat.child_ids:
                raise ValidationError(_(
                    "La categorie '%(name)s' a deja des sous-categories, "
                    "elle ne peut pas devenir elle-meme une sous-categorie.",
                    name=cat.name or '',
                ))
            # 3) Une categorie ne peut pas etre son propre parent
            if cat.parent_id and cat.parent_id == cat:
                raise ValidationError(_(
                    "Une categorie ne peut pas etre son propre parent."
                ))

    @api.depends('parent_id')
    def _compute_is_subcategory(self):
        for cat in self:
            cat.is_subcategory = bool(cat.parent_id)

    @api.depends('child_ids')
    def _compute_child_count(self):
        for cat in self:
            cat.child_count = len(cat.child_ids)

    # ------------------------------------------------------------------
    # DISPLAY NAME : "Parent / Enfant" pour les sous-categories
    # ------------------------------------------------------------------
    @api.depends('name', 'parent_id', 'parent_id.name')
    def _compute_display_name(self):
        for cat in self:
            if cat.parent_id:
                cat.display_name = "%s / %s" % (cat.parent_id.name, cat.name or '')
            else:
                cat.display_name = cat.name or ''

    # ------------------------------------------------------------------
    # NB QUESTIONS : inclure les sous-categories dans le compte
    # ------------------------------------------------------------------
    question_count = fields.Integer(
        'Nb questions',
        compute='_compute_question_count',
    )

    def _compute_question_count(self):
        Question = self.env['survey.question']
        for category in self:
            # Pour une categorie parente : on compte les questions tagguees
            # avec elle directement OU avec une de ses sous-categories.
            # Pour une sous-categorie : on compte juste les siennes.
            if category.parent_id:
                # sous-categorie : compte exact
                category.question_count = Question.search_count([
                    '|',
                    ('exam_category_id', '=', category.id),
                    ('exam_subcategory_id', '=', category.id),
                    ('is_bank_question', '=', True),
                ])
            else:
                # categorie parente : inclut sous-cats
                child_ids = category.child_ids.ids
                all_ids = [category.id] + child_ids
                category.question_count = Question.search_count([
                    '|',
                    ('exam_category_id', 'in', all_ids),
                    ('exam_subcategory_id', 'in', all_ids),
                    ('is_bank_question', '=', True),
                ])

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def action_open_bank_questions(self):
        """Ouvre la banque de questions filtree sur cette categorie
        (et ses sous-categories si c'est une categorie parente)."""
        self.ensure_one()
        if self.parent_id:
            # Sous-categorie : filtre exact
            domain = [
                '|',
                ('exam_category_id', '=', self.id),
                ('exam_subcategory_id', '=', self.id),
                ('is_bank_question', '=', True),
                ('is_page', '=', False),
                ('survey_id', '=', False),
            ]
            ctx_subcat = self.id
            ctx_cat = self.parent_id.id
        else:
            # Categorie parente : inclut sous-cats
            child_ids = self.child_ids.ids
            all_ids = [self.id] + child_ids
            domain = [
                '|',
                ('exam_category_id', 'in', all_ids),
                ('exam_subcategory_id', 'in', all_ids),
                ('is_bank_question', '=', True),
                ('is_page', '=', False),
                ('survey_id', '=', False),
            ]
            ctx_subcat = False
            ctx_cat = self.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Questions - %s', self.display_name),
            'res_model': 'survey.question',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {
                'default_is_bank_question': True,
                'default_exam_category_id': ctx_cat,
                'default_exam_subcategory_id': ctx_subcat,
                'default_survey_id': False,
            },
        }
