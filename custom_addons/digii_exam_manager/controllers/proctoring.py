# -*- coding: utf-8 -*-
import base64
import json
import logging

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

EXAMS_PER_PAGE = 9   # 3 colonnes × 3 lignes


class ProctoringController(http.Controller):

    # =========================================================================
    # HELPER: rejets candidat (badge "Rejeté" sur /my/exams)
    # =========================================================================

    def _compute_rejected_exams(self, partner, exams):
        """Retourne (rejected_exam_ids, rejected_reasons) pour le candidat.

        Un examen est considéré comme rejeté si, pour ce candidat :
          - une session de proctoring est à l'état 'rejected', OU
          - un user_input est marqué is_proctoring_rejected (exclusion en
            cours d'examen ou certificat rejeté).
        """
        rejected_exam_ids = set()
        rejected_reasons = {}
        if not exams:
            return rejected_exam_ids, rejected_reasons

        exam_ids = exams.ids

        # 1. Sessions de proctoring rejetées
        ProcSession = request.env['exam.proctoring.session'].sudo()
        rejected_sessions = ProcSession.search([
            ('survey_id',  'in', exam_ids),
            ('partner_id', '=', partner.id),
            ('state',      '=', 'rejected'),
        ], order='create_date desc')
        for sess in rejected_sessions:
            rejected_exam_ids.add(sess.survey_id.id)
            rejected_reasons.setdefault(
                sess.survey_id.id, sess.rejection_reason or 'Session rejetée par le procteur.')

        # 2. user_input marqués rejetés (exclusion / certificat rejeté)
        UserInput = request.env['survey.user_input'].sudo()
        rejected_inputs = UserInput.search([
            ('survey_id',              'in', exam_ids),
            ('partner_id',             '=', partner.id),
            ('is_proctoring_rejected', '=', True),
        ], order='create_date desc')
        for ui in rejected_inputs:
            rejected_exam_ids.add(ui.survey_id.id)
            rejected_reasons.setdefault(
                ui.survey_id.id, ui.proctoring_rejection_reason or 'Examen rejeté.')

        return rejected_exam_ids, rejected_reasons

    # =========================================================================
    # CANDIDATE PORTAL: exam list  (WITH PAGINATION)
    # =========================================================================

    @http.route(
        ['/my/exams', '/my/exams/page/<int:page>'],
        type='http', auth='user', website=True,
    )
    def portal_my_exams(self, page=1, already_done=None, **kw):
        partner = request.env.user.partner_id
        Survey  = request.env['survey.survey'].sudo()

        domain = [('is_exam', '=', True)]
        total  = Survey.search_count(domain)

        # ── Pagination ──────────────────────────────────────────────────────
        pager = request.website.pager(
            url='/my/exams',
            total=total,
            page=page,
            step=EXAMS_PER_PAGE,
            url_args={},
        )

        exams = Survey.search(
            domain,
            order='create_date desc',
            limit=EXAMS_PER_PAGE,
            offset=pager['offset'],
        )

        # ── Sessions actives ────────────────────────────────────────────────
        ProcSession    = request.env['exam.proctoring.session'].sudo()
        active_sessions = {}
        for exam in exams:
            session = ProcSession.search([
                ('survey_id',  '=', exam.id),
                ('partner_id', '=', partner.id),
                ('state', 'in', ('waiting', 'authorized', 'in_exam')),
            ], limit=1)
            if session:
                active_sessions[exam.id] = session

        # ── Tentatives passées ───────────────────────────────────────────────
        UserInput         = request.env['survey.user_input'].sudo()
        past_attempts     = {}
        completed_exam_ids = set()
        for exam in exams:
            attempts = UserInput.search([
                ('survey_id',  '=', exam.id),
                ('partner_id', '=', partner.id),
                ('state',      '=', 'done'),
            ], order='create_date desc')
            if attempts:
                past_attempts[exam.id] = attempts
                completed_exam_ids.add(exam.id)

        # ── Rejets (badge "Rejeté") ─────────────────────────────────────────
        rejected_exam_ids, rejected_reasons = self._compute_rejected_exams(partner, exams)

        values = {
            'exams':              exams,
            'active_sessions':    active_sessions,
            'past_attempts':      past_attempts,
            'completed_exam_ids': completed_exam_ids,
            'rejected_exam_ids':  rejected_exam_ids,
            'rejected_reasons':   rejected_reasons,
            'already_done_msg':   bool(already_done),
            'page_name':          'my_exams',
            'pager':              pager,
            'exam_count':         total,
        }
        return request.render('digii_exam_manager.portal_my_exams', values)

    # =========================================================================
    # CANDIDATE PORTAL: waiting room
    # =========================================================================

    @http.route(
        '/my/exam/<int:exam_id>/waiting-room',
        type='http', auth='user', website=True,
    )
    def portal_waiting_room(self, exam_id, **kw):
        partner = request.env.user.partner_id
        survey  = request.env['survey.survey'].sudo().browse(exam_id)

        if not survey.exists() or not survey.is_exam:
            return request.redirect('/my/exams')

        existing_done = request.env['survey.user_input'].sudo().search([
            ('survey_id',  '=', survey.id),
            ('partner_id', '=', partner.id),
            ('state',      '=', 'done'),
        ], limit=1)
        if existing_done:
            return request.redirect('/my/exams?already_done=1')

        ProcSession = request.env['exam.proctoring.session'].sudo()
        session = ProcSession.create_session(survey.id, partner.id)

        values = {
            'exam':      survey,
            'session':   session,
            'partner':   partner,
            'page_name': 'waiting_room',
        }
        return request.render('digii_exam_manager.portal_waiting_room', values)

    # =========================================================================
    # CANDIDATE PORTAL: mode ENREGISTREMENT SEUL (sans salle d'attente)
    # =========================================================================

    @http.route(
        '/my/exam/<int:exam_id>/record-start',
        type='json', auth='user',
    )
    def start_exam_record_only(self, exam_id, **kw):
        """
        Demarre un examen en mode enregistrement seul : la camera est
        activee et enregistree, mais le candidat entre directement sans
        salle d'attente ni autorisation du procteur.
        """
        partner = request.env.user.partner_id
        survey = request.env['survey.survey'].sudo().browse(exam_id)

        if not survey.exists() or not survey.is_exam:
            return {'error': "Examen introuvable."}

        # Ce mode n'est valide que si record_video est actif ET proctoring inactif.
        if not survey.record_video or survey.is_proctored:
            return {'error': "Ce mode n'est pas disponible pour cet examen."}

        # Verifie qu'il n'a pas deja passe l'examen.
        existing_done = request.env['survey.user_input'].sudo().search([
            ('survey_id',  '=', survey.id),
            ('partner_id', '=', partner.id),
            ('state',      '=', 'done'),
        ], limit=1)
        if existing_done:
            return {'error': "Vous avez deja passe cet examen."}

        # Cree la session et demarre directement (sans autorisation).
        ProcSession = request.env['exam.proctoring.session'].sudo()
        session = ProcSession.create_session(survey.id, partner.id)
        session.action_start_exam_record_only()

        # Cree le user_input pour l'examen.
        user_input = request.env['survey.user_input'].sudo().search([
            ('survey_id',  '=', survey.id),
            ('partner_id', '=', partner.id),
            ('state',      '!=', 'done'),
        ], limit=1)
        if not user_input:
            user_input = request.env['survey.user_input'].sudo().create({
                'survey_id':  survey.id,
                'partner_id': partner.id,
                'email':      partner.email,
            })

        session.sudo().write({'user_input_id': user_input.id})
        request.session['exam_proc_session_id'] = session.id

        survey_url = (
            f'/survey/start/{survey.access_token}'
            f'?answer_token={user_input.access_token}'
            f'&proc_session_id={session.id}'
        )
        return {'status': 'ok', 'survey_url': survey_url,
                'session_id': session.id}

    # =========================================================================
    # CANDIDATE PORTAL: examen STANDARD (sans video ni proctoring)
    # =========================================================================

    @http.route(
        '/my/exam/<int:exam_id>/start',
        type='json', auth='user',
    )
    def start_exam_standard(self, exam_id, **kw):
        """
        Demarre un examen standard (ni proctoring, ni enregistrement).
        Cree un user_input et renvoie l'URL complete avec answer_token,
        necessaire pour les examens de certification.
        """
        partner = request.env.user.partner_id
        survey = request.env['survey.survey'].sudo().browse(exam_id)

        if not survey.exists() or not survey.is_exam:
            return {'error': "Examen introuvable."}

        # Verifie qu'il n'a pas deja passe l'examen.
        existing_done = request.env['survey.user_input'].sudo().search([
            ('survey_id',  '=', survey.id),
            ('partner_id', '=', partner.id),
            ('state',      '=', 'done'),
        ], limit=1)
        if existing_done:
            return {'error': "Vous avez deja passe cet examen."}

        # Reutilise ou cree le user_input.
        user_input = request.env['survey.user_input'].sudo().search([
            ('survey_id',  '=', survey.id),
            ('partner_id', '=', partner.id),
            ('state',      '!=', 'done'),
        ], limit=1)
        if not user_input:
            user_input = request.env['survey.user_input'].sudo().create({
                'survey_id':  survey.id,
                'partner_id': partner.id,
                'email':      partner.email,
            })

        survey_url = (
            f'/survey/start/{survey.access_token}'
            f'?answer_token={user_input.access_token}'
        )
        return {'status': 'ok', 'survey_url': survey_url}

    # =========================================================================
    # PROCTOR DASHBOARD
    # =========================================================================

    @http.route(
        '/exam/proctoring/dashboard/<int:survey_id>',
        type='http', auth='user', website=True,
    )
    def proctoring_dashboard(self, survey_id, **kw):
        survey = request.env['survey.survey'].sudo().browse(survey_id)
        if not survey.exists():
            return request.redirect('/web')

        if not request.env.user.has_group('survey.group_survey_manager'):
            return request.redirect('/web')

        sessions = request.env['exam.proctoring.session'].sudo().search([
            ('survey_id', '=', survey_id),
            ('state', 'in', ('waiting', 'authorized', 'in_exam')),
        ], order='create_date asc')

        values = {'exam': survey, 'sessions': sessions}
        return request.render('digii_exam_manager.proctoring_dashboard', values)

    # =========================================================================
    # API: WebRTC signaling
    # =========================================================================

    @http.route('/exam/proctoring/signal/offer',
                type='json', auth='user', methods=['POST'])
    def signal_offer(self, session_id, sdp, **kw):
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}
        session.set_offer(sdp)
        return {'status': 'ok'}

    @http.route('/exam/proctoring/signal/answer',
                type='json', auth='user', methods=['POST'])
    def signal_answer(self, session_id, sdp, **kw):
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}
        session.set_answer(sdp)
        return {'status': 'ok'}

    @http.route('/exam/proctoring/signal/ice',
                type='json', auth='user', methods=['POST'])
    def signal_ice(self, session_id, candidate, source='candidate', **kw):
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}
        session.add_ice_candidate(candidate, source)
        return {'status': 'ok'}

    # =========================================================================
    # API: proctor actions
    # =========================================================================

    @http.route('/exam/proctoring/authorize',
                type='json', auth='user', methods=['POST'])
    def authorize_candidate(self, session_id, **kw):
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}
        session.action_authorize()
        return {'status': 'ok', 'state': 'authorized'}

    @http.route('/exam/proctoring/reject',
                type='json', auth='user', methods=['POST'])
    def reject_candidate(self, session_id, reason='', **kw):
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}
        session.action_reject(reason)
        return {'status': 'ok', 'state': 'rejected'}

    # =========================================================================
    # API: candidate polling
    # =========================================================================

    @http.route('/exam/proctoring/poll',
                type='json', auth='user', methods=['POST'])
    def poll_status(self, session_id, **kw):
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}

        result = {
            'status':     'ok',
            'state':      session.state,
            'answer_sdp': session.answer_sdp or False,
        }
        try:
            all_candidates    = json.loads(session.ice_candidates or '[]')
            proctor_candidates = [c for c in all_candidates if c.get('source') == 'proctor']
            result['ice_candidates'] = proctor_candidates
        except (json.JSONDecodeError, TypeError):
            result['ice_candidates'] = []

        if session.state == 'rejected':
            result['rejection_reason'] = session.rejection_reason or ''

        return result

    # =========================================================================
    # API: active sessions (proctor dashboard)
    # =========================================================================

    @http.route('/exam/proctoring/sessions',
                type='json', auth='user', methods=['POST'])
    def get_active_sessions(self, survey_id, **kw):
        sessions = request.env['exam.proctoring.session'].sudo().search([
            ('survey_id', '=', survey_id),
            ('state', 'in', ('waiting', 'authorized', 'in_exam')),
        ], order='create_date asc')

        result = []
        for s in sessions:
            try:
                ice = json.loads(s.ice_candidates or '[]')
            except (json.JSONDecodeError, TypeError):
                ice = []
            result.append({
                'id':           s.id,
                'partner_name': s.partner_id.name,
                'partner_email': s.partner_id.email or '',
                'state':        s.state,
                'offer_sdp':    s.offer_sdp or False,
                'ice_candidates': ice,
                'create_date':  s.create_date.isoformat() if s.create_date else '',
            })

        return {'status': 'ok', 'sessions': result}

    # =========================================================================
    # API: start exam (candidate)
    # =========================================================================

    @http.route('/exam/proctoring/start-exam',
                type='json', auth='user', methods=['POST'])
    def start_exam(self, session_id, **kw):
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}

        if session.state != 'authorized':
            return {'error': "Vous n'etes pas encore autorise."}

        survey  = session.survey_id
        partner = session.partner_id

        existing_done = request.env['survey.user_input'].sudo().search([
            ('survey_id',  '=', survey.id),
            ('partner_id', '=', partner.id),
            ('state',      '=', 'done'),
        ], limit=1)
        if existing_done:
            return {'error': "Vous avez deja passe cet examen. Une seule tentative est autorisee."}

        session.action_start_exam()

        user_input = request.env['survey.user_input'].sudo().search([
            ('survey_id',  '=', survey.id),
            ('partner_id', '=', partner.id),
            ('state',      '!=', 'done'),
        ], limit=1)

        if not user_input:
            user_input = request.env['survey.user_input'].sudo().create({
                'survey_id':  survey.id,
                'partner_id': partner.id,
                'email':      partner.email,
            })

        session.sudo().write({'user_input_id': user_input.id})
        request.session['exam_proc_session_id'] = session.id

        survey_url = (
            f'/survey/start/{survey.access_token}'
            f'?answer_token={user_input.access_token}'
            f'&proc_session_id={session.id}'
        )
        return {'status': 'ok', 'survey_url': survey_url}

    # =========================================================================
    # API: exam video upload
    # =========================================================================

    @http.route('/exam/proctoring/upload-recording',
                type='http', auth='user', methods=['POST'], csrf=False)
    def upload_recording(self, session_id=None, video_blob=None, **kw):
        if not session_id or not video_blob:
            return request.make_response(
                json.dumps({'error': 'Parametres manquants'}),
                headers=[('Content-Type', 'application/json')], status=400)
        try:
            sid = int(session_id)
        except (TypeError, ValueError):
            return request.make_response(
                json.dumps({'error': 'session_id invalide'}),
                headers=[('Content-Type', 'application/json')], status=400)

        session = request.env['exam.proctoring.session'].sudo().browse(sid)
        if not session.exists():
            return request.make_response(
                json.dumps({'error': 'Session introuvable'}),
                headers=[('Content-Type', 'application/json')], status=404)

        partner = request.env.user.partner_id
        if session.partner_id != partner:
            return request.make_response(
                json.dumps({'error': 'Non autorise'}),
                headers=[('Content-Type', 'application/json')], status=403)

        try:
            video_data = video_blob.read()
        except Exception as e:
            _logger.exception("Erreur lecture upload video: %s", e)
            return request.make_response(
                json.dumps({'error': 'Lecture fichier impossible'}),
                headers=[('Content-Type', 'application/json')], status=500)

        if not video_data:
            return request.make_response(
                json.dumps({'error': 'Fichier vide'}),
                headers=[('Content-Type', 'application/json')], status=400)

        encoded  = base64.b64encode(video_data)
        filename = f'recording_{session.name or session.id}.webm'
        session.sudo().write({'video_recording': encoded, 'video_filename': filename})
        _logger.info("Enregistrement video sauvegarde pour session %s (%d bytes)",
                     session.name, len(video_data))
        return request.make_response(
            json.dumps({'status': 'ok', 'size': len(video_data)}),
            headers=[('Content-Type', 'application/json')], status=200)

    @http.route('/exam/proctoring/recording/<int:session_id>',
                type='http', auth='user', website=False)
    def proctoring_recording_player(self, session_id, **kw):
        """Page lecteur HTML5 pour visionner l'enregistrement local (WebM) en ligne
        plutôt que de le télécharger."""
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists() or not session.video_recording:
            return request.not_found()

        user = request.env.user
        is_staff = user.has_group('survey.group_survey_user')
        is_owner = session.partner_id == user.partner_id
        if not (is_staff or is_owner):
            return request.make_response('Accès refusé', status=403)

        src = ('/web/content/exam.proctoring.session/%s/video_recording'
               '?download=false' % session.id)
        title = session.name or ('Session %s' % session.id)
        html = (
            "<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'/>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
            "<title>Enregistrement — " + title + "</title>"
            "<style>"
            "html,body{margin:0;height:100%;background:#0b0b0b;"
            "font-family:system-ui,sans-serif;}"
            ".wrap{display:flex;flex-direction:column;align-items:center;"
            "justify-content:center;height:100%;gap:14px;padding:16px;box-sizing:border-box;}"
            "h1{color:#eee;font-size:15px;font-weight:600;margin:0;}"
            "video{max-width:96vw;max-height:82vh;border-radius:10px;background:#000;"
            "box-shadow:0 10px 50px rgba(0,0,0,.6);}"
            "a{color:#9ecbff;font-size:13px;text-decoration:none;}"
            "</style></head><body><div class='wrap'>"
            "<h1>&#127909; " + title + "</h1>"
            "<video controls autoplay preload='metadata'>"
            "<source src='" + src + "'/>"
            "Votre navigateur ne supporte pas la lecture vidéo."
            "</video>"
            "<a href='" + src + "&download=true'>&#11015; Télécharger le fichier</a>"
            "</div></body></html>"
        )
        return request.make_response(
            html, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @http.route('/exam/proctoring/lookup-session',
                type='json', auth='user', methods=['POST'])
    def lookup_session(self, proc_session_id=None, **kw):
        if not proc_session_id:
            return {'error': 'session_id manquant'}
        try:
            sid = int(proc_session_id)
        except (TypeError, ValueError):
            return {'error': 'session_id invalide'}

        session = request.env['exam.proctoring.session'].sudo().browse(sid)
        if not session.exists():
            return {'error': 'Session introuvable'}

        partner = request.env.user.partner_id
        if session.partner_id != partner:
            return {'error': 'Non autorise'}

        return {
            'status':       'ok',
            'session_id':   session.id,
            'record_video': session.survey_id.record_video,
            'is_proctored': session.survey_id.is_proctored,
        }

    # =========================================================================
    # API: proctor excludes candidate mid-exam
    # =========================================================================

    @http.route('/exam/proctoring/exclude',
                type='json', auth='user', methods=['POST'])
    def exclude_candidate(self, session_id, reason='', **kw):
        if not request.env.user.has_group('survey.group_survey_manager'):
            return {'error': 'Non autorise'}

        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}

        if session.state not in ('in_exam', 'authorized', 'waiting'):
            return {'error': 'Cette session ne peut plus etre exclue (etat: %s)' % session.state}

        # Toute la logique (clôture user_input, marquage rejeté, strike,
        # notifications) est centralisée dans le modèle.
        session.action_exclude(reason or 'Exclu par le procteur.')
        return {'status': 'ok', 'state': 'completed'}

    # =========================================================================
    # LiveKit tokens
    # =========================================================================

    @http.route('/exam/proctoring/livekit/candidate-token',
                type='json', auth='user', methods=['POST'])
    def livekit_candidate_token(self, session_id, **kw):
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}
        partner = request.env.user.partner_id
        if session.partner_id != partner:
            return {'error': 'Non autorise'}
        LK       = request.env['exam.livekit.config'].sudo()
        room     = LK.room_name_for_session(session)
        identity = f'cand_{partner.id}'
        token    = LK.build_token(
            identity=identity, room=room, name=partner.name or identity,
            can_publish=True, can_subscribe=True)
        return {'status': 'ok', 'url': LK._get_livekit_url(),
                'token': token, 'room': room, 'identity': identity}

    @http.route('/exam/proctoring/livekit/proctor-token',
                type='json', auth='user', methods=['POST'])
    def livekit_proctor_token(self, session_id, **kw):
        if not request.env.user.has_group('survey.group_survey_manager'):
            return {'error': 'Non autorise'}
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}
        LK       = request.env['exam.livekit.config'].sudo()
        room     = LK.room_name_for_session(session)
        identity = f'proc_{request.env.user.id}_{session.id}'
        token    = LK.build_token(
            identity=identity, room=room, name=request.env.user.name,
            can_publish=False, can_subscribe=True)
        return {'status': 'ok', 'url': LK._get_livekit_url(),
                'token': token, 'room': room, 'identity': identity}

    @http.route('/exam/proctoring/test-egress',
                type='json', auth='user', methods=['POST'])
    def test_egress(self, session_id=None, **kw):
        if not request.env.user.has_group('survey.group_survey_manager'):
            return {'error': 'Non autorise'}
        session = request.env['exam.proctoring.session'].sudo().browse(session_id)
        if not session.exists():
            return {'error': 'Session introuvable'}
        import logging
        _log = logging.getLogger(__name__)
        LK     = request.env['exam.livekit.config'].sudo()
        lk_url = LK._livekit_http_url()
        _log.warning('[TEST-EGRESS] LiveKit HTTP URL: %s', lk_url)
        try:
            import requests
            r = requests.get(lk_url, timeout=3)
            _log.warning('[TEST-EGRESS] LiveKit reachable: %s', r.status_code)
        except Exception as e:
            _log.warning('[TEST-EGRESS] LiveKit NOT reachable: %s', e)
            return {'error': f'LiveKit inaccessible: {e}'}
        egress_id = LK.start_egress(session)
        _log.warning('[TEST-EGRESS] egress_id result: %s', egress_id)
        return {'status': 'ok', 'egress_id': egress_id,
                'livekit_url': lk_url, 'room': LK.room_name_for_session(session)}
