# -*- coding: utf-8 -*-
"""
interpreter.py — Interpretation du resultat par un LLM (Groq).

Prend un AnalysisResult (score + events + stats) et demande au modele
Groq (llama-3.3-70b) de produire une lecture en langage naturel pour le
procteur : conclusion, interpretation des signaux, recommandation.

Principes importants :
  - Le LLM N'INVENTE PAS de score. Il explique le score deja calcule.
  - Il ne rend JAMAIS un verdict automatique de triche. Il recommande
    une revue humaine (philosophie flag + validation humaine).
  - Si le LLM echoue (pas de cle, timeout, JSON invalide), l'analyse
    continue sans interpretation : ce module ne doit JAMAIS faire
    planter le pipeline.

On utilise le SDK OpenAI (compatible Groq) en mode JSON, exactement
comme le module Odoo digii_exam_ai_agent.
"""
import json
import logging

from .proctoring_config import settings
from .schemas import AnalysisResult, LlmInterpretation

logger = logging.getLogger(__name__)


# Libelles lisibles des events (pour donner du contexte au LLM).
_EVENT_LABELS = {
    "gaze_off_screen": "regard hors ecran",
    "gaze_down": "regard vers le bas",
    "face_absent": "visage absent du cadre",
    "multiple_persons": "deuxieme personne visible",
    "phone_detected": "telephone visible",
    "paper_detected": "papier ou notes visibles",
    "head_agitation": "agitation de la tete",
    "voice_detected": "voix detectee",
}


_SYSTEM_PROMPT = """Tu es un assistant qui aide un surveillant d'examen \
(procteur) a interpreter le rapport automatique d'un systeme de detection \
de triche par IA.

Regles STRICTES :
- Tu n'inventes AUCUN chiffre. Tu te bases UNIQUEMENT sur les donnees fournies.
- Tu ne rends JAMAIS un verdict definitif de triche. Le systeme SIGNALE, \
c'est un humain qui DECIDE.
- Tu rappelles que des faux positifs sont possibles (reflets, objets mal \
interpretes, stress normal).
- Tu ecris en francais clair, factuel, sans dramatiser.
- Tu produis UNIQUEMENT un objet JSON valide, sans texte autour, sans balises \
markdown, avec exactement ces trois cles :
  "conclusion"      : synthese neutre en 2 a 3 phrases
  "interpretation"  : explication des signaux detectes et de leur fiabilite
  "recommendation"  : conseil concret au procteur (ex: quels segments revoir)
"""


def _build_user_prompt(result: AnalysisResult) -> str:
    """Construit le message utilisateur a partir du resultat."""
    # Compte les events par type pour un resume compact.
    counts = {}
    for ev in result.events:
        key = ev.event_type.value
        counts[key] = counts.get(key, 0) + 1

    signals_lines = []
    for key, nb in sorted(counts.items(), key=lambda x: -x[1]):
        label = _EVENT_LABELS.get(key, key)
        signals_lines.append(f"- {label} : {nb} occurrence(s)")
    signals_text = "\n".join(signals_lines) or "- aucun signal suspect"

    s = result.stats
    return f"""Voici le resultat d'une analyse de proctoring a interpreter.

SCORE DE RISQUE : {result.risk_score}/100
NIVEAU : {result.risk_level.value}

STATISTIQUES :
- duree analysee : {s.duration_seconds} s
- frames analysees : {s.frames_analyzed}
- temps regard hors ecran : {round(s.gaze_off_ratio * 100, 1)} %
- temps sans visage : {round(s.face_absent_ratio * 100, 1)} %
- temps avec voix : {round(s.voice_ratio * 100, 1)} %
- nombre total d'alertes : {s.total_alerts}

SIGNAUX DETECTES :
{signals_text}

Rappel : le score est deja calcule par le systeme. Explique-le, ne le \
recalcule pas. Reponds uniquement en JSON avec les cles conclusion, \
interpretation, recommendation."""


def interpret_result(result: AnalysisResult) -> LlmInterpretation:
    """
    Genere l'interpretation LLM. Ne leve jamais d'exception : en cas
    d'echec, retourne une interpretation de repli (generated=False).
    """
    if not settings.LLM_ENABLED:
        return _fallback(result, "LLM desactive (PROCTOR_LLM_ENABLED=0).")

    if not settings.GROQ_API_KEY:
        logger.warning("GROQ_API_KEY absente : interpretation ignoree.")
        return _fallback(result, "Cle API Groq absente.")

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("SDK openai non installe : interpretation ignoree.")
        return _fallback(result, "Bibliotheque openai absente.")

    try:
        client = OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url=settings.GROQ_BASE_URL,
            timeout=settings.GROQ_TIMEOUT,
        )
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            temperature=settings.GROQ_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(result)},
            ],
        )
        raw = response.choices[0].message.content or ""
        data = json.loads(raw)

        return LlmInterpretation(
            conclusion=data.get("conclusion", "").strip()
                or "Conclusion non disponible.",
            interpretation=data.get("interpretation", "").strip()
                or "Interpretation non disponible.",
            recommendation=data.get("recommendation", "").strip()
                or "Revue humaine recommandee.",
            generated=True,
        )
    except json.JSONDecodeError as exc:
        logger.warning("LLM : JSON invalide : %s", exc)
        return _fallback(result, "Reponse LLM non exploitable.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM : appel echoue : %s", exc)
        return _fallback(result, f"Erreur LLM : {exc}")


def _fallback(result: AnalysisResult, reason: str) -> LlmInterpretation:
    """
    Interpretation de repli generee sans LLM (regles simples).
    Garantit qu'il y a toujours un texte lisible, meme sans IA.
    """
    level_text = {
        "none": "aucun risque notable",
        "suspect": "un risque moderé a surveiller",
        "high": "un risque eleve",
        "very_high": "un risque tres eleve",
    }.get(result.risk_level.value, "un risque indetermine")

    nb = len(result.events)
    conclusion = (
        f"Le systeme a calcule un score de {result.risk_score}/100, "
        f"soit {level_text}, avec {nb} alerte(s) relevee(s)."
    )
    interpretation = (
        "Interpretation automatique indisponible (" + reason + "). "
        "Consultez la timeline des evenements pour le detail des signaux."
    )
    recommendation = (
        "Une revue humaine de la video est recommandee avant toute "
        "decision. Le score est indicatif et des faux positifs sont possibles."
    )
    return LlmInterpretation(
        conclusion=conclusion,
        interpretation=interpretation,
        recommendation=recommendation,
        generated=False,
    )
