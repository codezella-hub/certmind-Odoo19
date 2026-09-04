# -*- coding: utf-8 -*-
{
    'name': 'Digii Proctoring IA',
    'version': '1.0',
    'summary': "Analyse de triche par IA integree a Odoo (sans microservice externe)",
    'description': """
Analyse de proctoring directement dans Odoo.

Ce module porte le pipeline d'analyse (MediaPipe, YOLOv8, Silero VAD) qui
tournait auparavant dans un microservice FastAPI separe. L'analyse s'execute
en arriere-plan via un CRON pour ne jamais bloquer l'interface Odoo.

Dependances Python (a installer dans l'environnement Odoo) :
  opencv-python, mediapipe, ultralytics, torch, numpy, reportlab
Optionnel (audio) : silero-vad / torchaudio
Optionnel (interpretation LLM) : requests + cle Groq
    """,
    'author': 'Digii',
    'category': 'Education',
    'depends': ['digii_exam_manager'],
    'data': [
        'data/proctoring_ai_params.xml',
        'data/proctoring_ai_cron.xml',
    ],
    # Seules les dépendances LÉGÈRES sont déclarées ici.
    #
    # Odoo importe chaque librairie listée pour vérifier sa présence au
    # moment de l'installation. Importer torch, mediapipe et ultralytics
    # simultanément dans le processus Odoo provoque un crash natif
    # (conflits de bibliothèques C : protobuf, OpenCV, runtime CUDA).
    #
    # Ces trois librairies sont donc importées tardivement, uniquement
    # quand une analyse démarre (voir _check_ai_libs plus bas). Le module
    # s'installe ainsi sans risque, et l'absence d'une librairie lourde
    # est signalée par un message clair au lancement de l'analyse.
    'external_dependencies': {
        'python': ['cv2', 'numpy', 'pydantic', 'reportlab'],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
