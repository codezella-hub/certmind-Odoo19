# -*- coding: utf-8 -*-
"""
Service d'appel a l'API Groq (compatible OpenAI SDK).

Toute la configuration passe par ir.config_parameter :

    digii_exam_ai_agent.api_key     cle API Groq (jamais en dur)
    digii_exam_ai_agent.model       defaut: llama-3.3-70b-versatile
    digii_exam_ai_agent.base_url    defaut: https://api.groq.com/openai/v1

Le service expose une seule methode publique : `chat_json(system_prompt,
user_prompt)`. Elle force le mode JSON, parse la reponse, et reessaye une
fois si le JSON est invalide. Les erreurs sont levees sous forme de
AiAgentError avec un message clair, destine a etre renvoye au frontend.
"""
import json
import logging

from odoo import api, models, _

_logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'llama-3.3-70b-versatile'
DEFAULT_BASE_URL = 'https://api.groq.com/openai/v1'
DEFAULT_TEMPERATURE = 0.3
REQUEST_TIMEOUT = 60


class AiAgentError(Exception):
    """Erreur metier renvoyee proprement au frontend."""
    pass


class DigiiAiService(models.AbstractModel):
    _name = 'digii.ai.service'
    _description = "Service d'appel IA (Groq)"

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @api.model
    def _get_config(self):
        icp = self.env['ir.config_parameter'].sudo()
        api_key = (icp.get_param('digii_exam_ai_agent.api_key') or '').strip()
        model = (icp.get_param('digii_exam_ai_agent.model') or DEFAULT_MODEL).strip()
        base_url = (icp.get_param('digii_exam_ai_agent.base_url') or DEFAULT_BASE_URL).strip()
        return {'api_key': api_key, 'model': model, 'base_url': base_url}

    @api.model
    def is_configured(self):
        """True si une cle API est presente."""
        return bool(self._get_config()['api_key'])

    @api.model
    def _get_client(self):
        cfg = self._get_config()
        if not cfg['api_key']:
            raise AiAgentError(_(
                "Cle API Groq absente. Renseignez le parametre systeme "
                "'digii_exam_ai_agent.api_key' (Parametres > Technique > "
                "Parametres systeme)."
            ))
        try:
            from openai import OpenAI
        except ImportError:
            raise AiAgentError(_(
                "La bibliotheque Python 'openai' n'est pas installee. "
                "Executez: pip install openai"
            ))
        return OpenAI(
            api_key=cfg['api_key'],
            base_url=cfg['base_url'],
            timeout=REQUEST_TIMEOUT,
        ), cfg['model']

    # ------------------------------------------------------------------
    # Appel principal
    # ------------------------------------------------------------------

    @api.model
    def chat_json(self, system_prompt, user_prompt, temperature=DEFAULT_TEMPERATURE,
                  max_retries=1):
        """
        Appelle Groq en mode JSON et retourne un dict Python.

        En cas de JSON invalide, reessaye `max_retries` fois en rappelant
        le modele avec une consigne de correction. Leve AiAgentError sinon.

        Retourne un tuple (parsed_dict, raw_text) pour la tracabilite.
        """
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
                _logger.warning('[AI] Appel Groq echoue (tentative %s): %s', attempt, exc)
                raise AiAgentError(self._humanize_api_error(exc))

            last_raw = response.choices[0].message.content or ''
            try:
                return json.loads(last_raw), last_raw
            except (json.JSONDecodeError, TypeError) as exc:
                _logger.warning('[AI] JSON invalide (tentative %s): %s', attempt, exc)
                # On rappelle le modele en lui montrant son erreur.
                messages.append({'role': 'assistant', 'content': last_raw})
                messages.append({
                    'role': 'user',
                    'content': (
                        "Ta reponse precedente n'etait pas un JSON valide. "
                        "Renvoie UNIQUEMENT un objet JSON valide, sans aucun "
                        "texte autour, sans balises markdown."
                    ),
                })

        raise AiAgentError(_(
            "Le modele IA n'a pas renvoye de JSON exploitable apres %s tentatives.",
            max_retries + 1,
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _humanize_api_error(self, exc):
        """Traduit une exception SDK en message clair pour l'utilisateur."""
        text = str(exc)
        low = text.lower()
        if 'rate limit' in low or '429' in low:
            return _("Limite de requetes Groq atteinte. Reessayez dans quelques instants.")
        if 'authentication' in low or '401' in low or 'invalid api key' in low:
            return _("Cle API Groq invalide. Verifiez le parametre systeme.")
        if 'timeout' in low or 'timed out' in low:
            return _("Le serveur IA a mis trop de temps a repondre. Reessayez.")
        if 'connection' in low:
            return _("Impossible de contacter le serveur Groq. Verifiez la connexion reseau.")
        return _("Erreur lors de l'appel IA : %s", text[:300])
