# -*- coding: utf-8 -*-
"""
Session de generation IA.

Une session represente UNE demande de l'admin (generer des questions,
proposer des regles, generer des distracteurs...). Elle garde la trace de
la demande, du prompt systeme utilise, de la reponse brute et des objets
crees (questions proposees ou propositions de regles).

Toute la logique de construction des prompts et de transformation de la
reponse JSON en enregistrements Odoo vit ici. Les controllers ne font
qu'appeler les methodes de ce modele.
"""
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .ai_service import AiAgentError

_logger = logging.getLogger(__name__)

DIFFICULTY_VALUES = ('easy', 'medium', 'hard')
QUESTION_TYPE_VALUES = ('simple_choice', 'multiple_choice')


class DigiiAiGenerationSession(models.Model):
    _name = 'digii.ai.generation.session'
    _description = 'Session de generation IA'
    _order = 'create_date desc'

    name = fields.Char(
        'Reference', readonly=True, copy=False, index=True,
        default=lambda self: _('Nouvelle session'),
    )
    source_type = fields.Selection([
        ('course', 'Cours'),
        ('text', 'Texte libre'),
        ('topic', 'Sujet / mot-cle'),
        ('single_question_distractors', 'Distracteurs (1 question)'),
        ('rule_copilot', 'Co-pilote regles examen'),
    ], string='Type de source', required=True, default='topic')

    source_course_id = fields.Many2one('slide.channel', string='Cours source')
    source_text = fields.Text('Texte source')
    prompt_user = fields.Text('Demande de l\'admin')

    prompt_system_used = fields.Text('Prompt systeme (debug)', readonly=True)
    raw_response = fields.Text('Reponse brute (JSON)', readonly=True)

    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('generating', 'En cours'),
        ('done', 'Termine'),
        ('error', 'Erreur'),
    ], string='Statut', default='draft', required=True)
    error_message = fields.Text('Message d\'erreur')

    created_question_ids = fields.One2many(
        'survey.question', 'ai_generation_session_id',
        string='Questions generees',
    )
    created_question_count = fields.Integer(
        'Nb questions', compute='_compute_counts',
    )
    created_rule_proposal_ids = fields.One2many(
        'digii.ai.rule.proposal', 'session_id',
        string='Regles proposees',
    )
    created_rule_count = fields.Integer(
        'Nb regles', compute='_compute_counts',
    )

    user_id = fields.Many2one(
        'res.users', string='Utilisateur',
        default=lambda self: self.env.user, readonly=True,
    )

    @api.depends('created_question_ids', 'created_rule_proposal_ids')
    def _compute_counts(self):
        for rec in self:
            rec.created_question_count = len(rec.created_question_ids)
            rec.created_rule_count = len(rec.created_rule_proposal_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('Nouvelle session'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'digii.ai.generation.session') or _('Session IA')
        return super().create(vals_list)

    # ==================================================================
    # API PUBLIQUE (appelee par le controller)
    # ==================================================================

    @api.model
    def generate_questions(self, source_type, count=5, difficulty_distribution=None,
                           question_type='simple_choice', source_course_id=None,
                           source_text=None, topic=None, user_prompt=None,
                           cognitive_type=None, category_id=None):
        """
        Genere un lot de questions proposees (etat 'proposed').
        Retourne un dict serialisable pour le frontend.
        """
        count = max(1, min(int(count or 5), 30))
        if question_type not in QUESTION_TYPE_VALUES:
            question_type = 'simple_choice'

        course = None
        if source_course_id:
            course = self.env['slide.channel'].browse(int(source_course_id)).exists()

        target_category = None
        if category_id:
            target_category = self.env['exam.category'].browse(int(category_id)).exists()

        session = self.create({
            'source_type': source_type if source_type in dict(
                self._fields['source_type'].selection) else 'topic',
            'source_course_id': course.id if course else False,
            'source_text': source_text or '',
            'prompt_user': user_prompt or topic or '',
            'state': 'generating',
        })

        try:
            system_prompt = session._build_questions_system_prompt(
                count, difficulty_distribution, question_type,
                cognitive_type=cognitive_type, target_category=target_category)
            user_content = session._build_questions_user_prompt(
                source_type, course, source_text, topic, user_prompt)

            session.prompt_system_used = system_prompt
            data, raw = self.env['digii.ai.service'].chat_json(
                system_prompt, user_content)
            session.raw_response = raw

            questions = session._create_questions_from_payload(
                data, cognitive_type=cognitive_type)
            session.state = 'done'
            return {
                'session_id': session.id,
                'questions': [q._ai_card_data() for q in questions],
            }
        except AiAgentError as exc:
            session.write({'state': 'error', 'error_message': str(exc)})
            return {'error': str(exc), 'session_id': session.id}
        except Exception as exc:  # noqa: BLE001
            _logger.exception('[AI] generate_questions a echoue')
            session.write({'state': 'error', 'error_message': str(exc)})
            return {'error': _("Erreur interne : %s", str(exc)[:300])}

    @api.model
    def generate_rules(self, survey_id, description):
        """
        Co-pilote : propose un jeu de regles exam.generation.rule a partir
        d'une description en langage naturel. Retourne les propositions
        avec leur faisabilite.
        """
        survey = self.env['survey.survey'].browse(int(survey_id)).exists()
        if not survey:
            return {'error': _("Examen introuvable.")}

        session = self.create({
            'source_type': 'rule_copilot',
            'prompt_user': description or '',
            'state': 'generating',
        })

        try:
            system_prompt = session._build_rules_system_prompt()
            user_content = session._build_rules_user_prompt(survey, description)
            session.prompt_system_used = system_prompt

            data, raw = self.env['digii.ai.service'].chat_json(
                system_prompt, user_content)
            session.raw_response = raw

            proposals = session._create_rule_proposals_from_payload(survey, data)
            session.state = 'done'
            return {
                'session_id': session.id,
                'notes': data.get('notes', ''),
                'rules': [p._ai_card_data() for p in proposals],
            }
        except AiAgentError as exc:
            session.write({'state': 'error', 'error_message': str(exc)})
            return {'error': str(exc), 'session_id': session.id}
        except Exception as exc:  # noqa: BLE001
            _logger.exception('[AI] generate_rules a echoue')
            session.write({'state': 'error', 'error_message': str(exc)})
            return {'error': _("Erreur interne : %s", str(exc)[:300])}

    @api.model
    def regenerate_question(self, question_id, instruction):
        """
        Regenere une question proposee selon une consigne ('plus difficile',
        'reformule plus clairement'...). Met a jour la question en place.
        """
        question = self.env['survey.question'].browse(int(question_id)).exists()
        if not question:
            return {'error': _("Question introuvable.")}

        session = self.create({
            'source_type': 'single_question_distractors',
            'prompt_user': instruction or '',
            'state': 'generating',
        })
        try:
            system_prompt = session._build_single_question_system_prompt()
            user_content = session._build_regenerate_user_prompt(question, instruction)
            session.prompt_system_used = system_prompt

            data, raw = self.env['digii.ai.service'].chat_json(
                system_prompt, user_content)
            session.raw_response = raw

            question._ai_apply_payload(data.get('question') or data, session)
            question.ai_validation_state = 'proposed'
            session.state = 'done'
            return {'question': question._ai_card_data()}
        except AiAgentError as exc:
            session.write({'state': 'error', 'error_message': str(exc)})
            return {'error': str(exc)}
        except Exception as exc:  # noqa: BLE001
            _logger.exception('[AI] regenerate_question a echoue')
            session.write({'state': 'error', 'error_message': str(exc)})
            return {'error': _("Erreur interne : %s", str(exc)[:300])}

    # ==================================================================
    # CONSTRUCTION DES PROMPTS
    # ==================================================================

    def _categories_context(self):
        """Texte listant les categories/sous-categories existantes pour
        que l'IA choisisse dedans plutot que d'inventer."""
        Cat = self.env['exam.category']
        parents = Cat.search([('parent_id', '=', False)], order='name')
        if not parents:
            return "Aucune categorie n'existe encore dans la banque."
        lines = []
        for parent in parents:
            subs = parent.child_ids.mapped('name')
            if subs:
                lines.append("- %s (sous-categories: %s)" % (
                    parent.name, ', '.join(subs)))
            else:
                lines.append("- %s" % parent.name)
        return '\n'.join(lines)

    def _bank_stats_context(self):
        """Contexte detaille pour la generation de regles : combien de
        questions existent par categorie / sous-categorie / difficulte /
        type cognitif. Permet a l'IA de proposer des regles REALISTES."""
        Question = self.env['survey.question']
        base = [('is_bank_question', '=', True)]
        total = Question.search_count(base)
        if not total:
            return "La banque est vide (aucune question). Impossible de composer un examen."

        _COG = {
            'memory': 'memoire', 'comprehension': 'comprehension',
            'application': 'application', 'analysis': 'analyse',
            'experience': 'experience',
        }
        _DIFF = {'easy': 'facile', 'medium': 'moyen', 'hard': 'difficile'}

        lines = ["La banque contient %d question(s) au total." % total]

        Cat = self.env['exam.category']
        parents = Cat.search([('parent_id', '=', False)], order='name')
        for parent in parents:
            cat_ids = [parent.id] + parent.child_ids.ids
            n = Question.search_count(base + [
                '|', ('exam_category_id', 'in', cat_ids),
                ('exam_subcategory_id', 'in', cat_ids)])
            if not n:
                continue
            detail = []
            # Par sous-categorie.
            for sub in parent.child_ids:
                ns = Question.search_count(base + [
                    ('exam_subcategory_id', '=', sub.id)])
                if ns:
                    detail.append("%s: %d" % (sub.name, ns))
            sub_txt = (" [" + ", ".join(detail) + "]") if detail else ""

            # Par difficulte.
            diff_parts = []
            for dk, dlabel in _DIFF.items():
                nd = Question.search_count(base + [
                    '|', ('exam_category_id', 'in', cat_ids),
                    ('exam_subcategory_id', 'in', cat_ids),
                    ('exam_difficulty', '=', dk)])
                if nd:
                    diff_parts.append("%s: %d" % (dlabel, nd))
            diff_txt = (" (difficultes -> " + ", ".join(diff_parts) + ")") if diff_parts else ""

            lines.append("- %s : %d question(s)%s%s" % (
                parent.name, n, sub_txt, diff_txt))

        # Types cognitifs disponibles (global).
        cog_parts = []
        for ck, clabel in _COG.items():
            nc = Question.search_count(base + [('cognitive_type', '=', ck)])
            if nc:
                cog_parts.append("%s: %d" % (clabel, nc))
        if cog_parts:
            lines.append("Types cognitifs disponibles: " + ", ".join(cog_parts) + ".")

        return '\n'.join(lines)

    def _build_questions_system_prompt(self, count, difficulty_distribution,
                                       question_type, cognitive_type=None,
                                       target_category=None):
        type_label = {
            'simple_choice': "QCM a reponse unique (1 seule bonne reponse)",
            'multiple_choice': "QCM a choix multiple (1 ou plusieurs bonnes reponses)",
        }[question_type]

        dist_text = ""
        if difficulty_distribution:
            parts = []
            for k in DIFFICULTY_VALUES:
                if difficulty_distribution.get(k):
                    parts.append("%s: %s" % (k, difficulty_distribution[k]))
            if parts:
                dist_text = "Repartition souhaitee par difficulte: " + ", ".join(parts) + "."

        # Consigne de type cognitif (memoire, application...).
        cognitive_text = ""
        _COG_LABELS = {
            'memory': "memoire (restitution de faits, definitions)",
            'comprehension': "comprehension (expliquer, interpreter)",
            'application': "application (utiliser dans un cas concret)",
            'analysis': "analyse (decomposer, comparer, critiquer)",
            'experience': "experience pratique (savoir-faire terrain)",
        }
        if cognitive_type and cognitive_type in _COG_LABELS:
            cognitive_text = (
                "TYPE COGNITIF IMPOSE: toutes les questions doivent etre de type "
                "'%s'. Concois-les en consequence.\n" % _COG_LABELS[cognitive_type])

        # Consigne de categorie ciblee.
        category_text = ""
        if target_category:
            category_text = (
                "CATEGORIE IMPOSEE: classe toutes les questions dans la categorie "
                "'%s'.\n" % target_category.name)

        return (
            "Tu es un assistant pedagogique expert qui redige des questions "
            "d'examen de haute qualite en francais.\n\n"
            "REGLES STRICTES:\n"
            "1. Tu reponds UNIQUEMENT avec un objet JSON valide, sans aucun texte "
            "autour ni balises markdown.\n"
            "2. Chaque question est de type '%s'.\n"
            "3. Genere EXACTEMENT %d question(s).\n"
            "4. La difficulte de chaque question est l'une de: easy, medium, hard.\n"
            "5. %s\n"
            "6. Pour la categorie et la sous-categorie, choisis de preference "
            "parmi celles existantes ci-dessous. Si aucune ne convient, propose "
            "un nom court. Mets une chaine vide si non pertinent.\n"
            "7. Chaque question a entre 3 et 5 propositions de reponse. Pour un "
            "QCM a reponse unique, exactement une reponse a 'correct': true. Pour "
            "un choix multiple, une ou plusieurs.\n"
            "8. Les distracteurs (mauvaises reponses) doivent etre plausibles, pas "
            "absurdes.\n\n"
            "%s%s"
            "CATEGORIES EXISTANTES:\n%s\n\n"
            "SCHEMA JSON ATTENDU:\n"
            "{\n"
            '  "questions": [\n'
            "    {\n"
            '      "title": "enonce de la question",\n'
            '      "type": "%s",\n'
            '      "difficulty": "easy|medium|hard",\n'
            '      "cognitive_type": "memory|comprehension|application|analysis|experience",\n'
            '      "category": "nom de categorie (existante ou nouvelle)",\n'
            '      "subcategory": "nom de sous-categorie (existante ou nouvelle)",\n'
            '      "answers": [\n'
            '        {"text": "proposition", "correct": true},\n'
            '        {"text": "proposition", "correct": false}\n'
            "      ],\n"
            '      "explanation": "courte justification de la bonne reponse",\n'
            '      "confidence": "low|medium|high"\n'
            "    }\n"
            "  ]\n"
            "}"
        ) % (type_label, count, dist_text or "Repartis les difficultes de maniere equilibree.",
             cognitive_text, category_text,
             self._categories_context(), question_type)

    def _build_questions_user_prompt(self, source_type, course, source_text,
                                     topic, user_prompt):
        chunks = []
        if user_prompt:
            chunks.append("Consigne de l'admin: %s" % user_prompt)

        if source_type == 'course' and course:
            chunks.append("Genere les questions a partir du contenu de ce cours: "
                          "\"%s\"." % course.name)
            content = self._extract_course_text(course)
            if content:
                chunks.append("CONTENU DU COURS (extrait):\n%s" % content[:8000])
            else:
                chunks.append("(Le cours n'a pas de contenu texte exploitable, "
                              "appuie-toi sur le titre et le sujet general.)")
        elif source_type == 'text' and source_text:
            chunks.append("Genere les questions a partir de ce texte:\n%s"
                          % source_text[:8000])
        elif source_type == 'topic':
            subject = topic or user_prompt or "(non precise)"
            chunks.append("Genere les questions sur le sujet suivant: %s" % subject)
        else:
            chunks.append("Genere les questions selon la consigne ci-dessus.")

        return '\n\n'.join(chunks)

    def _build_rules_system_prompt(self):
        return (
            "Tu es un expert en conception d'examens. Tu proposes des REGLES "
            "de selection de questions depuis une banque, pour composer un "
            "examen equilibre et pertinent.\n\n"
            "REGLES STRICTES:\n"
            "1. Reponds UNIQUEMENT avec un objet JSON valide, sans texte autour.\n"
            "2. Propose PLUSIEURS regles (3 a 6 en general), PAS une seule regle "
            "fourre-tout. Chaque regle cible une categorie/sous-categorie precise.\n"
            "3. Utilise les STATISTIQUES DE LA BANQUE ci-dessous : ne demande "
            "JAMAIS plus de questions qu'il n'en existe dans une categorie.\n"
            "4. Repartis intelligemment : varie les categories, les difficultes "
            "et les types cognitifs pour un examen complet et equilibre.\n"
            "5. Choisis categorie et sous-categorie parmi celles existantes. "
            "Laisse vide seulement si tu veux couvrir large.\n"
            "6. difficulty: easy, medium, hard, ou vide. cognitive_type: memory, "
            "comprehension, application, analysis, experience, ou vide.\n"
            "7. 'count' est un entier positif et REALISTE (<= questions dispo).\n"
            "8. Donne un libelle court et une 'reason' (pourquoi cette regle) "
            "pour chaque regle.\n\n"
            "STATISTIQUES DETAILLEES DE LA BANQUE:\n%s\n\n"
            "SCHEMA JSON ATTENDU:\n"
            "{\n"
            '  "rules": [\n'
            "    {\n"
            '      "name": "libelle court de la regle",\n'
            '      "category": "nom de categorie ou vide",\n'
            '      "subcategory": "nom de sous-categorie ou vide",\n'
            '      "difficulty": "easy|medium|hard ou vide",\n'
            '      "cognitive_type": "memory|comprehension|application|analysis|experience ou vide",\n'
            '      "count": 5,\n'
            '      "reason": "courte justification pedagogique"\n'
            "    }\n"
            "  ],\n"
            '  "notes": "remarques sur l\'equilibre global de l\'examen propose"\n'
            "}"
        ) % self._bank_stats_context()

    def _build_rules_user_prompt(self, survey, description):
        return (
            "Examen cible: \"%s\".\n"
            "Description de l'examen souhaite par l'admin:\n%s"
        ) % (survey.title or '', description or '(non precise)')

    def _build_single_question_system_prompt(self):
        return (
            "Tu es un assistant pedagogique. Tu retravailles UNE question "
            "d'examen en francais selon une consigne.\n\n"
            "REGLES STRICTES:\n"
            "1. Reponds UNIQUEMENT avec un objet JSON valide.\n"
            "2. Conserve le type de question (reponse unique ou choix multiple).\n"
            "3. Garde des distracteurs plausibles.\n\n"
            "SCHEMA JSON ATTENDU:\n"
            "{\n"
            '  "question": {\n'
            '    "title": "enonce",\n'
            '    "type": "simple_choice|multiple_choice",\n'
            '    "difficulty": "easy|medium|hard",\n'
            '    "category": "nom ou vide",\n'
            '    "subcategory": "nom ou vide",\n'
            '    "answers": [{"text": "...", "correct": true}],\n'
            '    "explanation": "...",\n'
            '    "confidence": "low|medium|high"\n'
            "  }\n"
            "}"
        )

    def _build_regenerate_user_prompt(self, question, instruction):
        answers = []
        for ans in question.suggested_answer_ids:
            answers.append({'text': ans.value, 'correct': bool(ans.is_correct)})
        current = {
            'title': question.title or '',
            'type': question.question_type or 'simple_choice',
            'difficulty': question.exam_difficulty or '',
            'category': question.exam_category_id.name or '',
            'subcategory': question.exam_subcategory_id.name or '',
            'answers': answers,
        }
        return (
            "Question actuelle (JSON):\n%s\n\n"
            "Consigne de modification: %s"
        ) % (json.dumps(current, ensure_ascii=False), instruction or 'Ameliore la question.')

    # ==================================================================
    # TRANSFORMATION JSON -> ENREGISTREMENTS
    # ==================================================================

    def _create_questions_from_payload(self, data, cognitive_type=None):
        self.ensure_one()
        questions_data = data.get('questions')
        if not isinstance(questions_data, list):
            raise AiAgentError(_(
                "La reponse IA ne contient pas de liste 'questions' exploitable."))

        Question = self.env['survey.question']
        created = self.env['survey.question']
        for qd in questions_data:
            if not isinstance(qd, dict) or not qd.get('title'):
                continue
            vals = self._question_vals_from_dict(qd)
            vals['ai_generation_session_id'] = self.id
            # Assigner le type cognitif si impose par l'utilisateur.
            if cognitive_type:
                vals['cognitive_type'] = cognitive_type
            created |= Question.create(vals)
        if not created:
            raise AiAgentError(_(
                "Aucune question valide n'a pu etre extraite de la reponse IA."))
        return created

    def _question_vals_from_dict(self, qd):
        qtype = qd.get('type')
        if qtype not in QUESTION_TYPE_VALUES:
            qtype = 'simple_choice'
        difficulty = qd.get('difficulty')
        if difficulty not in DIFFICULTY_VALUES:
            difficulty = False
        confidence = qd.get('confidence')
        if confidence not in ('low', 'medium', 'high'):
            confidence = False

        cat_id, sub_id = self._resolve_category(
            qd.get('category'), qd.get('subcategory'), create_missing=True)

        answer_cmds = []
        for ans in (qd.get('answers') or []):
            if not isinstance(ans, dict):
                continue
            text = (ans.get('text') or '').strip()
            if not text:
                continue
            is_ok = bool(ans.get('correct'))
            answer_cmds.append((0, 0, {
                'value': text,
                'is_correct': is_ok,
                'answer_score': 1.0 if is_ok else 0.0,
            }))

        # Type cognitif deduit par l'IA (si valide).
        ai_cognitive = qd.get('cognitive_type')
        if ai_cognitive not in ('memory', 'comprehension', 'application',
                                'analysis', 'experience'):
            ai_cognitive = False

        vals = {
            'title': qd['title'].strip(),
            'question_type': qtype,
            'is_bank_question': False,            # entre en banque seulement a l'approbation
            'survey_id': False,
            'exam_category_id': cat_id,
            'exam_subcategory_id': sub_id,
            'exam_difficulty': difficulty,
            'ai_generated': True,
            'ai_validation_state': 'proposed',
            'ai_confidence': confidence,
            'ai_explanation': qd.get('explanation') or '',
        }
        if ai_cognitive:
            vals['cognitive_type'] = ai_cognitive
        if answer_cmds:
            vals['suggested_answer_ids'] = answer_cmds
        return vals

    def _create_rule_proposals_from_payload(self, survey, data):
        self.ensure_one()
        rules_data = data.get('rules')
        if not isinstance(rules_data, list):
            raise AiAgentError(_(
                "La reponse IA ne contient pas de liste 'rules' exploitable."))

        Proposal = self.env['digii.ai.rule.proposal']
        created = Proposal
        for rd in rules_data:
            if not isinstance(rd, dict):
                continue
            difficulty = rd.get('difficulty')
            if difficulty not in DIFFICULTY_VALUES:
                difficulty = False
            cognitive = rd.get('cognitive_type')
            if cognitive not in ('memory', 'comprehension', 'application',
                                 'analysis', 'experience'):
                cognitive = False
            cat_id, sub_id = self._resolve_category(
                rd.get('category'), rd.get('subcategory'))
            try:
                count = int(rd.get('count') or 0)
            except (TypeError, ValueError):
                count = 0
            if count <= 0:
                count = 1
            created |= Proposal.create({
                'session_id': self.id,
                'survey_id': survey.id,
                'name': (rd.get('name') or 'Regle IA').strip(),
                'exam_category_id': cat_id,
                'exam_subcategory_id': sub_id,
                'exam_difficulty': difficulty,
                'cognitive_type': cognitive,
                'reason': (rd.get('reason') or '').strip(),
                'count': count,
            })
        if not created:
            raise AiAgentError(_(
                "Aucune regle valide n'a pu etre extraite de la reponse IA."))
        return created

    @api.model
    def _resolve_category(self, cat_name, sub_name, create_missing=False):
        """Mappe des noms de categorie/sous-categorie vers des ids.
        Si create_missing=True, cree les categories/sous-categories absentes
        (utile pour les questions generees par l'IA qui proposent de
        nouveaux themes). Sinon renvoie False si introuvable."""
        Cat = self.env['exam.category']
        cat_id = False
        sub_id = False
        cat_name = (cat_name or '').strip()
        sub_name = (sub_name or '').strip()

        if cat_name:
            parent = Cat.search([
                ('parent_id', '=', False),
                ('name', '=ilike', cat_name),
            ], limit=1)
            if parent:
                cat_id = parent.id
            elif create_missing:
                parent = Cat.create({'name': cat_name})
                cat_id = parent.id

        if sub_name:
            sub_domain = [('parent_id', '!=', False), ('name', '=ilike', sub_name)]
            if cat_id:
                sub_domain = [('parent_id', '=', cat_id), ('name', '=ilike', sub_name)]
            sub = Cat.search(sub_domain, limit=1)
            if sub:
                sub_id = sub.id
                if not cat_id and sub.parent_id:
                    cat_id = sub.parent_id.id
            elif create_missing and cat_id:
                # Creer la sous-categorie sous le parent.
                sub = Cat.create({'name': sub_name, 'parent_id': cat_id})
                sub_id = sub.id
        return cat_id, sub_id

    # ==================================================================
    # EXTRACTION CONTENU COURS
    # ==================================================================

    @api.model
    def _extract_course_text(self, course):
        """Concatene le texte exploitable des lecons d'un cours."""
        from html import unescape
        import re

        def strip_html(value):
            if not value:
                return ''
            text = re.sub(r'<[^>]+>', ' ', value)
            return unescape(re.sub(r'\s+', ' ', text)).strip()

        parts = []
        slides = course.slide_ids.filtered(lambda s: not s.is_category)
        for slide in slides:
            parts.append('## %s' % (slide.name or ''))
            desc = strip_html(slide.description or '')
            if desc:
                parts.append(desc)
            body = strip_html(getattr(slide, 'html_content', '') or '')
            if body:
                parts.append(body)
        return '\n'.join(p for p in parts if p)

    # ==================================================================
    # Actions de vue
    # ==================================================================

    def action_view_questions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Questions generees'),
            'res_model': 'survey.question',
            'view_mode': 'list,form',
            'domain': [('ai_generation_session_id', '=', self.id)],
        }
