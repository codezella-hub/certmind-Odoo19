# -*- coding: utf-8 -*-
"""
pipeline/scorer.py — Transforme les detections en score de risque.

C'est la COUCHE DE DECISION. Les modeles (MediaPipe/YOLO/Silero) disent
"quoi est dans l'image". Ici on decide "est-ce suspect et combien".

V1 = regles simples (pas de ML). Chaque signal a un poids defini dans
config.POINTS. Le score final = somme plafonnee a 100.

On raisonne sur des AGREGATS temporels, pas frame par frame :
  - regard hors ecran > X% du temps -> alerte
  - telephone vu au moins une fois -> alerte
  - voix > X secondes cumulees -> alerte
"""
import logging

from .proctoring_config import settings
from .schemas import (
    AnalysisResult, AnalysisStats, EventType, RiskLevel,
    SuspiciousEvent,
)

logger = logging.getLogger(__name__)


class Scorer:
    """
    Accumule les observations frame par frame, puis calcule le score
    final et la timeline d'evenements.
    """

    def __init__(self, task_id: str):
        self.task_id = task_id
        # Compteurs frame par frame
        self.total_frames = 0
        self.gaze_off_frames = 0
        self.gaze_down_frames = 0
        self.face_absent_frames = 0
        self.multi_person_frames = 0
        self.phone_frames = 0
        self.paper_frames = 0
        # Evenements horodates (pour la timeline)
        self.events: list[SuspiciousEvent] = []
        # Suivi des angles pour la variance (agitation)
        self._yaw_history = []
        # Duree totale (renseignee a la fin)
        self.duration = 0.0
        # Resultat audio (renseigne a la fin)
        self._audio_voice_seconds = 0.0
        self._audio_voice_ratio = 0.0

    # ------------------------------------------------------------------
    # ACCUMULATION (appele pour chaque frame par l'analyzer)
    # ------------------------------------------------------------------

    def observe_frame(self, timestamp, face_result, object_result):
        """Enregistre les observations d'une frame."""
        self.total_frames += 1

        # ---- Visage absent ----
        if not face_result.face_present:
            self.face_absent_frames += 1
            self._add_event(
                timestamp, EventType.FACE_ABSENT, 1.0,
                settings.POINTS["face_absent"], "aucun visage detecte",
            )
        else:
            self._yaw_history.append(face_result.yaw)

            # ---- Regard hors ecran (yaw) ----
            if abs(face_result.yaw) > settings.YAW_THRESHOLD_DEG:
                self.gaze_off_frames += 1
                self._add_event(
                    timestamp, EventType.GAZE_OFF_SCREEN,
                    min(abs(face_result.yaw) / 90, 1.0),
                    settings.POINTS["gaze_off_screen"],
                    f"yaw={face_result.yaw}deg",
                )

            # ---- Regard vers le bas (pitch) ----
            if face_result.pitch > settings.PITCH_THRESHOLD_DEG:
                self.gaze_down_frames += 1
                self._add_event(
                    timestamp, EventType.GAZE_DOWN,
                    min(face_result.pitch / 90, 1.0),
                    settings.POINTS["gaze_down"],
                    f"pitch={face_result.pitch}deg",
                )

        # ---- 2eme personne ----
        if object_result.person_count > 1:
            self.multi_person_frames += 1
            self._add_event(
                timestamp, EventType.MULTIPLE_PERSONS, 1.0,
                settings.POINTS["multiple_persons"],
                f"{object_result.person_count} personnes",
            )

        # ---- Telephone ----
        if object_result.phone_detected:
            self.phone_frames += 1
            self._add_event(
                timestamp, EventType.PHONE_DETECTED, 0.9,
                settings.POINTS["phone_detected"], "telephone visible",
            )

        # ---- Papier/notes ----
        if object_result.paper_detected:
            self.paper_frames += 1
            self._add_event(
                timestamp, EventType.PAPER_DETECTED, 0.7,
                settings.POINTS["paper_detected"], "papier/notes visible",
            )

    def set_audio_result(self, audio_result):
        """Injecte le resultat de l'analyse audio globale."""
        self._audio_voice_seconds = audio_result.total_voice_seconds
        self._audio_voice_ratio = audio_result.voice_ratio

        # Voix cumulee au-dessus du seuil -> evenements sur chaque segment.
        if audio_result.total_voice_seconds >= settings.VOICE_MIN_TOTAL_SEC:
            for seg in audio_result.voice_segments:
                self._add_event(
                    seg.start, EventType.VOICE_DETECTED, seg.confidence,
                    settings.POINTS["voice_detected"],
                    f"voix {seg.start}-{seg.end}s",
                )

    def set_duration(self, duration: float):
        self.duration = duration

    # ------------------------------------------------------------------
    # CALCUL FINAL
    # ------------------------------------------------------------------

    def compute(self) -> AnalysisResult:
        """Calcule le score final, le niveau de risque et les stats."""
        score = 0

        # Ratios temporels
        gaze_off_ratio = self._ratio(self.gaze_off_frames)
        face_absent_ratio = self._ratio(self.face_absent_frames)

        # ---- Contributions au score (basees sur des seuils) ----
        # Regard hors ecran : contribue si > 20% du temps.
        if gaze_off_ratio > 0.20:
            score += settings.POINTS["gaze_off_screen"]

        # Visage absent : contribue si > 10% du temps.
        if face_absent_ratio > 0.10:
            score += settings.POINTS["face_absent"]

        # 2eme personne : suspect si vue sur >=2 frames OU sur une part
        # notable des frames (couvre les videos courtes / peu de frames).
        multi_ratio = self._ratio(self.multi_person_frames)
        if self.multi_person_frames >= 2 or multi_ratio >= 0.30:
            score += settings.POINTS["multiple_persons"]

        # Telephone : des qu'il est vu (signal fort).
        if self.phone_frames >= 1:
            score += settings.POINTS["phone_detected"]

        # Papier : si vu plusieurs fois OU part notable des frames.
        paper_ratio = self._ratio(self.paper_frames)
        if self.paper_frames >= 3 or paper_ratio >= 0.30:
            score += settings.POINTS["paper_detected"]

        # Regard bas repete.
        if self._ratio(self.gaze_down_frames) > 0.15:
            score += settings.POINTS["gaze_down"]

        # Agitation de la tete (variance du yaw).
        if len(self._yaw_history) > 5:
            variance = self._variance(self._yaw_history)
            if variance > settings.HEAD_VARIANCE_THRESHOLD:
                score += settings.POINTS["head_agitation"]
                self._add_event(
                    0.0, EventType.HEAD_AGITATION,
                    min(variance / 50, 1.0),
                    settings.POINTS["head_agitation"],
                    f"variance yaw={round(variance, 1)}",
                )

        # Voix.
        if self._audio_voice_seconds >= settings.VOICE_MIN_TOTAL_SEC:
            score += settings.POINTS["voice_detected"]

        # Plafonnement a 100.
        score = min(score, 100)

        stats = AnalysisStats(
            duration_seconds=round(self.duration, 2),
            frames_analyzed=self.total_frames,
            gaze_off_ratio=round(gaze_off_ratio, 3),
            face_absent_ratio=round(face_absent_ratio, 3),
            voice_ratio=round(self._audio_voice_ratio, 3),
            total_alerts=len(self.events),
        )

        return AnalysisResult(
            task_id=self.task_id,
            risk_score=score,
            risk_level=self._risk_level(score),
            events=sorted(self.events, key=lambda e: e.timestamp),
            stats=stats,
            report_available=False,  # mis a True apres generation PDF
        )

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _add_event(self, timestamp, event_type, confidence, points, detail):
        self.events.append(SuspiciousEvent(
            timestamp=round(float(timestamp), 2),
            event_type=event_type,
            confidence=round(float(confidence), 3),
            points=points,
            detail=detail,
        ))

    def _ratio(self, count: int) -> float:
        return count / self.total_frames if self.total_frames > 0 else 0.0

    @staticmethod
    def _variance(values) -> float:
        n = len(values)
        mean = sum(values) / n
        return sum((v - mean) ** 2 for v in values) / n

    @staticmethod
    def _risk_level(score: int) -> RiskLevel:
        if score <= 30:
            return RiskLevel.NONE
        if score <= 60:
            return RiskLevel.SUSPECT
        if score <= 80:
            return RiskLevel.HIGH
        return RiskLevel.VERY_HIGH
