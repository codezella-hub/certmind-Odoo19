# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ExamGenerationRule(models.Model):
    """
    Regle de generation de questions pour un examen.
    Chaque regle definit :
    - Un filtre (categorie + sous-categorie + difficulte)
    - Un nombre de questions a piocher aleatoirement dans la banque

    Logique de filtrage des questions eligibles :
    +-----------------------+----------------------+--------------------------+
    | Categorie de la regle | Sous-cat de la regle | Questions selectionnees  |
    +-----------------------+----------------------+--------------------------+
    | (vide)                | (vide)               | TOUTES les questions     |
    | Python                | (vide)               | Python (cat directe)     |
    |                       |                      | + Python > * (toutes ses |
    |                       |                      |   sous-categories)       |
    | Python                | POO                  | Python > POO uniquement  |
    +-----------------------+----------------------+--------------------------+
    """
    _name = 'exam.generation.rule'
    _description = 'Regle de generation de questions'
    _order = 'sequence, id'

    survey_id = fields.Many2one(
        'survey.survey',
        string='Examen',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char('Libelle', required=True)
    sequence = fields.Integer('Sequence', default=10)

    # Filtres de selection
    exam_category_id = fields.Many2one(
        'exam.category',
        string='Categorie',
        domain="[('parent_id', '=', False)]",
        help="Categorie principale. Si une sous-categorie est aussi specifiee, "
             "le filtre sera plus precis. Sinon, toutes les questions de la "
             "categorie ET de ses sous-categories seront eligibles. "
             "Laisser vide pour ne pas filtrer par categorie.",
    )
    exam_subcategory_id = fields.Many2one(
        'exam.category',
        string='Sous-categorie',
        domain="[('parent_id', '=', exam_category_id)]",
        help="Sous-categorie pour un filtre plus precis (ex: Python > POO). "
             "Disponible uniquement si une categorie est selectionnee. "
             "Laisser vide pour inclure toutes les sous-categories.",
    )
    exam_difficulty = fields.Selection([
        ('easy',   'Facile'),
        ('medium', 'Moyen'),
        ('hard',   'Difficile'),
    ], string='Difficulte', help="Laisser vide pour ne pas filtrer par difficulte.")

    # Filtre optionnel par type cognitif (niveau 2).
    cognitive_type = fields.Selection([
        ('memory',        'Mémoire (restitution)'),
        ('comprehension', 'Compréhension'),
        ('application',   'Application'),
        ('analysis',      'Analyse'),
        ('experience',    'Expérience pratique'),
    ], string='Type cognitif',
        help="Laisser vide pour ne pas filtrer par type. Permet de piocher "
             "par exemple '3 questions de mémoire'.")

    # Couverture garantie (niveau 3).
    ensure_coverage = fields.Boolean(
        'Couvrir toutes les sous-catégories', default=False,
        help="Si coché : garantit qu'au moins une question de chaque "
             "sous-catégorie est tirée, avant de compléter au hasard. "
             "Évite qu'un chapitre entier soit oublié par le hasard.")

    count = fields.Integer(
        'Nb questions a piocher',
        required=True,
        default=5,
        help="Nombre de questions a selectionner aleatoirement depuis la banque.",
    )

    # --- Placement des questions générées ---
    use_section = fields.Boolean(
        'Regrouper sous une section',
        default=False,
        help="Si activé, les questions générées par cette règle seront "
             "placées sous une section dédiée dans l'examen.",
    )
    section_title = fields.Char(
        'Titre de la section',
        help="Titre de la section qui sera créée automatiquement dans l'examen. "
             "Laissez vide pour utiliser le libellé de la règle.",
    )

    # Info calculee : combien de questions disponibles avec ces filtres
    available_count = fields.Integer(
        'Questions disponibles',
        compute='_compute_available_count',
        help="Nombre de questions dans la banque correspondant aux filtres.",
    )

    @api.depends('exam_category_id', 'exam_subcategory_id', 'exam_difficulty')
    def _compute_available_count(self):
        for rule in self:
            rule.available_count = len(rule._get_question_pool())

    @api.constrains('count')
    def _check_count(self):
        for rule in self:
            if rule.count <= 0:
                raise ValidationError(_(
                    "Le nombre de questions a piocher doit etre superieur a 0."
                ))

    @api.constrains('exam_category_id', 'exam_subcategory_id')
    def _check_subcategory_belongs_to_category(self):
        """Verifier la coherence entre cat parente et sous-cat."""
        for rule in self:
            if rule.exam_subcategory_id:
                if not rule.exam_category_id:
                    raise ValidationError(_(
                        "Vous devez choisir une categorie principale avant de "
                        "selectionner une sous-categorie."
                    ))
                if rule.exam_subcategory_id.parent_id != rule.exam_category_id:
                    raise ValidationError(_(
                        "La sous-categorie '%(sub)s' n'appartient pas a la "
                        "categorie '%(cat)s'.",
                        sub=rule.exam_subcategory_id.name,
                        cat=rule.exam_category_id.name,
                    ))

    @api.onchange('exam_category_id')
    def _onchange_exam_category_id(self):
        """Vider la sous-cat si elle n'appartient plus a la nouvelle cat."""
        if self.exam_subcategory_id and self.exam_subcategory_id.parent_id != self.exam_category_id:
            self.exam_subcategory_id = False

    def _get_question_pool(self):
        """
        Retourne le recordset des survey.question eligibles
        selon les filtres de cette regle.

        Logique :
          1. Filtre de base : banque, sans survey, pas de section
          2. Si sous-categorie -> filtre exact sur (cat OU sub).
          3. Sinon si categorie parente seule -> inclut la cat ET ses sous-cats.
          4. Difficulte appliquee en plus si specifiee.
        """
        self.ensure_one()
        Question = self.env['survey.question']
        domain = [
            ('is_bank_question', '=', True),
            ('survey_id', '=', False),          # questions libres dans la banque
            ('is_page', '=', False),            # pas les sections
        ]

        if self.exam_subcategory_id:
            # Cas 1 : sous-categorie precisee -> filtre exact.
            # Une question est eligible si :
            #   - elle est tagguee directement avec cette sous-cat
            #     (exam_subcategory_id = sub_id), OU
            #   - elle est tagguee dans la categorie parente avec
            #     justement la bonne cat ET cette sous-cat n'est pas
            #     specifiee sur la question (cas exam_category_id = sub_id
            #     n'arrive pas en pratique car la cat principale est
            #     forcement de niveau 1, mais on couvre par securite).
            domain += [('exam_subcategory_id', '=', self.exam_subcategory_id.id)]

        elif self.exam_category_id:
            # Cas 2 : juste la categorie parente -> inclut tout
            # (la cat directement OU une de ses sous-cats).
            child_ids = self.exam_category_id.child_ids.ids
            all_cat_ids = [self.exam_category_id.id] + child_ids
            domain += [
                '|',
                ('exam_category_id', 'in', all_cat_ids),
                ('exam_subcategory_id', 'in', all_cat_ids),
            ]
        # Cas 3 : ni l'un ni l'autre -> aucune restriction de categorie

        if self.exam_difficulty:
            domain += [('exam_difficulty', '=', self.exam_difficulty)]

        if self.cognitive_type:
            domain += [('cognitive_type', '=', self.cognitive_type)]

        return Question.search(domain)

    def pick_question_ids(self):
        """
        Tire les IDs de questions pour cette regle, avec couverture optionnelle.

        Niveau 1 : tirage aleatoire simple (si ensure_coverage = False).
        Niveau 3 : si ensure_coverage = True, garantit au moins une question
                   de chaque sous-categorie avant de completer au hasard.

        Retourne (liste_ids, avertissement_ou_None).
        """
        import random as _random
        self.ensure_one()
        pool = self._get_question_pool()
        available = len(pool)
        pick_count = min(self.count, available)
        warning = None
        if pick_count < self.count:
            warning = (f"Regle '{self.name}' : seulement {pick_count} "
                       f"question(s) disponible(s) sur {self.count} demandee(s).")

        if pick_count == 0:
            return [], warning

        # Niveau 1 : tirage simple.
        if not self.ensure_coverage:
            return _random.sample(pool.ids, pick_count), warning

        # Niveau 3 : couverture garantie par sous-categorie.
        # 1. Regrouper les questions par sous-categorie.
        by_subcat = {}
        for q in pool:
            key = q.exam_subcategory_id.id or q.exam_category_id.id or 0
            by_subcat.setdefault(key, []).append(q.id)

        picked = []
        # 2. Tirer 1 question de chaque sous-categorie (dans la limite du count).
        subcats = list(by_subcat.keys())
        _random.shuffle(subcats)
        for key in subcats:
            if len(picked) >= pick_count:
                break
            picked.append(_random.choice(by_subcat[key]))

        # 3. Completer au hasard avec le reste si besoin.
        remaining = [qid for qid in pool.ids if qid not in picked]
        _random.shuffle(remaining)
        while len(picked) < pick_count and remaining:
            picked.append(remaining.pop())

        return picked, warning
