# -*- coding: utf-8 -*-
{
    'name': 'Digii Exam AI Agent',
    'version': '19.0.1.0.0',
    'category': 'Education',
    'summary': "Agent IA pour la generation de questions et l'assistance a la creation d'examens",
    'description': """
Agent IA conversationnel pour la banque de questions et la generation d'examens
================================================================================

Assistant IA integre au back-office Odoo qui aide a :

* Generer des questions a partir d'un cours, d'un texte libre ou d'un sujet.
* Proposer des distracteurs plausibles pour une question existante.
* Co-piloter la creation des regles de generation d'examen (exam.generation.rule)
  avec verification de faisabilite sur le pool reel de la banque.
* Valider les questions proposees par l'IA avant leur entree en banque
  (workflow propose -> approuve / rejete / edite).

L'IA propose, l'administrateur valide. Aucune question generee n'entre
directement dans la banque officielle.

Backend : API Groq (compatible OpenAI SDK), modele configurable.
""",
    'author': 'Ben Slimen Louay',
    'depends': ['digii_lms', 'digii_exam_manager'],
    'external_dependencies': {'python': ['openai']},
    'data': [
        'security/ai_agent_groups.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/survey_question_views.xml',
        'views/ai_generation_session_views.xml',
        'views/survey_survey_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'digii_exam_ai_agent/static/src/scss/ai_agent_panel.scss',
            'digii_exam_ai_agent/static/src/xml/ai_agent_panel.xml',
            'digii_exam_ai_agent/static/src/js/markdown.js',
            'digii_exam_ai_agent/static/src/js/components/ai_typing_indicator.js',
            'digii_exam_ai_agent/static/src/js/components/ai_message.js',
            'digii_exam_ai_agent/static/src/js/components/ai_question_card.js',
            'digii_exam_ai_agent/static/src/js/components/ai_rule_card.js',
            'digii_exam_ai_agent/static/src/js/ai_agent_panel.js',
            'digii_exam_ai_agent/static/src/js/ai_agent_service.js',
            'digii_exam_ai_agent/static/src/js/ai_agent_systray.js',
            'digii_exam_ai_agent/static/src/js/ai_survey_button.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
