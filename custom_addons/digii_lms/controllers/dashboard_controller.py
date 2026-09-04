# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from collections import defaultdict


class DigiiDashboardController(http.Controller):

    @http.route('/digii/dashboard/data', type='jsonrpc', auth='user', methods=['POST'])
    def dashboard_data(self):
        env = request.env
        Channel = env['slide.channel']
        Slide   = env['slide.slide']
        CP      = env['slide.channel.partner']
        Cat     = env['digii.course.category']

        # ── KPIs ─────────────────────────────────────────────────────────────
        all_channels = Channel.search([])
        all_cp       = CP.search([])

        kpi = {
            'total_courses':       len(all_channels),
            'published_courses':   len(all_channels.filtered('is_published')),
            'unpublished_courses': len(all_channels.filtered(lambda c: not c.is_published)),
            'total_slides':        Slide.search_count([('is_category', '=', False)]),
            'published_slides':    Slide.search_count([
                ('is_category', '=', False), ('is_published', '=', True)
            ]),
            'total_learners':      len(all_cp),
            'completed_learners':  len(all_cp.filtered(lambda cp: cp.completion == 100)),
            'total_categories':    Cat.search_count([]),
            'total_views':         int(sum(all_channels.mapped('total_views') or [0])),
        }

        # ── Pie : Cours par catégorie ─────────────────────────────────────────
        courses_by_category = []
        for cat in Cat.search([]):
            count = Channel.search_count([('course_category_id', '=', cat.id)])
            if count:
                courses_by_category.append({'name': cat.name, 'count': count})
        no_cat = Channel.search_count([('course_category_id', '=', False)])
        if no_cat:
            courses_by_category.append({'name': 'Non catégorisé', 'count': no_cat})

        # ── Bar : Leçons par type ─────────────────────────────────────────────
        type_map = {
            'video':        'Vidéo',
            'document':     'PDF/Doc',
            'infographic':  'Infographie',
            'presentation': 'Présentation',
            'article':      'Article',
            'quiz':         'Quiz',
            'url':          'URL',
        }
        slide_types = []
        for stype, label in type_map.items():
            count = Slide.search_count([
                ('slide_type', '=', stype), ('is_category', '=', False)
            ])
            if count:
                slide_types.append({'label': label, 'count': count})

        # ── Doughnut : Difficulté ─────────────────────────────────────────────
        diff_map = {
            'beginner':     'Débutant',
            'intermediate': 'Intermédiaire',
            'advanced':     'Avancé',
            'expert':       'Expert',
        }
        difficulty_data = []
        for key, label in diff_map.items():
            count = Channel.search_count([('custom_difficulty', '=', key)])
            if count:
                difficulty_data.append({'label': label, 'count': count})

        # ── Doughnut : Statut apprenants ──────────────────────────────────────
        bucket = defaultdict(int)
        for cp in all_cp:
            compl    = cp.completion or 0
            m_status = getattr(cp, 'member_status', None)
            if m_status == 'invited':
                bucket['Invité'] += 1
            elif compl == 0:
                bucket['Inscrit'] += 1
            elif compl == 100:
                bucket['Complété'] += 1
            else:
                bucket['En cours'] += 1
        status_data = [{'label': k, 'count': v} for k, v in bucket.items() if v]

        # ── Bar : Cours par langue ────────────────────────────────────────────
        lang_map = {
            'fr': 'Français', 'en': 'Anglais',
            'ar': 'Arabe',    'es': 'Espagnol',
        }
        language_data = []
        for key, label in lang_map.items():
            count = Channel.search_count([('custom_language', '=', key)])
            if count:
                language_data.append({'label': label, 'count': count})

        # ── Horizontal Bar : Top 5 cours ──────────────────────────────────────
        top_channels = Channel.search([], order='total_views desc', limit=5)
        top_courses = []
        for ch in top_channels:
            learners  = CP.search_count([('channel_id', '=', ch.id)])
            completed = CP.search_count([
                ('channel_id', '=', ch.id), ('completion', '=', 100)
            ])
            name = ch.name[:35] + ('…' if len(ch.name) > 35 else '')
            top_courses.append({'name': name, 'learners': learners, 'completed': completed})

        return {
            'kpi':                 kpi,
            'courses_by_category': courses_by_category,
            'slide_types':         slide_types,
            'difficulty_data':     difficulty_data,
            'status_data':         status_data,
            'language_data':       language_data,
            'top_courses':         top_courses,
        }
