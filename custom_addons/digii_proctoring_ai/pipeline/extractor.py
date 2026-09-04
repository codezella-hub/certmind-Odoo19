# -*- coding: utf-8 -*-
"""
pipeline/extractor.py — Extraction de frames depuis une video.

Responsabilite UNIQUE : ouvrir une video et renvoyer des frames a un
rythme donne (ex: 1 image/seconde), chacune avec son timestamp.

IMPORTANT — gestion des WebM navigateur :
Les videos WebM enregistrees par MediaRecorder (navigateur) n'ont
souvent PAS de metadonnees fiables (CAP_PROP_FRAME_COUNT renvoie une
valeur aberrante comme -9.2e18, CAP_PROP_FPS peut etre 0). On ne se fie
donc JAMAIS a FRAME_COUNT pour la duree : on lit les frames reellement
et on utilise le timestamp OpenCV (CAP_PROP_POS_MSEC) ou un compteur.
"""
import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# FPS de repli quand la video ne declare pas le sien (WebM navigateur).
_DEFAULT_FPS = 25.0
# Valeur au-dela de laquelle FRAME_COUNT est juge aberrant (WebM casse).
_MAX_REASONABLE_FRAMES = 10_000_000  # ~92h a 30fps : au-dela = invalide


@dataclass
class Frame:
    """Une frame extraite avec son horodatage."""
    timestamp: float       # seconde dans la video
    image: np.ndarray      # image BGR (format OpenCV)
    index: int             # numero de la frame extraite


def _safe_fps(cap) -> float:
    """Retourne un FPS raisonnable, avec repli si absent ou absurde."""
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    if fps <= 0 or fps > 1000:  # 0 ou valeur absurde
        return _DEFAULT_FPS
    return fps


def get_video_info(video_path: str) -> dict:
    """
    Retourne les metadonnees de la video de facon ROBUSTE.

    Pour la duree : on ne fait pas confiance a FRAME_COUNT (peut etre
    aberrant sur WebM). On mesure par lecture si necessaire.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Impossible d'ouvrir la video : {video_path}")

    fps = _safe_fps(cap)
    raw_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    # FRAME_COUNT fiable ? (positif et raisonnable)
    frame_count_valid = 0 < raw_frame_count < _MAX_REASONABLE_FRAMES

    if frame_count_valid:
        duration = raw_frame_count / fps
        frame_count = raw_frame_count
    else:
        logger.warning(
            "FRAME_COUNT non fiable (%s) : mesure de la duree par lecture.",
            raw_frame_count,
        )
        duration, frame_count = _measure_duration_by_reading(cap, fps)

    cap.release()

    if width <= 0 or height <= 0:
        raise ValueError(
            f"Video illisible (dimensions {width}x{height}). "
            "Fichier corrompu ou format non supporte."
        )

    return {
        "fps": round(fps, 2),
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration_seconds": round(max(duration, 0.0), 2),
    }


def _measure_duration_by_reading(cap, fps: float):
    """
    Mesure la duree en parcourant la video (pour WebM sans metadonnees).
    Retourne (duree_secondes, nombre_de_frames).
    """
    count = 0
    last_msec = 0.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    while True:
        ret = cap.grab()  # grab() = plus rapide (pas de decode complet)
        if not ret:
            break
        count += 1
        msec = cap.get(cv2.CAP_PROP_POS_MSEC)
        if msec and msec > last_msec:
            last_msec = msec

    if last_msec > 0:
        duration = last_msec / 1000.0
    else:
        duration = count / fps if fps > 0 else 0.0

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return duration, count


def extract_frames(video_path: str, frames_per_second: float = 1.0):
    """
    Generateur qui yield des Frame a la cadence demandee.

    Robuste aux WebM : on ne se fie pas a FRAME_COUNT. On lit toutes les
    frames et on en garde une sur N selon le fps cible.

    Args:
        video_path: chemin du fichier video
        frames_per_second: combien de frames analyser par seconde de video

    Yields:
        Frame(timestamp, image, index)
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Impossible d'ouvrir la video : {video_path}")

    source_fps = _safe_fps(cap)
    step = max(1, int(round(source_fps / frames_per_second)))

    src_index = 0
    out_index = 0
    while True:
        ret, image = cap.read()
        if not ret:
            break

        if src_index % step == 0:
            timestamp = src_index / source_fps
            if image is not None and image.size > 0:
                yield Frame(
                    timestamp=round(timestamp, 3),
                    image=image,
                    index=out_index,
                )
                out_index += 1

        src_index += 1

    cap.release()
    logger.info("Extraction terminee : %d frames analysees", out_index)
