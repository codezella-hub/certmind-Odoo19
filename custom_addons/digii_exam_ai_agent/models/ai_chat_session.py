# -*- coding: utf-8 -*-
"""
Assistant Q&A analytique avec sessions persistantes.

- digii.ai.chat.session : une conversation par utilisateur (historique).
- digii.ai.chat.message : les messages (user / assistant), avec charts JSON.

L'assistant recoit les statistiques REELLES de la plateforme (LMS + examens
+ proctoring + banque de questions) et repond avec du texte et des
graphiques de comparaison.
"""
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DigiiAiChatSession(models.Model):
    _name = 'digii.ai.chat.session'
    _description = 'Session de conversation avec l\'assistant IA'
    _order = 'write_date desc'

    name = fields.Char('Titre', default='Nouvelle conversation')
    user_id = fields.Many2one(
        'res.users', string='Utilisateur', required=True,
        default=lambda self: self.env.user, index=True, ondelete='cascade')
    message_ids = fields.One2many(
        'digii.ai.chat.message', 'session_id', string='Messages')
    message_count = fields.Integer(compute='_compute_message_count')
    active = fields.Boolean(default=True)

    @api.depends('message_ids')
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    # ==================================================================
    # API principale : poser une question
    # ==================================================================

    def ask(self, question):
        """
        Pose une question a l'assistant analytique dans cette session.
        Retourne le message assistant cree (avec texte + charts).
        """
        self.ensure_one()
        question = (question or '').strip()
        if not question:
            raise UserError(_("Question vide."))

        # 1. Enregistrer le message utilisateur.
        Msg = self.env['digii.ai.chat.message']
        Msg.create({
            'session_id': self.id,
            'role': 'user',
            'content': question,
        })

        # 2. Construire le prompt avec donnees reelles + historique.
        system_prompt = self._build_system_prompt()
        user_content = self._build_user_content(question)

        # 3. Appel LLM.
        data, _raw = self.env['digii.ai.service'].chat_json(
            system_prompt, user_content)

        answer = (data.get('answer') or '').strip() or _(
            "Je n'ai pas pu formuler de réponse.")
        charts = data.get('charts') or []
        charts = [c for c in charts if self._valid_chart(c)]
        tables = data.get('tables') or []
        tables = [t for t in tables if self._valid_table(t)]

        # 4. Enregistrer la reponse.
        assistant_msg = Msg.create({
            'session_id': self.id,
            'role': 'assistant',
            'content': answer,
            'charts_json': json.dumps(charts) if charts else False,
            'tables_json': json.dumps(tables) if tables else False,
        })

        # 5. Titre automatique de la session (premiere question).
        if self.name == 'Nouvelle conversation':
            self.name = question[:60] + ('…' if len(question) > 60 else '')

        return assistant_msg

    @staticmethod
    def _valid_chart(c):
        if not isinstance(c, dict):
            return False
        if c.get('type') not in ('bar', 'pie', 'line'):
            return False
        labels = c.get('labels')
        values = c.get('values')
        if not isinstance(labels, list) or not isinstance(values, list):
            return False
        if not labels or len(labels) != len(values):
            return False
        try:
            [float(v) for v in values]
        except (TypeError, ValueError):
            return False
        return True

    @staticmethod
    def _valid_table(t):
        """Table = {title, headers: [...], rows: [[...], ...]} alignee."""
        if not isinstance(t, dict):
            return False
        headers = t.get('headers')
        rows = t.get('rows')
        if not isinstance(headers, list) or not headers:
            return False
        if not isinstance(rows, list) or not rows:
            return False
        for r in rows:
            if not isinstance(r, list) or len(r) != len(headers):
                return False
        return True

    # ==================================================================
    # Prompts
    # ==================================================================

    def _build_system_prompt(self):
        return (
            "Tu es l'assistant analytique d'une plateforme de formation (LMS) "
            "et d'examens en ligne. Tu reponds aux questions de l'administrateur "
            "de facon claire, precise et DETAILLEE, en te basant UNIQUEMENT sur "
            "les DONNEES REELLES fournies ci-dessous.\n\n"
            "LANGUE: detecte la langue de la question (francais ou anglais) et "
            "reponds TOUJOURS dans cette meme langue, y compris les titres des "
            "graphiques et tableaux. / LANGUAGE: detect the language of the "
            "question (French or English) and ALWAYS answer in that same "
            "language, including chart and table titles.\n\n"
            "REGLES STRICTES:\n"
            "1. Reponds UNIQUEMENT avec un objet JSON valide, sans texte autour.\n"
            "2. Le champ 'answer' contient ta reponse en texte (tu peux utiliser "
            "des puces avec '-' et du **gras**). Sois detaille : donne les "
            "chiffres exacts, des comparaisons et une courte interpretation.\n"
            "3. GRAPHIQUES ('charts', max 2) - choisis le type le plus adapte :\n"
            "   - 'bar' : comparaison entre elements (examens, cours, categories)\n"
            "   - 'pie' : repartition / proportions d'un tout (ex: niveaux de "
            "risque, repartition par difficulte)\n"
            "   - 'line' : evolution ou tendance ordonnee (ex: scores dans le "
            "temps, progression)\n"
            "4. TABLEAUX ('tables', max 2) : pour des donnees detaillees "
            "multi-colonnes (ex: liste d'examens avec passages, reussites, "
            "score moyen). headers et rows doivent etre alignes.\n"
            "5. Si la donnee demandee n'est pas dans le contexte, dis-le "
            "honnetement dans 'answer' (n'invente JAMAIS de chiffres).\n\n"
            "DONNEES REELLES DE LA PLATEFORME:\n%s\n\n"
            "SCHEMA JSON ATTENDU:\n"
            "{\n"
            '  "answer": "reponse detaillee en texte",\n'
            '  "charts": [\n'
            "    {\n"
            '      "type": "bar|pie|line",\n'
            '      "title": "titre du graphique",\n'
            '      "labels": ["A", "B", "C"],\n'
            '      "values": [10, 20, 30]\n'
            "    }\n"
            "  ],\n"
            '  "tables": [\n'
            "    {\n"
            '      "title": "titre du tableau",\n'
            '      "headers": ["Colonne 1", "Colonne 2"],\n'
            '      "rows": [["val", "val"], ["val", "val"]]\n'
            "    }\n"
            "  ]\n"
            "}"
        ) % self._analytics_context()

    def _build_user_content(self, question):
        """Question + petit historique pour le contexte conversationnel."""
        history_lines = []
        # Les 6 derniers messages (hors la question tout juste creee).
        msgs = self.message_ids.sorted('id')[-7:-1]
        for m in msgs:
            prefix = "Admin" if m.role == 'user' else "Assistant"
            content = (m.content or '')[:500]
            history_lines.append("%s: %s" % (prefix, content))
        history = "\n".join(history_lines)
        if history:
            return ("HISTORIQUE RECENT DE LA CONVERSATION:\n%s\n\n"
                    "NOUVELLE QUESTION DE L'ADMIN:\n%s") % (history, question)
        return "QUESTION DE L'ADMIN:\n%s" % question

    # ==================================================================
    # Contexte analytique : les donnees reelles
    # ==================================================================

    def _analytics_context(self):
        """Agrege les statistiques cles de la plateforme en texte compact."""
        parts = []
        parts.append(self._ctx_lms())
        parts.append(self._ctx_exams())
        parts.append(self._ctx_certificates())
        parts.append(self._ctx_proctoring())
        parts.append(self._ctx_question_bank())
        return "\n\n".join(p for p in parts if p)

    def _ctx_lms(self):
        Channel = self.env['slide.channel'].sudo()
        channels = Channel.search([], limit=15, order='total_slides desc')
        if not channels:
            return "COURS (LMS): aucun cours."
        lines = ["COURS (LMS): %d cours au total." % Channel.search_count([])]
        for ch in channels:
            members = ch.members_count if hasattr(ch, 'members_count') else \
                len(ch.channel_partner_ids)
            done = 0
            if hasattr(ch, 'channel_partner_ids'):
                done = len(ch.channel_partner_ids.filtered(
                    lambda p: getattr(p, 'completed', False)))
            lines.append("- \"%s\": %d inscrit(s), %d ayant complete, "
                         "%d lecon(s)" % (ch.name, members, done,
                                          ch.total_slides or 0))
        return "\n".join(lines)

    def _ctx_exams(self):
        Survey = self.env['survey.survey'].sudo()
        exams = Survey.search([('is_exam', '=', True)], limit=15)
        if not exams:
            return "EXAMENS: aucun examen."
        UserInput = self.env['survey.user_input'].sudo()
        lines = ["EXAMENS: %d examen(s) au total." %
                 Survey.search_count([('is_exam', '=', True)])]
        for ex in exams:
            inputs = UserInput.search([
                ('survey_id', '=', ex.id), ('state', '=', 'done')])
            n = len(inputs)
            if n:
                passed = len(inputs.filtered('scoring_success'))
                avg = sum(inputs.mapped('scoring_percentage')) / n
                lines.append(
                    "- \"%s\": %d passage(s), %d reussite(s) (taux %.0f%%), "
                    "score moyen %.1f%%" % (
                        ex.title, n, passed,
                        (passed * 100.0 / n), avg))
            else:
                lines.append("- \"%s\": aucun passage termine." % ex.title)
        return "\n".join(lines)

    def _ctx_certificates(self):
        Cert = self.env.get('exam.certificate')
        if Cert is None:
            return ""
        Cert = Cert.sudo()
        total = Cert.search_count([])
        return "CERTIFICATS: %d certificat(s) delivre(s) au total." % total

    def _ctx_proctoring(self):
        Session = self.env.get('exam.proctoring.session')
        if Session is None:
            return ""
        Session = Session.sudo()
        total = Session.search_count([])
        if not total:
            return "PROCTORING: aucune session."
        analyzed = Session.search([('ai_analysis_state', '=', 'done')])
        lines = ["PROCTORING: %d session(s) au total, %d analysee(s) par IA."
                 % (total, len(analyzed))]
        if analyzed:
            by_level = {}
            for s in analyzed:
                lvl = s.ai_risk_level or 'inconnu'
                by_level[lvl] = by_level.get(lvl, 0) + 1
            label = {'none': 'aucun risque', 'suspect': 'a surveiller',
                     'high': 'tres suspect', 'very_high': 'triche probable'}
            detail = ", ".join("%s: %d" % (label.get(k, k), v)
                               for k, v in by_level.items())
            avg = sum(analyzed.mapped('ai_risk_score')) / len(analyzed)
            lines.append("Repartition des niveaux de risque -> %s. "
                         "Score de risque moyen: %.0f/100." % (detail, avg))
        return "\n".join(lines)

    def _ctx_question_bank(self):
        Question = self.env['survey.question'].sudo()
        base = [('is_bank_question', '=', True)]
        total = Question.search_count(base)
        if not total:
            return "BANQUE DE QUESTIONS: vide."
        lines = ["BANQUE DE QUESTIONS: %d question(s)." % total]

        Cat = self.env['exam.category'].sudo()
        for parent in Cat.search([('parent_id', '=', False)], order='name'):
            cat_ids = [parent.id] + parent.child_ids.ids
            n = Question.search_count(base + [
                '|', ('exam_category_id', 'in', cat_ids),
                ('exam_subcategory_id', 'in', cat_ids)])
            if n:
                lines.append("- Categorie \"%s\": %d question(s)" %
                             (parent.name, n))

        for diff, lab in (('easy', 'faciles'), ('medium', 'moyennes'),
                          ('hard', 'difficiles')):
            nd = Question.search_count(base + [('exam_difficulty', '=', diff)])
            if nd:
                lines.append("- %d question(s) %s" % (nd, lab))

        cog_labels = {'memory': 'memoire', 'comprehension': 'comprehension',
                      'application': 'application', 'analysis': 'analyse',
                      'experience': 'experience'}
        cog_parts = []
        for ck, cl in cog_labels.items():
            nc = Question.search_count(base + [('cognitive_type', '=', ck)])
            if nc:
                cog_parts.append("%s: %d" % (cl, nc))
        if cog_parts:
            lines.append("- Types cognitifs -> " + ", ".join(cog_parts))
        return "\n".join(lines)


class DigiiAiChatMessage(models.Model):
    _name = 'digii.ai.chat.message'
    _description = 'Message d\'une conversation IA'
    _order = 'id'

    session_id = fields.Many2one(
        'digii.ai.chat.session', string='Session', required=True,
        ondelete='cascade', index=True)
    role = fields.Selection([
        ('user', 'Utilisateur'),
        ('assistant', 'Assistant'),
    ], required=True)
    content = fields.Text('Contenu')
    charts_json = fields.Text('Graphiques (JSON)')
    tables_json = fields.Text('Tableaux (JSON)')

    def _to_frontend(self):
        self.ensure_one()
        charts = []
        if self.charts_json:
            try:
                charts = json.loads(self.charts_json)
            except (ValueError, TypeError):
                charts = []
        tables = []
        if self.tables_json:
            try:
                tables = json.loads(self.tables_json)
            except (ValueError, TypeError):
                tables = []
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content or '',
            'charts': charts,
            'tables': tables,
        }
