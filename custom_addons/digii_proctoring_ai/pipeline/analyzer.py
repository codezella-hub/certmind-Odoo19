# -*- coding: utf-8 -*-
"""
pipeline/analyzer.py — Orchestrateur du pipeline complet.

C'est le chef d'orchestre. Il enchaine :
  1. extraction des frames (extractor)
  2. analyse visage (face) + objets (objects) sur chaque frame
  3. analyse audio globale (audio)
  4. scoring (scorer)

Les modeles (FaceAnalyzer, ObjectDetector, AudioAnalyzer) sont lourds a
charger. On les charge PARESSEUSEMENT (lazy) et une seule fois, via un
singleton, pour ne pas payer le cout a chaque requete.

Une fonction de callback `on_progress` permet de remonter la progression
(0-100) pour l'endpoint /status.
"""
import logging
from typing import Callable, Optional

from .proctoring_config import settings
from .schemas import AnalysisResult
from .extractor import extract_frames, get_video_info
from .preprocess import prepare_video, _safe_remove
from .scorer import Scorer

logger = logging.getLogger(__name__)


class _Models:
    """
    Conteneur singleton des modeles lourds.
    Charges une seule fois au premier usage.
    """
    _face = None
    _objects = None
    _audio = None

    @classmethod
    def face(cls):
        if cls._face is None:
            from .face import FaceAnalyzer
            logger.info("Chargement MediaPipe FaceAnalyzer...")
            cls._face = FaceAnalyzer(max_faces=2)
        return cls._face

    @classmethod
    def objects(cls):
        if cls._objects is None:
            from .objects import ObjectDetector
            logger.info("Chargement YOLOv8 ObjectDetector...")
            cls._objects = ObjectDetector(
                model_path=settings.YOLO_MODEL,
                confidence=settings.YOLO_CONFIDENCE,
            )
        return cls._objects

    @classmethod
    def audio(cls):
        if cls._audio is None:
            from .audio import AudioAnalyzer
            logger.info("Chargement Silero VAD AudioAnalyzer...")
            cls._audio = AudioAnalyzer(
                sample_rate=settings.AUDIO_SAMPLE_RATE,
                confidence=settings.VOICE_CONFIDENCE,
            )
        return cls._audio


def analyze_video(
    task_id: str,
    video_path: str,
    on_progress: Optional[Callable[[int], None]] = None,
) -> AnalysisResult:
    """
    Analyse complete d'une video. Bloquant (a lancer dans un thread ou
    une BackgroundTask cote API).

    Args:
        task_id: identifiant de la tache
        video_path: chemin du MP4 a analyser
        on_progress: callback optionnel appele avec la progression 0-100

    Returns:
        AnalysisResult complet
    """
    def _progress(p):
        if on_progress:
            on_progress(min(max(int(p), 0), 100))

    logger.info("[%s] Debut analyse : %s", task_id, video_path)

    # --- Preparation : conversion WebM/autres -> MP4 via ffmpeg ---
    # Rend la video lisible de facon fiable par OpenCV et librosa.
    analysis_path, is_temp = prepare_video(video_path)
    if is_temp:
        logger.info("[%s] Video convertie pour analyse : %s",
                    task_id, analysis_path)

    try:
        return _run_pipeline(task_id, analysis_path, _progress)
    finally:
        # Nettoie le MP4 temporaire de conversion (garde l'original).
        if is_temp:
            _safe_remove(analysis_path)


def _run_pipeline(task_id, video_path, _progress) -> AnalysisResult:
    """Corps de l'analyse, sur une video deja preparee (MP4 lisible)."""
    # --- Metadonnees ---
    info = get_video_info(video_path)
    duration = info["duration_seconds"]

    # Securite : si la duree est aberrante malgre la correction, on la
    # bornera plus tard sur le nombre de frames reellement analysees.
    if duration <= 0 or duration > 86400:  # > 24h = invalide
        logger.warning("[%s] Duree suspecte (%s), sera recalculee.",
                       task_id, duration)
        duration = 0.0

    expected_frames = max(1, int(duration * settings.FRAMES_PER_SECOND)) if duration > 0 else 100
    _progress(5)

    scorer = Scorer(task_id)
    scorer.set_duration(duration)

    face_analyzer = _Models.face()
    object_detector = _Models.objects()

    # --- Boucle frame par frame (visage + objets) ---
    frame_no = 0
    last_timestamp = 0.0
    for frame in extract_frames(video_path, settings.FRAMES_PER_SECOND):
        face_result = face_analyzer.analyze(frame.image)
        object_result = object_detector.detect(frame.image)
        scorer.observe_frame(frame.timestamp, face_result, object_result)
        last_timestamp = frame.timestamp

        frame_no += 1
        # 5% -> 75% de la progression sur la boucle video
        if frame_no % 10 == 0:
            pct = 5 + int(70 * frame_no / expected_frames)
            _progress(min(pct, 75))

    # Si la duree etait invalide, on la reconstruit depuis les frames lues.
    if duration <= 0 and frame_no > 0:
        # frames analysees a FRAMES_PER_SECOND -> duree approx.
        duration = max(last_timestamp, frame_no / settings.FRAMES_PER_SECOND)
        scorer.set_duration(duration)
        logger.info("[%s] Duree recalculee : %.1fs (%d frames)",
                    task_id, duration, frame_no)

    _progress(78)

    # --- Analyse audio globale ---
    try:
        audio_analyzer = _Models.audio()
        audio_result = audio_analyzer.analyze(video_path)
        scorer.set_audio_result(audio_result)
    except Exception as exc:  # audio non bloquant
        logger.warning("[%s] Analyse audio ignoree : %s", task_id, exc)

    _progress(90)

    # --- Score final ---
    result = scorer.compute()
    _progress(93)

    # --- Interpretation LLM (Groq) ---
    # Non bloquant : si le LLM echoue, on garde le resultat sans interpretation.
    try:
        from .interpreter import interpret_result
        result.interpretation = interpret_result(result)
    except Exception as exc:  # securite : ne jamais planter ici
        logger.warning("[%s] Interpretation LLM ignoree : %s", task_id, exc)

    _progress(100)

    logger.info(
        "[%s] Analyse terminee : score=%d niveau=%s alertes=%d",
        task_id, result.risk_score, result.risk_level, len(result.events),
    )
    return result
