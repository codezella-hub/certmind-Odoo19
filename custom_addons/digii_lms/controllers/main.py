# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class LmsWebsite(http.Controller):

    @http.route('/', auth='public', website=True)
    def lms_home(self, **kwargs):
        env = request.env
        user = env.user
        Channel = env['slide.channel'].sudo()
        Slide = env['slide.slide'].sudo()
        Category = env['digii.course.category'].sudo()
        CP = env['slide.channel.partner'].sudo()

        # ── Cours de la CLASSE de l'utilisateur connecté ──
        my_courses = Channel.browse()
        completion_map = {}
        if not user._is_public():
            classes = env['digii.class'].sudo().search([
                ('student_ids', 'in', user.id),
                ('active', '=', True),
            ])
            my_courses = classes.mapped('course_ids')[:6]
            if my_courses:
                cps = CP.search([
                    ('channel_id', 'in', my_courses.ids),
                    ('partner_id', '=', user.partner_id.id),
                ])
                completion_map = {
                    cp.channel_id.id: int(cp.completion or 0) for cp in cps
                }

        # ── Catégories ayant au moins un cours ──
        categories = Category.search(
            [('channel_count', '>', 0)], order='sequence, name', limit=6
        )

        # ── Statistiques réelles (dynamiques) ──
        courses_count = Channel.search_count([('is_published', '=', True)])
        lessons_count = Slide.search_count([
            ('is_category', '=', False), ('is_published', '=', True)
        ])
        categories_count = Category.search_count([('channel_count', '>', 0)])
        learners_count = len(set(CP.search([]).mapped('partner_id').ids))

        values = {
            'user': user,
            'is_public': user._is_public(),
            'my_courses': my_courses,
            'completion_map': completion_map,
            'categories': categories,
            'stat_courses': courses_count,
            'stat_lessons': lessons_count,
            'stat_categories': categories_count,
            'stat_learners': learners_count,
        }
        return request.render('digii_lms.lms_home_page', values)
