# -*- coding: utf-8 -*-
"""
Controller JSON du Dashboard Examens.

Renvoie en un seul appel :
    - kpi   : les indicateurs clés (cartes du haut)
    - les datasets pour les graphiques Chart.js

Même approche que le dashboard LMS (digii/dashboard/data) : un endpoint
HTTP type='json' appelé par le composant OWL.
"""
from collections import defaultdict

from odoo import http
from odoo.http import request


class DigiiExamDashboardController(http.Controller):

    @http.route('/digii/exam/dashboard/data', type='jsonrpc', auth='user', methods=['POST'])
    def exam_dashboard_data(self):
        env = request.env
        Survey      = env['survey.survey']
        UserInput   = env['survey.user_input']
        Certificate = env['exam.certificate']
        ProcSession = env['exam.proctoring.session']
        Question    = env['survey.question']

        # ── Ensemble des examens ─────────────────────────────────────────────
        exams = Survey.search([('is_exam', '=', True)])
        exam_ids = exams.ids

        proctored = exams.filtered('is_proctored')
        certified = exams.filtered('is_certification')

        # ── Tentatives terminées (done) sur des examens ──────────────────────
        done_attempts = UserInput.search([
            ('survey_id', 'in', exam_ids),
            ('state', '=', 'done'),
        ]) if exam_ids else UserInput.browse()

        in_progress = UserInput.search_count([
            ('survey_id', 'in', exam_ids),
            ('state', '=', 'in_progress'),
        ]) if exam_ids else 0

        passed = done_attempts.filtered('scoring_success')
        nb_done = len(done_attempts)
        nb_passed = len(passed)
        pass_rate = round((nb_passed / nb_done) * 100, 1) if nb_done else 0.0

        scores = done_attempts.mapped('scoring_percentage') or []
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0

        # ── Certificats ───────────────────────────────────────────────────────
        cert_approved = Certificate.search_count([('state', '=', 'approved')])
        cert_pending  = Certificate.search_count([('state', '=', 'pending')])
        cert_rejected = Certificate.search_count([('state', '=', 'rejected')])

        # ── Sessions proctoring ─────────────────────────────────────────────
        all_sessions = ProcSession.search([])
        sessions_with_video = len(all_sessions.filtered('has_video_recording'))

        # ── Banque de questions ──────────────────────────────────────────────
        bank_questions = Question.search_count([
            ('is_bank_question', '=', True),
            ('is_page', '=', False),
        ])

        kpi = {
            'total_exams':         len(exams),
            'proctored_exams':     len(proctored),
            'certified_exams':     len(certified),
            'total_attempts':      nb_done,
            'in_progress':         in_progress,
            'passed_attempts':     nb_passed,
            'pass_rate':           pass_rate,
            'avg_score':           avg_score,
            'cert_approved':       cert_approved,
            'cert_pending':        cert_pending,
            'sessions_total':      len(all_sessions),
            'sessions_with_video': sessions_with_video,
            'bank_questions':      bank_questions,
        }

        # ── Doughnut : Examens surveillés vs standards ───────────────────────
        nb_proctored = len(proctored)
        nb_standard = len(exams) - nb_proctored
        exam_type_data = []
        if nb_proctored:
            exam_type_data.append({'label': 'Surveillés', 'count': nb_proctored})
        if nb_standard:
            exam_type_data.append({'label': 'Standards', 'count': nb_standard})

        # ── Doughnut : Résultats des tentatives ──────────────────────────────
        results_data = []
        if nb_passed:
            results_data.append({'label': 'Réussi', 'count': nb_passed})
        if nb_done - nb_passed:
            results_data.append({'label': 'Échoué', 'count': nb_done - nb_passed})

        # ── Doughnut : Certificats par statut ────────────────────────────────
        cert_status_data = []
        for label, val in (('Approuvé', cert_approved),
                           ('En attente', cert_pending),
                           ('Rejeté', cert_rejected)):
            if val:
                cert_status_data.append({'label': label, 'count': val})

        # ── Doughnut : Sessions proctoring par statut ────────────────────────
        state_labels = {
            'waiting':    'En attente',
            'authorized': 'Autorisé',
            'rejected':   'Rejeté',
            'in_exam':    'En examen',
            'completed':  'Terminé',
            'expired':    'Expiré',
        }
        sess_bucket = defaultdict(int)
        for s in all_sessions:
            sess_bucket[s.state] += 1
        session_status_data = [
            {'label': state_labels.get(k, k), 'count': v}
            for k, v in sess_bucket.items() if v
        ]

        # ── Bar : Top examens par nombre de tentatives ───────────────────────
        attempts_by_exam = defaultdict(int)
        for a in done_attempts:
            attempts_by_exam[a.survey_id.id] += 1
        top_attempts = sorted(
            attempts_by_exam.items(), key=lambda kv: kv[1], reverse=True
        )[:5]
        top_attempts_data = []
        for sid, cnt in top_attempts:
            survey = Survey.browse(sid)
            name = (survey.title or '')[:32] + ('…' if len(survey.title or '') > 32 else '')
            top_attempts_data.append({'name': name, 'count': cnt})

        # ── Bar horizontal : Score moyen par examen (top 5) ──────────────────
        score_by_exam = defaultdict(list)
        for a in done_attempts:
            score_by_exam[a.survey_id.id].append(a.scoring_percentage or 0.0)
        avg_by_exam = []
        for sid, vals in score_by_exam.items():
            survey = Survey.browse(sid)
            name = (survey.title or '')[:32] + ('…' if len(survey.title or '') > 32 else '')
            avg_by_exam.append({
                'name': name,
                'avg': round(sum(vals) / len(vals), 1) if vals else 0.0,
            })
        avg_by_exam = sorted(avg_by_exam, key=lambda x: x['avg'], reverse=True)[:5]

        return {
            'kpi':                 kpi,
            'exam_type_data':      exam_type_data,
            'results_data':        results_data,
            'cert_status_data':    cert_status_data,
            'session_status_data': session_status_data,
            'top_attempts_data':   top_attempts_data,
            'avg_by_exam':         avg_by_exam,
        }
