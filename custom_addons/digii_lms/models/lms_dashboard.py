# -*- coding: utf-8 -*-
from odoo import models, fields, api
from collections import defaultdict


class DigiiLmsDashboard(models.TransientModel):
    """
    Modèle transitoire utilisé uniquement comme source de données
    pour le dashboard OWL. Aucun enregistrement n'est persisté.

    Accès via call_kw :
        - search_read  → retourne un seul enregistrement avec les KPIs
        - get_dashboard_data → retourne tous les datasets pour Chart.js
    """
    _name = 'digii.lms.dashboard'
    _description = 'Dashboard Smart LMS'

    # ── Champs KPI ────────────────────────────────────────────────────────────
    total_courses       = fields.Integer(string='Total Cours',       compute='_compute_all', store=False)
    published_courses   = fields.Integer(string='Cours Publiés',     compute='_compute_all', store=False)
    unpublished_courses = fields.Integer(string='Cours Non Publiés', compute='_compute_all', store=False)
    total_slides        = fields.Integer(string='Total Leçons',      compute='_compute_all', store=False)
    published_slides    = fields.Integer(string='Leçons Publiées',   compute='_compute_all', store=False)
    total_learners      = fields.Integer(string='Total Apprenants',  compute='_compute_all', store=False)
    completed_learners  = fields.Integer(string='Apprenants Complétés', compute='_compute_all', store=False)
    total_categories    = fields.Integer(string='Total Catégories',  compute='_compute_all', store=False)
    total_views         = fields.Integer(string='Total Vues',        compute='_compute_all', store=False)

    # ── Compute global ────────────────────────────────────────────────────────
    @api.depends()
    def _compute_all(self):
        """
        Pour les TransientModel, les computes ne sont appelés que sur des
        enregistrements existants.  search_read crée d'abord un enregistrement
        fictif ; on calcule ici les stats live depuis la BD.
        """
        env = self.env
        Channel = env['slide.channel']
        Slide   = env['slide.slide']
        CP      = env['slide.channel.partner']
        Cat     = env['digii.course.category']

        # Calcul une seule fois pour tous les records du batch
        stats = {
            'total_courses':       Channel.search_count([]),
            'published_courses':   Channel.search_count([('is_published', '=', True)]),
            'unpublished_courses': Channel.search_count([('is_published', '=', False)]),
            'total_slides':        Slide.search_count([('is_category', '=', False)]),
            'published_slides':    Slide.search_count([
                ('is_category', '=', False), ('is_published', '=', True)
            ]),
            'total_learners':      CP.search_count([]),
            'completed_learners':  CP.search_count([('completion', '=', 100)]),
            'total_categories':    Cat.search_count([]),
            'total_views':         sum(Channel.search([]).mapped('total_views')),
        }
        for rec in self:
            for k, v in stats.items():
                setattr(rec, k, v)

    # ── Override search_read ──────────────────────────────────────────────────
    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None,
                    order=None, **kwargs):
        """
        On crée un enregistrement virtuel en mémoire, on calcule ses champs,
        on retourne la liste comme si c'était un vrai search_read.
        """
        # Créer un enregistrement temporaire (auto-supprimé après la transaction)
        record = self.create({})
        self.env.cr.execute("SAVEPOINT digii_dashboard_sp")

        # Forcer le recalcul
        record._compute_all()

        # Construire le résultat
        all_fields = [
            'total_courses', 'published_courses', 'unpublished_courses',
            'total_slides', 'published_slides',
            'total_learners', 'completed_learners',
            'total_categories', 'total_views',
        ]
        read_fields = fields if fields else all_fields
        result = record.read(read_fields)

        # Rollback pour ne pas persister le transient inutilement
        try:
            self.env.cr.execute("ROLLBACK TO SAVEPOINT digii_dashboard_sp")
        except Exception:
            pass

        return result[:1]

    # ── Méthode principale des données graphiques ─────────────────────────────
    @api.model
    def get_dashboard_data(self):
        env = self.env
        Channel = env['slide.channel']
        Slide   = env['slide.slide']
        CP      = env['slide.channel.partner']
        Cat     = env['digii.course.category']

        # ── 1. Courses by category (Pie) ─────────────────────────────────────
        courses_by_category = []
        for cat in Cat.search([]):
            count = Channel.search_count([('course_category_id', '=', cat.id)])
            if count > 0:
                courses_by_category.append({'name': cat.name, 'count': count})
        no_cat = Channel.search_count([('course_category_id', '=', False)])
        if no_cat:
            courses_by_category.append({'name': 'Non catégorisé', 'count': no_cat})

        # ── 2. Slides by type (Bar) ───────────────────────────────────────────
        type_labels = {
            'video':        'Vidéo',
            'document':     'PDF/Doc',
            'infographic':  'Infographie',
            'presentation': 'Présentation',
            'article':      'Article',
            'quiz':         'Quiz',
            'url':          'URL',
        }
        slide_types = []
        for stype, label in type_labels.items():
            count = Slide.search_count([
                ('slide_type', '=', stype),
                ('is_category', '=', False),
            ])
            if count > 0:
                slide_types.append({'label': label, 'count': count})

        # ── 3. Difficulty (Doughnut) ──────────────────────────────────────────
        diff_labels = {
            'beginner':     'Débutant',
            'intermediate': 'Intermédiaire',
            'advanced':     'Avancé',
            'expert':       'Expert',
        }
        difficulty_data = []
        for key, label in diff_labels.items():
            count = Channel.search_count([('custom_difficulty', '=', key)])
            if count > 0:
                difficulty_data.append({'label': label, 'count': count})

        # ── 4. Learner status (Doughnut) ──────────────────────────────────────
        all_cp = CP.search([])
        status_bucket = defaultdict(int)
        for cp in all_cp:
            compl = cp.completion or 0
            # member_status existe sur slide.channel.partner en Odoo 17+
            m_status = getattr(cp, 'member_status', None)
            if m_status == 'invited':
                status_bucket['Invité'] += 1
            elif compl == 0:
                status_bucket['Inscrit'] += 1
            elif compl == 100:
                status_bucket['Complété'] += 1
            else:
                status_bucket['En cours'] += 1
        status_data = [{'label': k, 'count': v} for k, v in status_bucket.items() if v]

        # ── 5. Courses by language (Bar) ─────────────────────────────────────
        lang_labels = {
            'fr': 'Français',
            'en': 'Anglais',
            'ar': 'Arabe',
            'es': 'Espagnol',
        }
        language_data = []
        for key, label in lang_labels.items():
            count = Channel.search_count([('custom_language', '=', key)])
            if count > 0:
                language_data.append({'label': label, 'count': count})

        # ── 6. Top 5 courses (Horizontal Bar) ────────────────────────────────
        top_channels = Channel.search([], order='total_views desc', limit=5)
        top_courses = []
        for ch in top_channels:
            learners  = CP.search_count([('channel_id', '=', ch.id)])
            completed = CP.search_count([('channel_id', '=', ch.id), ('completion', '=', 100)])
            top_courses.append({
                'name':      ch.name[:35] + ('…' if len(ch.name) > 35 else ''),
                'learners':  learners,
                'completed': completed,
            })

        return {
            'courses_by_category': courses_by_category,
            'slide_types':         slide_types,
            'difficulty_data':     difficulty_data,
            'status_data':         status_data,
            'language_data':       language_data,
            'top_courses':         top_courses,
        }
