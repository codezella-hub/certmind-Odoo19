# -*- coding: utf-8 -*-
{
    'name': 'Digii LMS - Agent IA Étudiant',
    'version': '1.0',
    'summary': "Compagnon d'apprentissage IA pour les étudiants (tuteur, quiz, "
               "résumé, révision) sur le portail eLearning.",
    'description': """
Agent IA côté ÉTUDIANT pour le portail LMS.

Fonctionnalités (développées par étapes) :
  1. Tuteur de cours   : chat pédagogique sur le contenu d'une leçon
  2. Quiz de révision  : questions auto-générées + correction expliquée
  3. Résumé de leçon   : synthèse exportable en PDF soigné
  4. Plan de révision  : planning personnalisé avant un examen
  5. Historique enrichi : conversations par cours, recherche, favoris...

Service IA dédié au LMS (digii.lms.ai.service), avec sa propre clé et son
propre modèle, indépendants de l'agent examen.
Philosophie : l'IA assiste et explique, l'étudiant pilote son apprentissage.
    """,
    'author': 'Digii',
    'category': 'eLearning',
    'depends': [
        'digii_lms',
        'website_slides',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/lms_ai_groups.xml',
        'data/lms_ai_params.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            # Le tuteur et le quiz vivent sur le portail (site web).
            'digii_lms_ai_agent/static/src/scss/lms_ai_tutor.scss',
            'digii_lms_ai_agent/static/src/js/lms_ai_tutor.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'post_init_hook': '_lms_ai_fix_model',
}
