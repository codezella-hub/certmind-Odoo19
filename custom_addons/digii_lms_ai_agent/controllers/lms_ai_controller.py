# -*- coding: utf-8 -*-
"""
Controleur portail de l'agent tuteur IA.

Expose des routes JSON appelees par le panneau de chat cote site web :
  - /lms_ai/tutor/ask     : poser une question au tuteur
  - /lms_ai/sessions      : lister ses conversations
  - /lms_ai/session/new   : demarrer une nouvelle conversation
  - /lms_ai/session/load  : charger une conversation
  - /lms_ai/session/rename, /pin, /delete, /delete_all
  - /lms_ai/message/favorite : marquer un message favori

Toutes les routes sont en auth='user' : seul un utilisateur connecte
(etudiant) peut les appeler, et les record rules garantissent qu'il
n'accede qu'a ses propres donnees.
"""
from odoo import http
from odoo.http import request


class LmsAiPortalController(http.Controller):

    # ------------------------------------------------------------------
    # Tuteur : poser une question
    # ------------------------------------------------------------------
    @http.route('/lms_ai/tutor/ask', type='json', auth='user', website=True)
    def tutor_ask(self, question=None, slide_id=None, session_id=None, **kw):
        question = (question or '').strip()
        if not question:
            return {'error': "Question vide."}

        env = request.env
        slide = env['slide.slide'].sudo().browse(int(slide_id)) \
            if slide_id else env['slide.slide']

        # Recupere ou cree la conversation.
        Session = env['digii.lms.ai.chat.session'].sudo()
        if session_id:
            session = Session.browse(int(session_id))
            if not session.exists() or session.user_id.id != env.user.id:
                return {'error': "Conversation introuvable."}
        else:
            session = Session.create({
                'user_id': env.user.id,
                'channel_id': slide.channel_id.id if slide else False,
                'slide_id': slide.id if slide else False,
            })
        session._auto_title_from(question)

        # Historique pour le contexte.
        history = [{'role': m.role, 'content': m.content}
                   for m in session.message_ids]

        # Enregistre la question.
        Message = env['digii.lms.ai.chat.message'].sudo()
        Message.create({
            'session_id': session.id, 'role': 'user', 'content': question,
        })

        # Appelle le tuteur.
        answer = env['digii.lms.ai.tutor'].sudo().ask_tutor(
            slide, question, history=history)

        # Enregistre la reponse.
        msg = Message.create({
            'session_id': session.id, 'role': 'assistant', 'content': answer,
        })

        return {
            'answer': answer,
            'session_id': session.id,
            'message_id': msg.id,
            'title': session.name,
        }

    # ------------------------------------------------------------------
    # Historique : lister les conversations
    # ------------------------------------------------------------------
    @http.route('/lms_ai/sessions', type='json', auth='user', website=True)
    def list_sessions(self, search=None, **kw):
        env = request.env
        domain = [('user_id', '=', env.user.id)]
        if search:
            domain.append(('name', 'ilike', search.strip()))
        sessions = env['digii.lms.ai.chat.session'].sudo().search(domain)
        return {
            'sessions': [{
                'id': s.id,
                'name': s.name,
                'course': s.channel_id.name or '',
                'is_pinned': s.is_pinned,
                'message_count': s.message_count,
            } for s in sessions],
        }

    @http.route('/lms_ai/session/load', type='json', auth='user', website=True)
    def load_session(self, session_id=None, **kw):
        env = request.env
        session = env['digii.lms.ai.chat.session'].sudo().browse(int(session_id))
        if not session.exists() or session.user_id.id != env.user.id:
            return {'error': "Conversation introuvable."}
        return {
            'id': session.id,
            'name': session.name,
            'messages': [{
                'id': m.id,
                'role': m.role,
                'content': m.content,
                'is_favorite': m.is_favorite,
            } for m in session.message_ids],
        }

    @http.route('/lms_ai/session/new', type='json', auth='user', website=True)
    def new_session(self, slide_id=None, **kw):
        env = request.env
        slide = env['slide.slide'].sudo().browse(int(slide_id)) \
            if slide_id else env['slide.slide']
        session = env['digii.lms.ai.chat.session'].sudo().create({
            'user_id': env.user.id,
            'channel_id': slide.channel_id.id if slide else False,
            'slide_id': slide.id if slide else False,
        })
        return {'session_id': session.id, 'name': session.name}

    # ------------------------------------------------------------------
    # Historique enrichi : renommer, epingler, favori, supprimer
    # ------------------------------------------------------------------
    @http.route('/lms_ai/session/rename', type='json', auth='user', website=True)
    def rename_session(self, session_id=None, name=None, **kw):
        session = self._own_session(session_id)
        if not session:
            return {'error': "Introuvable."}
        session.name = (name or '').strip() or session.name
        return {'ok': True, 'name': session.name}

    @http.route('/lms_ai/session/pin', type='json', auth='user', website=True)
    def pin_session(self, session_id=None, **kw):
        session = self._own_session(session_id)
        if not session:
            return {'error': "Introuvable."}
        session.is_pinned = not session.is_pinned
        return {'ok': True, 'is_pinned': session.is_pinned}

    @http.route('/lms_ai/session/delete', type='json', auth='user', website=True)
    def delete_session(self, session_id=None, **kw):
        session = self._own_session(session_id)
        if not session:
            return {'error': "Introuvable."}
        session.unlink()
        return {'ok': True}

    @http.route('/lms_ai/session/delete_all', type='json', auth='user',
                website=True)
    def delete_all_sessions(self, **kw):
        env = request.env
        env['digii.lms.ai.chat.session'].sudo().search(
            [('user_id', '=', env.user.id)]).unlink()
        return {'ok': True}

    @http.route('/lms_ai/message/favorite', type='json', auth='user',
                website=True)
    def favorite_message(self, message_id=None, **kw):
        env = request.env
        msg = env['digii.lms.ai.chat.message'].sudo().browse(int(message_id))
        if not msg.exists() or msg.session_id.user_id.id != env.user.id:
            return {'error': "Introuvable."}
        msg.is_favorite = not msg.is_favorite
        return {'ok': True, 'is_favorite': msg.is_favorite}

    # ------------------------------------------------------------------
    def _own_session(self, session_id):
        """Retourne la session si elle appartient a l'utilisateur, sinon False."""
        if not session_id:
            return False
        env = request.env
        session = env['digii.lms.ai.chat.session'].sudo().browse(int(session_id))
        if session.exists() and session.user_id.id == env.user.id:
            return session
        return False
