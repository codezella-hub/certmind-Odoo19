# -*- coding: utf-8 -*-
"""
pipeline/audio.py — Detection d'activite vocale avec Silero VAD.

Responsabilite : extraire la piste audio du MP4 et detecter les
segments ou une voix parle. Sert deux signaux :
  - le candidat parle/murmure (a croiser avec les levres qui bougent)
  - quelqu'un parle autour de lui (voix mais levres immobiles)

Silero VAD est un modele pre-entraine (~1 MB) qui tourne sur CPU.
Il travaille sur des chunks de 512 samples a 16 kHz.

L'analyse audio est GLOBALE (sur toute la video), contrairement au
visage/objets qui sont frame par frame. On la fait une seule fois.
"""
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 512  # Silero attend des chunks de 512 samples a 16kHz


@dataclass
class VoiceSegment:
    """Un segment horodate ou une voix a ete detectee."""
    start: float       # seconde de debut
    end: float         # seconde de fin
    confidence: float  # confiance moyenne


@dataclass
class AudioResult:
    """Resultat global de l'analyse audio."""
    voice_segments: list = field(default_factory=list)  # list[VoiceSegment]
    total_voice_seconds: float = 0.0
    voice_ratio: float = 0.0       # % du temps avec voix
    audio_available: bool = True   # False si pas de piste audio


class AudioAnalyzer:
    """
    Encapsule Silero VAD. Instancier UNE fois, reutiliser.
    """

    def __init__(self, sample_rate: int = 16000, confidence: float = 0.5):
        import torch
        from silero_vad import load_silero_vad
        self._torch = torch
        self.model = load_silero_vad()
        self.sample_rate = sample_rate
        self.confidence = confidence

    def analyze(self, video_path: str) -> AudioResult:
        """
        Extrait l'audio du MP4 et detecte les segments de voix.
        """
        import librosa

        # Charge l'audio en mono 16kHz directement depuis le MP4.
        try:
            audio, _ = librosa.load(video_path, sr=self.sample_rate, mono=True)
        except Exception as exc:
            logger.warning("Pas de piste audio exploitable : %s", exc)
            return AudioResult(audio_available=False)

        if audio is None or len(audio) == 0:
            return AudioResult(audio_available=False)

        total_duration = len(audio) / self.sample_rate
        segments = self._detect_segments(audio)

        total_voice = sum(s.end - s.start for s in segments)
        ratio = total_voice / total_duration if total_duration > 0 else 0.0

        return AudioResult(
            voice_segments=segments,
            total_voice_seconds=round(total_voice, 2),
            voice_ratio=round(ratio, 3),
            audio_available=True,
        )

    def _detect_segments(self, audio):
        """
        Parcourt l'audio par chunks et regroupe les segments de voix
        consecutifs en periodes continues.
        """
        torch = self._torch
        segments = []
        in_speech = False
        seg_start = 0.0
        conf_accum = []

        for i in range(0, len(audio) - _CHUNK_SIZE, _CHUNK_SIZE):
            chunk = audio[i:i + _CHUNK_SIZE]
            tensor = torch.from_numpy(chunk).float()
            conf = self.model(tensor, self.sample_rate).item()
            timestamp = i / self.sample_rate

            if conf >= self.confidence:
                if not in_speech:
                    in_speech = True
                    seg_start = timestamp
                    conf_accum = []
                conf_accum.append(conf)
            else:
                if in_speech:
                    # fin d'un segment de voix
                    avg_conf = sum(conf_accum) / len(conf_accum) if conf_accum else 0
                    segments.append(VoiceSegment(
                        start=round(seg_start, 2),
                        end=round(timestamp, 2),
                        confidence=round(avg_conf, 3),
                    ))
                    in_speech = False

        # segment encore ouvert a la fin
        if in_speech and conf_accum:
            avg_conf = sum(conf_accum) / len(conf_accum)
            segments.append(VoiceSegment(
                start=round(seg_start, 2),
                end=round(len(audio) / self.sample_rate, 2),
                confidence=round(avg_conf, 3),
            ))

        return segments
