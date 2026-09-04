# -*- coding: utf-8 -*-
import random

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class SurveySurveyPatch(models.Model):
    """
    Extension de survey.survey pour la gestion des examens.

    Logique principale :
    1. is_exam = True → active le mode examen sur ce survey
    2. generation_rule_ids → règles de sélection (catégorie + difficulté + count)
    3. action_generate_exam_questions() → copie les questions tirées au sort
       depuis la banque vers ce survey (snapshot figé)
    4. _prepare_user_input_predefined_questions() est surchargé :
       - si is_exam → retourne les questions déjà copiées (déjà dans question_ids)
       - sinon → comportement natif survey inchangé

    Le reste (scoring, predefined_question_ids, certification, statistiques)
    fonctionne 100% nativement via survey.user_input.
    """
    _inherit = 'survey.survey'

    # --- Champ flag examen ---
    is_exam = fields.Boolean(
        'Est un examen',
        default=False,
        help="Activer pour utiliser la banque de questions avec génération aléatoire.",
    )

    # --- Proctoring ---
    is_proctored = fields.Boolean(
        'Surveillance en direct (Proctoring)',
        default=False,
        help=(
            "Active la surveillance vidéo en temps réel. Les candidats doivent "
            "activer leur caméra et être autorisés par un procteur avant de "
            "pouvoir démarrer l'examen."
        ),
    )
    record_video = fields.Boolean(
        'Enregistrer la video du candidat',
        default=False,
        help=(
            "Si active, la camera du candidat sera enregistree pendant "
            "toute la duree de l'examen. La video est sauvegardee sur la "
            "session de proctoring et consultable par les procteurs."
        ),
    )
    # COMPATIBILITY FALLBACK :
    # Certaines vues natives / modules tiers (Odoo 19) referencent un champ
    # "proctoring_mode" qui peut ne pas etre defini dans toutes les
    # installations. On le declare ici en Selection (type attendu par Odoo
    # pour ce champ, car _process_ondelete lit field.ondelete qui n'existe
    # que sur Selection). Il n'est utilise nulle part dans notre logique :
    # notre flag metier est "is_proctored".
    proctoring_mode = fields.Selection(
        selection=[
            ('no_proctoring', 'No Proctoring'),
            ('partner_identification', 'Require Identity Verification'),
        ],
        string='Proctoring Mode (compat)',
        default='no_proctoring',
        ondelete={
            'no_proctoring': 'set default',
            'partner_identification': 'set default',
        },
        help="Champ de compatibilite avec vues natives/modules tiers. "
             "Non utilise par digii_exam_manager (utiliser is_proctored).",
    )
    proctoring_session_count = fields.Integer(
        'Sessions proctoring',
        compute='_compute_proctoring_session_count',
    )

    def _compute_proctoring_session_count(self):
        for survey in self:
            survey.proctoring_session_count = self.env['exam.proctoring.session'].search_count([
                ('survey_id', '=', survey.id),
            ])

    def action_open_proctoring_dashboard(self):
        """Ouvre le dashboard procteur dans un nouvel onglet."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/exam/proctoring/dashboard/{self.id}',
            'target': 'new',
        }

    def action_view_proctoring_sessions(self):
        """Ouvre la liste des sessions de proctoring."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sessions Proctoring — %s' % self.title,
            'res_model': 'exam.proctoring.session',
            'view_mode': 'list,form',
            'domain': [('survey_id', '=', self.id)],
            'context': {'default_survey_id': self.id},
        }

    # --- Règles de génération ---
    generation_rule_ids = fields.One2many(
        'exam.generation.rule',
        'survey_id',
        string='Règles de génération',
    )

    # --- Template de certificat (override par examen) ---
    is_certification = fields.Boolean(
        'Activer la certification',
        default=False,
        help=(
            "Active la génération automatique de certificats quand un candidat "
            "atteint le score de réussite. Fonctionne avec ou sans le mode examen."
        ),
    )
    certificate_template_id = fields.Many2one(
        'exam.certificate.template',
        string='Template de certificat',
        help="Template spécifique pour cet examen. Si vide, le template par défaut sera utilisé.",
    )

    # --- Compteur de certificats ---
    certificate_count = fields.Integer(
        'Nb certificats',
        compute='_compute_certificate_count',
    )

    # --- État de la génération ---
    exam_questions_generated = fields.Boolean(
        'Questions générées',
        default=False,
        copy=False,
        help="True si les questions ont été copiées depuis la banque dans cet examen.",
    )
    exam_group_by_type = fields.Boolean(
        'Section par type de question',
        default=False,
        help="Si activé, lors de la génération aléatoire, les questions sont "
             "regroupées sous une section dédiée pour CHAQUE type de question "
             "(choix unique, choix multiple, texte, etc.).",
    )

    # Catégories (parentes) présentes dans l'examen, déduites des questions.
    # Sert au filtrage côté portail /my/exams.
    exam_category_ids = fields.Many2many(
        comodel_name='exam.category',
        relation='survey_survey_exam_category_rel',
        column1='survey_id',
        column2='category_id',
        string='Catégories (examen)',
        compute='_compute_exam_category_ids',
        store=True,
        help="Catégories parentes des questions de cet examen "
             "(les sous-catégories sont ramenées à leur parente).",
    )

    # IMPORTANT : pas de @api.depends('question_ids.xxx') ici.
    # question_ids est un One2many natif de survey.survey, non stocké côté
    # survey.survey. Avec store=True sur exam_category_ids, un @api.depends
    # sur ce chemin force Odoo à faire un search() SQL sur question_ids pour
    # invalider/recalculer ce champ a chaque create/write d'une question, et
    # ça plante avec :
    #   "Cannot convert survey.survey.question_ids to SQL because it is not stored"
    # (typiquement déclenché par question.copy() dans
    # action_generate_exam_questions). Le recalcul est donc déclenché
    # manuellement depuis survey_question_patch.py (côté question, qui a
    # bien survey_id stocké) via _trigger_exam_category_ids_recompute().
    def _compute_exam_category_ids(self):
        for survey in self:
            cats = self.env['exam.category']
            for q in survey.question_ids:
                cat = q.exam_category_id
                # Si seule une sous-catégorie est renseignée, prendre sa parente
                if not cat and q.exam_subcategory_id:
                    cat = q.exam_subcategory_id.parent_id
                # Toujours remonter à la catégorie parente (jamais une sous-cat)
                if cat and cat.parent_id:
                    cat = cat.parent_id
                if cat:
                    cats |= cat
            survey.exam_category_ids = [(6, 0, cats.ids)]

    def _trigger_exam_category_ids_recompute(self):
        """Recalcule exam_category_ids à la demande (appelé depuis
        survey_question_patch.py quand une question change de catégorie,
        ou est créée/copiée/supprimée dans un examen).

        Ce recalcul est volontairement manuel (voir note ci-dessus sur
        _compute_exam_category_ids) plutôt que piloté par @api.depends.
        """
        self._compute_exam_category_ids()

    exam_generated_count = fields.Integer(
        'Nb questions générées',
        compute='_compute_exam_generated_count',
    )

    @api.depends('question_and_page_ids', 'is_exam')
    def _compute_exam_generated_count(self):
        for survey in self:
            if survey.is_exam:
                # Compter uniquement les questions copiées (bank_question_id rempli)
                survey.exam_generated_count = self.env['survey.question'].search_count([
                    ('survey_id', '=', survey.id),
                    ('is_bank_question', '=', False),
                    ('bank_question_id', '!=', False),
                    ('is_page', '=', False),
                ])
            else:
                survey.exam_generated_count = 0

    def _compute_certificate_count(self):
        for survey in self:
            survey.certificate_count = self.env['exam.certificate'].search_count([
                ('survey_id', '=', survey.id),
            ])

    # -------------------------------------------------------------------------
    # ONCHANGE is_exam : forcer les champs obligatoires
    # -------------------------------------------------------------------------

    @api.onchange('is_exam')
    def _onchange_is_exam(self):
        """
        Quand is_exam est activé, appliquer automatiquement les réglages
        verrouillés annoncés dans le bandeau :
          - users_can_go_back  = True                      (Allow Roaming)
          - scoring_type       = 'scoring_without_answers' (Scoring without answers)
          - is_certification   = True                      (Special Certificate)
          - is_time_limited    = True                      (Survey Time Limit)
        """
        if self.is_exam:
            self.users_can_go_back = True
            self.scoring_type      = 'scoring_without_answers'
            self.is_certification  = True
            self.is_time_limited   = True
            if not self.time_limit or self.time_limit <= 0:
                self.time_limit = 30.0   # durée par défaut (minutes), modifiable

    @api.onchange('record_video')
    def _onchange_record_video(self):
        """Si on desactive l'enregistrement, on desactive aussi le proctoring
        (le proctoring en direct a besoin de la video)."""
        if not self.record_video:
            self.is_proctored = False

    @api.onchange('is_proctored')
    def _onchange_is_proctored(self):
        """Si on active le proctoring, l'enregistrement video est requis."""
        if self.is_proctored:
            self.record_video = True

    # Valeurs verrouillées pour un examen
    def _exam_locked_vals(self):
        """Retourne les valeurs à forcer pour un examen (champs verrouillés)."""
        self.ensure_one()
        fix = {}
        if not self.users_can_go_back:
            fix['users_can_go_back'] = True
        if self.scoring_type != 'scoring_without_answers':
            fix['scoring_type'] = 'scoring_without_answers'
        if not self.is_certification:
            fix['is_certification'] = True
        if not self.is_time_limited:
            fix['is_time_limited'] = True
        if (self.is_time_limited or fix.get('is_time_limited')) and (not self.time_limit or self.time_limit <= 0):
            fix['time_limit'] = 30.0
        return fix

    @api.model_create_multi
    def create(self, vals_list):
        """S'assurer que les champs sont forcés même à la création."""
        for vals in vals_list:
            if vals.get('is_exam'):
                vals['users_can_go_back'] = True
                vals['scoring_type']      = 'scoring_without_answers'
                vals['is_certification']  = True
                vals['is_time_limited']   = True
                if not vals.get('time_limit'):
                    vals['time_limit'] = 30.0
        surveys = super().create(vals_list)
        # exam_category_ids est compute+store SANS @api.depends (voir note
        # plus haut sur _compute_exam_category_ids) : il faut donc
        # l'initialiser explicitement ici, sinon il reste vide tant qu'aucune
        # question liée n'est créée/modifiée par la suite.
        surveys._trigger_exam_category_ids_recompute()
        return surveys

    def write(self, vals):
        """Verrouillage permanent : à chaque écriture, les réglages examen
        sont re-forcés (impossible de les désactiver tant que is_exam=True)."""
        if vals.get('is_exam'):
            vals['users_can_go_back'] = True
            vals['scoring_type']      = 'scoring_without_answers'
            vals['is_certification']  = True
            vals['is_time_limited']   = True
            # Garantir time_limit > 0 (contrainte native) si activé maintenant
            if 'time_limit' not in vals and any((s.time_limit or 0) <= 0 for s in self):
                vals['time_limit'] = 30.0
        res = super().write(vals)
        # Re-forcer pour tout examen (verrou permanent), sans récursion infinie
        if not self.env.context.get('_exam_locking'):
            for rec in self.filtered('is_exam'):
                fix = rec._exam_locked_vals()
                if fix:
                    rec.with_context(_exam_locking=True).write(fix)
        return res

    # -------------------------------------------------------------------------
    # ACTION PRINCIPALE : Générer les questions
    # -------------------------------------------------------------------------

    def action_generate_exam_questions(self):
        """
        Copie aléatoirement des questions depuis la banque vers cet examen.

        Pour chaque règle :
        1. Cherche les questions éligibles (banque + filtres catégorie/difficulté)
        2. Tire N questions au sort (random.sample)
        3. Copie chaque question dans ce survey via question.copy()
           - survey_id = self.id  → la copie appartient à l'examen
           - is_bank_question = False → ce n'est pas une question de banque
           - bank_question_id = question.id → référence vers la source

        Les anciennes questions générées sont supprimées avant de régénérer.
        """
        self.ensure_one()

        if not self.is_exam:
            raise UserError("Ce survey n'est pas configuré comme un examen.")

        if not self.generation_rule_ids:
            raise UserError("Veuillez définir au moins une règle de génération.")

        # Supprimer TOUT ce qui a été généré précédemment :
        #   - les questions copiées (bank_question_id)
        #   - les sections générées (marqueur exam_generated_item)
        Question = self.env['survey.question']
        old_generated = Question.search([
            ('survey_id', '=', self.id),
            '|',
                ('exam_generated_item', '=', True),
                ('bank_question_id', '!=', False),
        ])
        if old_generated:
            old_generated.unlink()

        # Rétro-compatibilité : nettoyer les anciennes sections générées
        # AVANT l'ajout du marqueur (identifiées par leur titre de type).
        type_labels = list(self._QUESTION_TYPE_LABELS.values())
        legacy_sections = Question.search([
            ('survey_id', '=', self.id),
            ('is_page', '=', True),
        ])
        for sec in legacy_sections:
            base_title = (sec.title or '').split(' (')[0].strip()
            if base_title in type_labels:
                sec.unlink()

        total_generated = 0
        warnings = []

        # ===== MODE "SECTION PAR TYPE DE QUESTION" =========================
        if self.exam_group_by_type:
            total_generated, warnings = self._generate_grouped_by_type()
            self.exam_questions_generated = True
            message = f"✓ {total_generated} question(s) générée(s) (groupées par type)."
            if warnings:
                message += "\n\nAvertissements :\n" + "\n".join(f"• {w}" for w in warnings)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Génération terminée',
                    'message': message,
                    'type': 'success' if not warnings else 'warning',
                    'sticky': bool(warnings),
                },
            }
        # ===================================================================

        for rule in self.generation_rule_ids.sorted('sequence'):
            pool = rule._get_question_pool()

            if not pool:
                warnings.append(
                    f"Règle '{rule.name}' : aucune question disponible avec ces filtres."
                )
                continue

            # Nombre réel à piocher (min entre demandé et disponible)
            pick_count = min(rule.count, len(pool))

            # Tirage intelligent (niveau 1 ou 3 selon ensure_coverage)
            picked_questions, rule_warning = rule.pick_question_ids()
            if rule_warning:
                warnings.append(rule_warning)

            # ── Créer une section si demandé ───────────────────────────────
            rule_index = list(self.generation_rule_ids.sorted('sequence').ids).index(rule.id)
            seq = (rule_index + 1) * 100  # espace entre règles

            if rule.use_section:
                section_label = rule.section_title or rule.name
                self.env['survey.question'].create({
                    'survey_id':  self.id,
                    'is_page':    True,
                    'title':      section_label,
                    'sequence':   seq,
                    'exam_generated_item': True,
                })
                seq += 1

            # ── Copier chaque question dans cet examen ─────────────────────
            for q_id in picked_questions:
                question = self.env['survey.question'].browse(q_id)
                question.copy(default={
                    'survey_id':            self.id,
                    'is_bank_question':     False,
                    'bank_question_id':     question.id,
                    'sequence':             seq,
                    'exam_generated_item':  True,
                    'triggering_answer_ids': [(5, 0, 0)],
                })
                seq += 1
                total_generated += 1

        self.exam_questions_generated = True

        # Message de confirmation avec avertissements éventuels
        message = f"✓ {total_generated} question(s) générée(s) avec succès."
        if warnings:
            message += "\n\nAvertissements :\n" + "\n".join(f"• {w}" for w in warnings)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Génération terminée',
                'message': message,
                'type': 'success' if not warnings else 'warning',
                'sticky': bool(warnings),
            },
        }

    # Libellés FR par type de question (pour les sections)
    _QUESTION_TYPE_LABELS = {
        'simple_choice':   'Questions à choix unique',
        'multiple_choice': 'Questions à choix multiple',
        'text_box':        'Questions à développement',
        'char_box':        'Questions à réponse courte',
        'numerical_box':   'Questions numériques',
        'date':            'Questions (date)',
        'datetime':        'Questions (date et heure)',
        'scale':           'Questions à échelle',
        'matrix':          'Questions matricielles',
    }
    # Ordre d'affichage des sections par type
    _QUESTION_TYPE_ORDER = [
        'simple_choice', 'multiple_choice', 'char_box', 'text_box',
        'numerical_box', 'scale', 'matrix', 'date', 'datetime',
    ]

    def _generate_grouped_by_type(self):
        """Génère les questions puis crée UNE SECTION PAR TYPE de question.

        1. Pioche les questions de toutes les règles (aléatoire).
        2. Les regroupe par question_type.
        3. Pour chaque type : crée une section puis copie ses questions dessous.

        Retourne (total_generated, warnings).
        """
        self.ensure_one()
        Question = self.env['survey.question']

        # 1) Piocher selon toutes les règles
        picked_ids = []
        warnings = []
        for rule in self.generation_rule_ids.sorted('sequence'):
            pool = rule._get_question_pool()
            if not pool:
                warnings.append(
                    f"Règle '{rule.name}' : aucune question disponible avec ces filtres."
                )
                continue
            pick_count = min(rule.count, len(pool))
            rule_picked, rule_warning = rule.pick_question_ids()
            if rule_warning:
                warnings.append(rule_warning)
            picked_ids += rule_picked

        # Dédoublonner en gardant l'ordre
        seen = set()
        unique_ids = [qid for qid in picked_ids if not (qid in seen or seen.add(qid))]
        if not unique_ids:
            return 0, warnings

        # 2) Regrouper par type
        groups = {}
        for q in Question.browse(unique_ids):
            groups.setdefault(q.question_type, []).append(q)

        # 3) Créer une section par type + copier les questions
        ordered_types = [t for t in self._QUESTION_TYPE_ORDER if t in groups]
        # types non prévus dans l'ordre (sécurité)
        ordered_types += [t for t in groups if t not in ordered_types]

        total_generated = 0
        seq = 100
        for qtype in ordered_types:
            qs = groups[qtype]
            label = self._QUESTION_TYPE_LABELS.get(qtype, 'Autres questions')
            Question.create({
                'survey_id': self.id,
                'is_page':   True,
                'title':     '%s (%d)' % (label, len(qs)),
                'sequence':  seq,
                'exam_generated_item': True,
            })
            seq += 1
            for q in qs:
                q.copy(default={
                    'survey_id':             self.id,
                    'is_bank_question':      False,
                    'bank_question_id':      q.id,
                    'sequence':              seq,
                    'exam_generated_item':   True,
                    'triggering_answer_ids': [(5, 0, 0)],
                })
                seq += 1
                total_generated += 1

        return total_generated, warnings

    def action_reset_exam_questions(self):
        """
        Supprime toutes les questions ET sections copiées/générées.
        Remet l'examen à zéro pour permettre une nouvelle génération.
        """
        self.ensure_one()
        Question = self.env['survey.question']
        generated = Question.search([
            ('survey_id', '=', self.id),
            '|',
                ('exam_generated_item', '=', True),
                ('bank_question_id', '!=', False),
        ])
        generated.unlink()

        # Rétro-compat : anciennes sections de type sans marqueur
        type_labels = list(self._QUESTION_TYPE_LABELS.values())
        for sec in Question.search([('survey_id', '=', self.id), ('is_page', '=', True)]):
            base_title = (sec.title or '').split(' (')[0].strip()
            if base_title in type_labels:
                sec.unlink()

        self.exam_questions_generated = False

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Réinitialisation',
                'message': 'Les questions générées ont été supprimées.',
                'type': 'info',
                'sticky': False,
            },
        }

    # -------------------------------------------------------------------------
    # OVERRIDE : _prepare_user_input_predefined_questions
    # -------------------------------------------------------------------------

    def _prepare_user_input_predefined_questions(self):
        """
        Surcharge de la méthode native survey.survey.

        Contexte natif (survey/models/survey_survey.py) :
            Cette méthode est appelée dans survey.user_input.create()
            pour remplir predefined_question_ids.
            Elle gère la randomisation par section (questions_selection='random').

        Notre surcharge :
            - Si is_exam=True → on retourne les questions déjà copiées dans le survey
              (générées par action_generate_exam_questions).
              L'ordre est celui de la séquence.
            - Sinon → comportement natif inchangé (super()).
        """
        self.ensure_one()

        if not self.is_exam:
            # Comportement natif survey : randomisation par section si configurée
            return super()._prepare_user_input_predefined_questions()

        # Mode examen : retourner les questions copiées depuis la banque
        # Elles sont déjà dans question_ids (survey_id = self.id, is_page=False)
        return self.question_ids

    # -------------------------------------------------------------------------
    # ACTION : Voir les certificats
    # -------------------------------------------------------------------------

    def action_view_certificates(self):
        """Ouvre la liste des certificats liés à cet examen."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Certificats — %s' % self.title,
            'res_model': 'exam.certificate',
            'view_mode': 'list,form',
            'domain': [('survey_id', '=', self.id)],
            'context': {'default_survey_id': self.id},
        }
