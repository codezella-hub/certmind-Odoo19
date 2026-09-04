# -*- coding: utf-8 -*-
"""
Surcharge du portail "/my/exams" (digii_exam_manager) pour ajouter :
    - une recherche texte sur le titre de l'examen,
    - un filtre par cours (course_id),
    - un filtre par tag (exam_tag_ids).

On hérite de ProctoringController et on réécrit la route portal_my_exams.
La logique sessions actives / tentatives passées est conservée à l'identique.
"""
from odoo import http
from odoo.http import request

from odoo.addons.digii_exam_manager.controllers.proctoring import (
    ProctoringController,
    EXAMS_PER_PAGE,
)


class LmsExamPortal(ProctoringController):

    @http.route(
        ['/my/exams', '/my/exams/page/<int:page>'],
        type='http', auth='user', website=True,
    )
    def portal_my_exams(self, page=1, already_done=None,
                        search=None, course_id=None, tag_id=None, category_id=None, **kw):
        partner = request.env.user.partner_id
        Survey = request.env['survey.survey'].sudo()

        # ── Construction du domaine de recherche/filtre ─────────────────────
        domain = [('is_exam', '=', True)]

        search = (search or '').strip()
        if search:
            domain.append(('title', 'ilike', search))

        # Conversion sûre des paramètres GET (str -> int)
        def _to_int(val):
            try:
                return int(val)
            except (TypeError, ValueError):
                return False

        course_id = _to_int(course_id)
        tag_id = _to_int(tag_id)
        category_id = _to_int(category_id)

        if course_id:
            domain.append(('course_id', '=', course_id))
        if tag_id:
            domain.append(('exam_tag_ids', 'in', tag_id))
        if category_id:
            domain.append(('exam_category_ids', 'in', category_id))

        total = Survey.search_count(domain)

        # ── Options des filtres (uniquement cours/tags réellement utilisés) ──
        all_exams = Survey.search([('is_exam', '=', True)])
        filter_courses = all_exams.mapped('course_id').sorted('name')
        filter_tags = all_exams.mapped('exam_tag_ids').sorted('name')
        filter_categories = all_exams.mapped('exam_category_ids').sorted('name')

        # ── Conserver les filtres dans les liens de pagination ──────────────
        url_args = {}
        if search:
            url_args['search'] = search
        if course_id:
            url_args['course_id'] = course_id
        if tag_id:
            url_args['tag_id'] = tag_id
        if category_id:
            url_args['category_id'] = category_id

        pager = request.website.pager(
            url='/my/exams',
            total=total,
            page=page,
            step=EXAMS_PER_PAGE,
            url_args=url_args,
        )

        exams = Survey.search(
            domain,
            order='create_date desc',
            limit=EXAMS_PER_PAGE,
            offset=pager['offset'],
        )

        # ── Sessions actives ────────────────────────────────────────────────
        ProcSession = request.env['exam.proctoring.session'].sudo()
        active_sessions = {}
        for exam in exams:
            session = ProcSession.search([
                ('survey_id', '=', exam.id),
                ('partner_id', '=', partner.id),
                ('state', 'in', ('waiting', 'authorized', 'in_exam')),
            ], limit=1)
            if session:
                active_sessions[exam.id] = session

        # ── Tentatives passées ───────────────────────────────────────────────
        UserInput = request.env['survey.user_input'].sudo()
        past_attempts = {}
        completed_exam_ids = set()
        for exam in exams:
            attempts = UserInput.search([
                ('survey_id', '=', exam.id),
                ('partner_id', '=', partner.id),
                ('state', '=', 'done'),
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
            # ── Données pour la barre de recherche/filtres ──
            'search':             search,
            'active_course_id':   course_id,
            'active_tag_id':      tag_id,
            'active_category_id': category_id,
            'filter_courses':     filter_courses,
            'filter_tags':        filter_tags,
            'filter_categories':  filter_categories,
        }
        return request.render('digii_exam_manager.portal_my_exams', values)
