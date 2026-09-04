# -*- coding: utf-8 -*-
import math
from urllib.parse import urlencode
from odoo import http
from odoo.http import request
from odoo.addons.website_slides.controllers.main import WebsiteSlides

DIFF_LABELS = {
    'beginner': 'Débutant',
    'intermediate': 'Intermédiaire',
    'advanced': 'Avancé',
    'expert': 'Expert',
}
LANG_LABELS = {
    'fr': 'Français',
    'en': 'Anglais',
    'ar': 'Arabe',
    'es': 'Espagnol',
}
PER_PAGE = 8


class DigiiSlidesPortal(WebsiteSlides):
    """Page /slides : cours de la (les) classe(s) de l'utilisateur connecté,
    avec recherche, filtres dynamiques (catégorie, niveau, langue, tag),
    bascule cartes / liste et pagination (8 par page)."""

    @http.route()
    def slides_channel(self, slide_category=None, slug_tags=None, my=0, page=1, **post):
        user = request.env.user
        is_public = user._is_public()

        classes = request.env['digii.class']
        base_courses = request.env['slide.channel']
        if not is_public:
            classes = request.env['digii.class'].sudo().search([
                ('student_ids', 'in', user.id),
                ('active', '=', True),
            ])
            base_courses = classes.mapped('course_ids')

        # ── Options de filtres (dynamiques, calculées sur l'ensemble de base) ──
        cat_records = base_courses.mapped('course_category_id')
        categories = [{'id': c.id, 'name': c.name} for c in cat_records]
        tag_records = base_courses.mapped('tag_ids')
        tags = [{'id': t.id, 'name': t.name} for t in tag_records]
        present_levels = set(base_courses.mapped('custom_difficulty'))
        levels = [{'code': k, 'name': v} for k, v in DIFF_LABELS.items()
                  if k in present_levels]
        present_langs = set(base_courses.mapped('custom_language'))
        langs = [{'code': k, 'name': v} for k, v in LANG_LABELS.items()
                 if k in present_langs]

        # ── Valeurs de filtres reçues ──
        search = (post.get('search') or '').strip()
        sel_category = (post.get('category') or '').strip()
        sel_level = (post.get('level') or '').strip()
        sel_lang = (post.get('lang') or '').strip()
        sel_tag = (post.get('tag') or '').strip()
        view = (post.get('view') or 'grid').strip()
        if view not in ('grid', 'list'):
            view = 'grid'

        # ── Application des filtres (en Python sur le recordset) ──
        courses = base_courses
        if search:
            s = search.lower()
            courses = courses.filtered(
                lambda c: s in (c.name or '').lower()
                or s in (c.description or '').lower()
            )
        if sel_category.isdigit():
            cid = int(sel_category)
            courses = courses.filtered(
                lambda c: c.course_category_id.id == cid)
        if sel_level:
            courses = courses.filtered(
                lambda c: c.custom_difficulty == sel_level)
        if sel_lang:
            courses = courses.filtered(
                lambda c: c.custom_language == sel_lang)
        if sel_tag.isdigit():
            tid = int(sel_tag)
            courses = courses.filtered(lambda c: tid in c.tag_ids.ids)

        # ── Pagination (8 par page) ──
        total = len(courses)
        num_pages = max(1, math.ceil(total / PER_PAGE))
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = 1
        page = max(1, min(page, num_pages))
        offset = (page - 1) * PER_PAGE
        courses_page = courses[offset:offset + PER_PAGE]

        # ── Progression réelle de l'utilisateur ──
        completion_map = {}
        if not is_public and courses_page:
            cps = request.env['slide.channel.partner'].sudo().search([
                ('channel_id', 'in', courses_page.ids),
                ('partner_id', '=', user.partner_id.id),
            ])
            completion_map = {
                cp.channel_id.id: int(cp.completion or 0) for cp in cps
            }

        # ── Query string (sans 'page') pour pagination & bascule de vue ──
        current = {
            'search': search, 'category': sel_category, 'level': sel_level,
            'lang': sel_lang, 'tag': sel_tag, 'view': view,
        }
        qs_no_page = urlencode({k: v for k, v in current.items() if v})
        qs_no_view = urlencode({k: v for k, v in current.items()
                                if v and k != 'view'})

        has_filters = bool(search or sel_category or sel_level
                           or sel_lang or sel_tag)

        values = {
            'user': user,
            'is_public': is_public,
            'classes': classes,
            'courses': courses_page,
            'courses_count': total,
            'completion_map': completion_map,
            # filtres
            'categories': categories,
            'tags': tags,
            'levels': levels,
            'langs': langs,
            'search': search,
            'sel_category': sel_category,
            'sel_level': sel_level,
            'sel_lang': sel_lang,
            'sel_tag': sel_tag,
            'view': view,
            'has_filters': has_filters,
            # pagination
            'page': page,
            'num_pages': num_pages,
            'page_range': list(range(1, num_pages + 1)),
            'qs_no_page': qs_no_page,
            'qs_no_view': qs_no_view,
        }
        return request.render('digii_lms.slides_class_page', values)
