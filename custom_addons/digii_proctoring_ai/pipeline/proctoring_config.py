# -*- coding: utf-8 -*-
"""
config.py — Configuration centralisee.

Tous les seuils de detection et parametres techniques vivent ici, PAS
disperses dans le code. On peut les surcharger par variables
d'environnement sans toucher au code (bonne pratique 12-factor).

Les seuils de detection sont regroupes pour qu'un non-dev (ou toi, dans
6 mois) puisse les ajuster sans lire tout le pipeline.
"""
import os

# Charge le fichier .env s'il existe, AVANT toute lecture de os.environ.
# python-dotenv est optionnel : si absent, on continue sans (les
# variables d'environnement systeme restent utilisables).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class Settings:
    """Parametres du service. Surcharge possible via os.environ."""

    # ---- API ----
    APP_NAME: str = "Proctoring AI Service"
    APP_VERSION: str = "1.0.0"

    # ---- Stockage ----
    # Dossier ou on ecrit les uploads temporaires et les captures de frames.
    UPLOAD_DIR: str = os.environ.get("PROCTOR_UPLOAD_DIR", "storage/uploads")
    FRAMES_DIR: str = os.environ.get("PROCTOR_FRAMES_DIR", "storage/frames")
    REPORTS_DIR: str = os.environ.get("PROCTOR_REPORTS_DIR", "storage/reports")

    # ---- Extraction video ----
    # Nombre de frames analysees par seconde de video (1 = economique).
    FRAMES_PER_SECOND: float = float(os.environ.get("PROCTOR_FPS", "1.0"))

    # ---- Seuils GAZE (regard) en degres ----
    YAW_THRESHOLD_DEG: float = 30.0    # au-dela = regard hors ecran (gauche/droite)
    PITCH_THRESHOLD_DEG: float = 20.0  # au-dela = regard vers le bas
    GAZE_MIN_DURATION_SEC: float = 3.0 # duree mini pour declencher l'alerte

    # ---- Seuils YOLO (objets) ----
    YOLO_CONFIDENCE: float = 0.40      # confiance mini pour valider une detection
    YOLO_MODEL: str = os.environ.get("PROCTOR_YOLO_MODEL", "yolov8n.pt")

    # ---- Seuils AUDIO (Silero VAD) ----
    VOICE_CONFIDENCE: float = 0.50     # confiance mini "c'est de la voix"
    VOICE_MIN_TOTAL_SEC: float = 5.0   # voix cumulee mini pour signaler
    AUDIO_SAMPLE_RATE: int = 16000     # Silero attend du 16kHz mono

    # ---- Seuils COMPORTEMENT ----
    HEAD_VARIANCE_THRESHOLD: float = 15.0  # variance angles = agitation

    # ---- LLM (Groq) pour l'interpretation du resultat ----
    # La cle API ne doit JAMAIS etre en dur : passe-la par variable
    # d'environnement GROQ_API_KEY.
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_BASE_URL: str = os.environ.get(
        "GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    GROQ_TEMPERATURE: float = 0.3   # bas = factuel, peu creatif
    GROQ_TIMEOUT: int = 30
    # Si True et pas de cle, l'interpretation est ignoree sans planter.
    LLM_ENABLED: bool = os.environ.get("PROCTOR_LLM_ENABLED", "1") == "1"

    # ---- Ponderation du score (points par type d'evenement) ----
    POINTS = {
        "gaze_off_screen": 35,
        "gaze_down": 15,
        "face_absent": 40,
        "multiple_persons": 50,
        "phone_detected": 45,
        "paper_detected": 25,
        "head_agitation": 15,
        "voice_detected": 25,
    }

    # ---- Bornes des niveaux de risque ----
    RISK_BOUNDS = {
        "none": (0, 30),
        "suspect": (31, 60),
        "high": (61, 80),
        "very_high": (81, 100),
    }


settings = Settings()


def ensure_dirs():
    """Cree les dossiers de stockage au demarrage s'ils n'existent pas."""
    for d in (settings.UPLOAD_DIR, settings.FRAMES_DIR, settings.REPORTS_DIR):
        os.makedirs(d, exist_ok=True)
