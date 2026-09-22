# -*- coding: utf-8 -*-
{
    'name': 'Digii Exam Manager',
    'version': '19.0.6.0.0',
    'summary': 'Digii - Banque de questions avec sous-categories, examens, certification, proctoring LiveKit, panneau lateral - v6.0: hierarchie 2 niveaux pour categorisation fine + design moderne arrondi des boutons natifs',
    'category': 'Education',
    'depends': ['survey', 'mail', 'portal', 'website', 'bus'],
    'external_dependencies': {
        'python': ['jwt', 'requests'],
    },
    'data': [
        # Security
        'security/ir.model.access.csv',
        # Data
        'data/mail_template_data.xml',
        'data/livekit_config_data.xml',
        'data/website_menu_data.xml',
        'data/proctoring_ai_cron.xml',
        # Reports
        'report/exam_certificate_report.xml',
        'report/exam_certificate_report_action.xml',
        # Views
        'views/exam_category_views.xml',
        'views/exam_certificate_template_views.xml',
        'views/exam_certificate_views.xml',
        'views/survey_question_views.xml',
        'views/exam_generation_rule_views.xml',
        'views/exam_preview_wizard_views.xml',
        'wizard/exam_question_import_views.xml',
        'views/survey_survey_views.xml',
        'views/survey_survey_views_cert.xml',
        # Proctoring views
        'views/exam_proctoring_session_views.xml',
        'views/survey_survey_proctoring_views.xml',
        # Strikes / sanctions + rejet examen
        'views/exam_strike_views.xml',
        'views/survey_user_input_rejected_views.xml',
        # Menu (must come after all actions)
        'views/menu.xml',
        # Wizard
        'wizard/exam_certificate_reject_wizard_views.xml',
        # Portal
        'views/portal_certificate_templates.xml',
        'views/portal_exam_templates.xml',
        'views/portal_waiting_room_templates.xml',
        # Proctoring dashboard
        'views/proctoring_dashboard_templates.xml',
        # Survey override : redirect + hide retry + inject block-nav / record JS
        'views/survey_done_hide_retry.xml',
        'views/exam_survey_fill_inject.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'digii_exam_manager/static/src/js/ai_progress_widget.js',
            'digii_exam_manager/static/src/xml/ai_progress_widget.xml',
        ],
        'web.assets_frontend': [
            'digii_exam_manager/static/src/css/exam_portal.css',
            'digii_exam_manager/static/src/js/exam_record_only.js',
        ],
        # Le patch de l'interaction native SurveyForm doit etre charge dans
        # LE MEME bundle que survey_form.js (survey.survey_assets), qui n'est
        # servi que sur les pages de survey. Cela garantit que l'import
        # '@survey/interactions/survey_form' est resolu et que le patch
        # s'applique avant l'instanciation de l'interaction.
        'survey.survey_assets': [
            'digii_exam_manager/static/src/js/exam_survey_jump.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
