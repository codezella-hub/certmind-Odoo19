# -*- coding: utf-8 -*-
"""
Service d'appel IA DEDIE au module LMS (independant de l'agent examen).

Configuration propre via ir.config_parameter :

    digii_lms_ai_agent.api_key     cle API Groq (jamais en dur)
    digii_lms_ai_agent.model       defaut: openai/gpt-oss-120b
    digii_lms_ai_agent.base_url    defaut: https://api.groq.com/openai/v1

Ainsi le tuteur LMS a sa PROPRE cle et son PROPRE modele, separes de
ceux de l'agent examen. On peut par exemple utiliser un modele plus
leger/rapide pour le tuteur et un plus puissant pour la generation
d'examens, ou des cles differentes.

Expose `chat_json(system_prompt, user_prompt)` et `is_configured()`.
"""
import json
import logging

from odoo import api, models, _

_logger = logging.getLogger(__name__)

# Modele Groq par defaut (l'ancien llama-3.3-70b-versatile est deprecie).
DEFAULT_MODEL = 'openai/gpt-oss-120b'
DEFAULT_BASE_URL = 'https://api.groq.com/openai/v1'
DEFAULT_TEMPERATURE = 0.5
REQUEST_TIMEOUT = 60


class LmsAiServiceError(Exception):
    """Erreur metier renvoyee proprement au frontend."""
    pass


class DigiiLmsAiService(models.AbstractModel):
    _name = 'digii.lms.ai.service'
    _description = "Service d'appel IA du LMS (Groq)"

    # ------------------------------------------------------------------
    # Configuration (parametres PROPRES au module LMS)
    # ------------------------------------------------------------------
    @api.model
    def _get_config(self):
        icp = self.env['ir.config_parameter'].sudo()
        api_key = (icp.get_param('digii_lms_ai_agent.api_key') or '').strip()
        model = (icp.get_param('digii_lms_ai_agent.model')
                 or DEFAULT_MODEL).strip()
        base_url = (icp.get_param('digii_lms_ai_agent.base_url')
                    or DEFAULT_BASE_URL).strip()
        return {'api_key': api_key, 'model': model, 'base_url': base_url}

    @api.model
    def is_configured(self):
        """True si une cle API propre au LMS est presente."""
        return bool(self._get_config()['api_key'])

    @api.model
    def _get_client(self):
        cfg = self._get_config()
        _logger.info("[LMS AI] Modèle configuré utilisé : '%s' (base_url: %s)",
                     cfg['model'], cfg['base_url'])
        if not cfg['api_key']:
            raise LmsAiServiceError(_(
                "Clé API du tuteur LMS absente. Renseignez le paramètre "
                "système 'digii_lms_ai_agent.api_key' (Paramètres > "
                "Technique > Paramètres système)."
            ))
        try:
            from openai import OpenAI
        except ImportError:
            raise LmsAiServiceError(_(
                "La bibliothèque Python 'openai' n'est pas installée. "
                "Exécutez : pip install openai"
            ))
        return OpenAI(
            api_key=cfg['api_key'],
            base_url=cfg['base_url'],
            timeout=REQUEST_TIMEOUT,
        ), cfg['model']

    # ------------------------------------------------------------------
    # Appel principal (mode JSON, avec retry)
    # ------------------------------------------------------------------
    @api.model
    def chat_json(self, system_prompt, user_prompt,
                  temperature=DEFAULT_TEMPERATURE, max_retries=1):
        """Appelle Groq en mode JSON et retourne (dict, texte_brut)."""
        client, model = self._get_client()

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]

        last_raw = ''
        attempt = 0
        while attempt <= max_retries:
            attempt += 1
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    response_format={'type': 'json_object'},
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning('[LMS AI] Appel Groq echoue (tentative %s): %s',
                                attempt, exc)
                raise LmsAiServiceError(self._humanize_api_error(exc))

            last_raw = response.choices[0].message.content or ''
            try:
                return json.loads(last_raw), last_raw
            except (json.JSONDecodeError, TypeError) as exc:
                _logger.warning('[LMS AI] JSON invalide (tentative %s): %s',
                                attempt, exc)
                messages.append({'role': 'assistant', 'content': last_raw})
                messages.append({
                    'role': 'user',
                    'content': (
                        "Ta réponse précédente n'était pas un JSON valide. "
                        "Renvoie UNIQUEMENT un objet JSON valide, sans aucun "
                        "texte autour, sans balises markdown."
                    ),
                })

        raise LmsAiServiceError(_(
            "Le modèle IA n'a pas renvoyé de JSON exploitable après %s "
            "tentatives.", max_retries + 1))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _humanize_api_error(self, exc):
        """Traduit une exception SDK en message clair."""
        text = str(exc)
        low = text.lower()
        if 'rate limit' in low or '429' in low:
            return _("Limite de requêtes Groq atteinte. Réessayez dans "
                     "quelques instants.")
        if 'authentication' in low or '401' in low or 'invalid api key' in low:
            return _("Clé API Groq invalide. Vérifiez le paramètre système "
                     "'digii_lms_ai_agent.api_key'.")
        if 'not found' in low or '404' in low or 'does not exist' in low or \
                'decommission' in low or 'deprecat' in low:
            return _("Le modèle IA configuré n'existe plus chez Groq. "
                     "Changez 'digii_lms_ai_agent.model' pour un modèle "
                     "actuel (ex: openai/gpt-oss-120b).")
        if 'timeout' in low or 'timed out' in low:
            return _("Le serveur IA a mis trop de temps à répondre. Réessayez.")
        if 'connection' in low:
            return _("Impossible de contacter le serveur Groq. Vérifiez la "
                     "connexion réseau.")
        return _("Erreur lors de l'appel IA : %s", text[:300])
