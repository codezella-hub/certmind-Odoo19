# -*- coding: utf-8 -*-
"""
pipeline/preprocess.py — Preparation de la video avant analyse.

Probleme : les WebM enregistres par le navigateur (MediaRecorder, codec
VP8/VP9) sont mal decodes par OpenCV et librosa sur Windows. OpenCV ne
lit qu'une frame, librosa ne trouve pas l'audio.

Solution : convertir la video en MP4 (H.264 + AAC) avec ffmpeg AVANT
l'analyse. ffmpeg gere tous les codecs et produit un MP4 propre que
OpenCV et librosa lisent sans probleme.

ffmpeg doit etre installe et accessible dans le PATH. On le detecte au
demarrage ; s'il est absent, on tente l'analyse directe (avec un
avertissement) plutot que de planter.
"""
import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Extensions qui beneficient d'une conversion (codecs mal supportes).
_NEEDS_CONVERSION = {".webm", ".mkv", ".avi", ".mov"}


def ffmpeg_available() -> bool:
    """True si ffmpeg est installe et accessible dans le PATH."""
    return shutil.which("ffmpeg") is not None


def prepare_video(video_path: str) -> tuple[str, bool]:
    """
    Prepare la video pour l'analyse.

    Si le fichier est dans un format a risque (WebM...) et que ffmpeg est
    disponible, convertit en MP4 dans un fichier temporaire.

    Retourne (chemin_a_analyser, est_temporaire).
    Si est_temporaire=True, l'appelant doit supprimer le fichier apres usage.
    """
    ext = os.path.splitext(video_path)[1].lower()

    # Format deja sur (MP4) : rien a faire.
    if ext not in _NEEDS_CONVERSION:
        return video_path, False

    # ffmpeg absent : on tente quand meme avec le fichier original.
    if not ffmpeg_available():
        logger.warning(
            "ffmpeg absent : analyse directe du %s (risque de lecture "
            "partielle). Installez ffmpeg pour une lecture fiable.", ext,
        )
        return video_path, False

    # Conversion WebM -> MP4.
    fd, mp4_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)  # on ferme le descripteur, ffmpeg ecrira dedans

    cmd = [
        "ffmpeg", "-y",              # -y : ecrase le fichier de sortie
        "-i", video_path,           # entree
        "-c:v", "libx264",          # video en H.264
        "-preset", "veryfast",      # rapide (qualite suffisante pour l'analyse)
        "-c:a", "aac",              # audio en AAC (lisible par librosa)
        "-movflags", "+faststart",  # metadonnees en tete (duree fiable !)
        mp4_path,
    ]

    logger.info("Conversion %s -> MP4 via ffmpeg...", ext)
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,  # 5 min max pour la conversion
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="ignore")[-500:]
            logger.warning("ffmpeg a echoue (code %s) : %s",
                           result.returncode, err)
            # On nettoie et on retombe sur le fichier original.
            _safe_remove(mp4_path)
            return video_path, False

        # Verifie que le MP4 produit n'est pas vide.
        if os.path.getsize(mp4_path) == 0:
            logger.warning("ffmpeg a produit un fichier vide.")
            _safe_remove(mp4_path)
            return video_path, False

        logger.info("Conversion reussie : %s", mp4_path)
        return mp4_path, True

    except subprocess.TimeoutExpired:
        logger.warning("Conversion ffmpeg trop longue (timeout).")
        _safe_remove(mp4_path)
        return video_path, False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Erreur conversion ffmpeg : %s", exc)
        _safe_remove(mp4_path)
        return video_path, False


def _safe_remove(path: str):
    """Supprime un fichier sans lever d'erreur."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
