# -*- coding: utf-8 -*-
"""
schemas.py — Contrat de donnees du microservice.

Toutes les formes de donnees qui entrent et sortent de l'API sont
definies ici avec Pydantic. Avantages :
  - validation automatique des entrees (FastAPI rejette le mauvais JSON)
  - documentation /docs auto-generee et correcte
  - un seul endroit ou le "format" de l'analyse est defini

Regle : les routers et le pipeline NE definissent JAMAIS leurs propres
dicts a la main. Ils construisent et retournent ces modeles.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ======================================================================
# ENUMERATIONS
# ======================================================================

class TaskStatus(str, Enum):
    """Etat d'une tache d'analyse (cycle de vie)."""
    PENDING = "pending"        # cree, pas encore demarre
    PROCESSING = "processing"  # pipeline en cours
    DONE = "done"              # termine avec succes
    ERROR = "error"            # echec (voir error_message)


class EventType(str, Enum):
    """
    Type d'evenement suspect detecte.
    Chaque valeur correspond a un critere de triche defini en amont.
    """
    GAZE_OFF_SCREEN = "gaze_off_screen"      # regard hors ecran (yaw)
    GAZE_DOWN = "gaze_down"                   # regard vers le bas (pitch)
    FACE_ABSENT = "face_absent"              # aucun visage detecte
    MULTIPLE_PERSONS = "multiple_persons"    # 2eme personne (YOLO)
    PHONE_DETECTED = "phone_detected"        # telephone (YOLO)
    PAPER_DETECTED = "paper_detected"        # papier/notes (YOLO)
    HEAD_AGITATION = "head_agitation"        # variance angles elevee
    VOICE_DETECTED = "voice_detected"        # activite vocale (Silero)


class RiskLevel(str, Enum):
    """Categorie de risque derivee du score final (0-100)."""
    NONE = "none"            # 0-30
    SUSPECT = "suspect"      # 31-60
    HIGH = "high"            # 61-80
    VERY_HIGH = "very_high"  # 81-100


# ======================================================================
# EVENEMENTS ET STATISTIQUES
# ======================================================================

class SuspiciousEvent(BaseModel):
    """
    Un evenement suspect horodate dans la video.
    C'est l'unite de base de la timeline.
    """
    timestamp: float = Field(..., description="Seconde dans la video", ge=0)
    event_type: EventType = Field(..., description="Type de signal detecte")
    confidence: float = Field(..., description="Confiance 0-1", ge=0, le=1)
    points: int = Field(..., description="Points de risque ajoutes")
    detail: Optional[str] = Field(None, description="Info lisible (ex: yaw=35deg)")
    frame_path: Optional[str] = Field(None, description="Capture du frame suspect")


class AnalysisStats(BaseModel):
    """Statistiques agregees sur toute la video."""
    duration_seconds: float = Field(..., description="Duree totale analysee")
    frames_analyzed: int = Field(..., description="Nb de frames traitees")
    gaze_off_ratio: float = Field(0.0, description="% temps regard hors ecran", ge=0, le=1)
    face_absent_ratio: float = Field(0.0, description="% temps sans visage", ge=0, le=1)
    voice_ratio: float = Field(0.0, description="% temps avec voix", ge=0, le=1)
    total_alerts: int = Field(0, description="Nb total d'evenements suspects")


# ======================================================================
# INTERPRETATION LLM
# ======================================================================

class LlmInterpretation(BaseModel):
    """
    Interpretation en langage naturel generee par le LLM (Groq).
    Aide le procteur a lire le resultat. Ne remplace PAS sa decision.
    """
    conclusion: str = Field(..., description="Synthese en 2-3 phrases")
    interpretation: str = Field(..., description="Explication des signaux")
    recommendation: str = Field(..., description="Conseil au procteur")
    generated: bool = Field(True, description="False si le LLM a echoue")


# ======================================================================
# RESULTAT COMPLET
# ======================================================================

class AnalysisResult(BaseModel):
    """
    Resultat final d'une analyse. C'est ce que Odoo recupere via
    GET /result/{task_id} et stocke dans exam.proctoring.session.
    """
    task_id: str
    risk_score: int = Field(..., description="Score de risque 0-100", ge=0, le=100)
    risk_level: RiskLevel
    events: list[SuspiciousEvent] = Field(default_factory=list)
    stats: AnalysisStats
    interpretation: Optional[LlmInterpretation] = Field(
        None, description="Analyse en langage naturel (LLM)")
    report_available: bool = Field(False, description="True si le PDF est pret")
    # Metadonnees du candidat (transmises par Odoo, optionnelles)
    candidate_name: Optional[str] = Field(None, description="Nom du candidat")
    exam_name: Optional[str] = Field(None, description="Nom de l'examen")
    exam_date: Optional[str] = Field(None, description="Date de l'examen (str)")


# ======================================================================
# REPONSES D'API
# ======================================================================

class AnalyzeResponse(BaseModel):
    """Reponse immediate a POST /analyze/video (avant traitement)."""
    task_id: str
    status: TaskStatus
    message: str = "Analyse demarree. Interrogez /status/{task_id}."


class StatusResponse(BaseModel):
    """Reponse a GET /status/{task_id} (polling)."""
    task_id: str
    status: TaskStatus
    progress: int = Field(0, description="Progression 0-100", ge=0, le=100)
    error_message: Optional[str] = None
