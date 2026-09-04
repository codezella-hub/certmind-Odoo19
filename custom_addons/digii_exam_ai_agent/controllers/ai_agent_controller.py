# -*- coding: utf-8 -*-
"""
Routes JSON de l'agent IA.

Toutes les routes sont auth='user' et reservees au groupe
digii_exam_ai_agent.group_exam_ai_user. Les operations d'ecriture sur la
banque (approve/reject) verifient en plus les droits ORM sur
survey.question.
"""
import logging

from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class DigiiExamAiController(http.Controller):

    def _check_group(self):
        if not request.env.user.has_group('digii_exam_ai_agent.group_exam_ai_user'):
            raise AccessError(_("Acces refuse a l'assistant IA."))

    # ------------------------------------------------------------------
    # Etat de configuration (pour afficher un avertissement dans l'UI)
    # ------------------------------------------------------------------

    @http.route('/digii_exam_ai_agent/config_status', type='json', auth='user')
    def config_status(self, **kw):
        self._check_group()
        Service = request.env['digii.ai.service']
        cfg = Service._get_config()
        return {
            'configured': bool(cfg['api_key']),
            'model': cfg['model'],
            'user_lang': (request.env.user.lang or 'fr_FR')[:2],
        }

    # ------------------------------------------------------------------
    # Generation de questions
    # ------------------------------------------------------------------

    @http.route('/digii_exam_ai_agent/generate_questions', type='json', auth='user')
    def generate_questions(self, source_type='topic', count=5,
                           difficulty_distribution=None, question_type='simple_choice',
                           source_course_id=None, source_text=None, topic=None,
                           user_prompt=None, cognitive_type=None, category_id=None, **kw):
        self._check_group()
        return request.env['digii.ai.generation.session'].generate_questions(
            source_type=source_type,
            count=count,
            difficulty_distribution=difficulty_distribution,
            question_type=question_type,
            source_course_id=source_course_id,
            source_text=source_text,
            topic=topic,
            user_prompt=user_prompt,
            cognitive_type=cognitive_type,
            category_id=category_id,
        )

    # ------------------------------------------------------------------
    # Co-pilote regles
    # ------------------------------------------------------------------

    @http.route('/digii_exam_ai_agent/generate_rules', type='json', auth='user')
    def generate_rules(self, survey_id=None, description='', **kw):
        self._check_group()
        if not survey_id:
            return {'error': _("Aucun examen cible n'a ete specifie.")}
        return request.env['digii.ai.generation.session'].generate_rules(
            survey_id=survey_id, description=description)

    @http.route('/digii_exam_ai_agent/check_feasibility', type='json', auth='user')
    def check_feasibility(self, proposals=None, **kw):
        """Recalcule la faisabilite d'une liste de propositions (par id)."""
        self._check_group()
        proposals = proposals or []
        ids = [int(p) for p in proposals if p]
        records = request.env['digii.ai.rule.proposal'].browse(ids).exists()
        return {'rules': [r._ai_card_data() for r in records]}

    @http.route('/digii_exam_ai_agent/accept_rule', type='json', auth='user')
    def accept_rule(self, proposal_id=None, **kw):
        self._check_group()
        prop = request.env['digii.ai.rule.proposal'].browse(
            int(proposal_id)).exists()
        if not prop:
            return {'error': _("Proposition introuvable.")}
        rule = prop.accept()
        return {'ok': True, 'rule_id': rule.id, 'proposal': prop._ai_card_data()}

    @http.route('/digii_exam_ai_agent/reject_rule', type='json', auth='user')
    def reject_rule(self, proposal_id=None, **kw):
        self._check_group()
        prop = request.env['digii.ai.rule.proposal'].browse(
            int(proposal_id)).exists()
        if not prop:
            return {'error': _("Proposition introuvable.")}
        prop.reject()
        return {'ok': True, 'proposal': prop._ai_card_data()}

    # ------------------------------------------------------------------
    # Actions de revue sur une question proposee
    # ------------------------------------------------------------------

    @http.route('/digii_exam_ai_agent/review_action', type='json', auth='user')
    def review_action(self, question_id=None, action=None, payload=None, **kw):
        self._check_group()
        question = request.env['survey.question'].browse(
            int(question_id)).exists()
        if not question:
            return {'error': _("Question introuvable.")}

        try:
            if action == 'approve':
                question.ai_approve()
                return {'ok': True, 'question': question._ai_card_data()}
            elif action == 'reject':
                question.ai_reject()
                return {'ok': True, 'rejected': True, 'question_id': question.id}
            elif action == 'edit':
                # payload = dict de champs a ecrire (title, answers, difficulty...)
                question._check_bank_write_access()
                question._ai_apply_payload(payload or {})
                question.ai_mark_edited()
                return {'ok': True, 'question': question._ai_card_data()}
            elif action == 'regenerate':
                instruction = (payload or {}).get('instruction', '')
                return request.env['digii.ai.generation.session'].regenerate_question(
                    question.id, instruction)
            else:
                return {'error': _("Action inconnue : %s", action)}
        except AccessError as exc:
            return {'error': str(exc)}
        except Exception as exc:  # noqa: BLE001
            _logger.exception('[AI] review_action a echoue')
            return {'error': _("Erreur : %s", str(exc)[:300])}

    # ------------------------------------------------------------------
    # Donnees de support pour le panneau (cours, examens)
    # ------------------------------------------------------------------

    @http.route('/digii_exam_ai_agent/context_data', type='json', auth='user')
    def context_data(self, **kw):
        """Liste les cours et examens pour les selecteurs du panneau."""
        self._check_group()
        env = request.env
        courses = env['slide.channel'].search_read(
            [], ['id', 'name'], limit=200, order='name')
        exams = env['survey.survey'].search_read(
            [('is_exam', '=', True)], ['id', 'title'], limit=200, order='title')
        # Categories de la banque (pour le menu de generation ciblee).
        categories = env['exam.category'].search_read(
            [], ['id', 'name'], limit=200, order='name')
        return {
            'courses': courses,
            'exams': [{'id': e['id'], 'name': e['title']} for e in exams],
            'categories': categories,
        }

    @http.route('/digii_exam_ai_agent/session/<int:session_id>/status',
                type='json', auth='user')
    def session_status(self, session_id, **kw):
        self._check_group()
        session = request.env['digii.ai.generation.session'].browse(
            session_id).exists()
        if not session:
            return {'error': _("Session introuvable.")}
        return {
            'state': session.state,
            'error_message': session.error_message or '',
        }

    # ------------------------------------------------------------------
    # Assistant Q&A analytique (sessions + historique)
    # ------------------------------------------------------------------

    @http.route('/digii_exam_ai_agent/chat/sessions', type='json', auth='user')
    def chat_sessions(self, **kw):
        """Liste les conversations de l'utilisateur courant."""
        self._check_group()
        sessions = request.env['digii.ai.chat.session'].search(
            [('user_id', '=', request.env.user.id)], limit=30)
        return {'sessions': [
            {'id': s.id, 'name': s.name, 'count': s.message_count}
            for s in sessions
        ]}

    @http.route('/digii_exam_ai_agent/chat/new', type='json', auth='user')
    def chat_new(self, **kw):
        """Cree une nouvelle conversation."""
        self._check_group()
        session = request.env['digii.ai.chat.session'].create({})
        return {'session_id': session.id, 'name': session.name}

    @http.route('/digii_exam_ai_agent/chat/history', type='json', auth='user')
    def chat_history(self, session_id=None, **kw):
        """Renvoie l'historique complet d'une conversation."""
        self._check_group()
        session = request.env['digii.ai.chat.session'].browse(
            int(session_id or 0)).exists()
        if not session or session.user_id.id != request.env.user.id:
            return {'error': _("Conversation introuvable.")}
        return {
            'session_id': session.id,
            'name': session.name,
            'messages': [m._to_frontend() for m in session.message_ids],
        }

    @http.route('/digii_exam_ai_agent/chat/delete', type='json', auth='user')
    def chat_delete(self, session_id=None, **kw):
        """Supprime UNE conversation de l'utilisateur courant."""
        self._check_group()
        session = request.env['digii.ai.chat.session'].browse(
            int(session_id or 0)).exists()
        if not session or session.user_id.id != request.env.user.id:
            return {'error': _("Conversation introuvable.")}
        session.unlink()
        return {'ok': True}

    @http.route('/digii_exam_ai_agent/chat/delete_all', type='json', auth='user')
    def chat_delete_all(self, **kw):
        """Supprime TOUTES les conversations de l'utilisateur courant."""
        self._check_group()
        sessions = request.env['digii.ai.chat.session'].search(
            [('user_id', '=', request.env.user.id)])
        count = len(sessions)
        sessions.unlink()
        return {'ok': True, 'deleted': count}

    @http.route('/digii_exam_ai_agent/chat/ask', type='json', auth='user')
    def chat_ask(self, session_id=None, question=None, **kw):
        """Pose une question dans une conversation (creee si absente)."""
        self._check_group()
        Session = request.env['digii.ai.chat.session']
        session = Session.browse(int(session_id or 0)).exists()
        if not session or session.user_id.id != request.env.user.id:
            session = Session.create({})
        try:
            msg = session.ask(question)
        except Exception as exc:
            _logger.exception("Erreur assistant Q&A")
            return {'error': str(exc), 'session_id': session.id}
        return {
            'session_id': session.id,
            'session_name': session.name,
            'message': msg._to_frontend(),
        }
