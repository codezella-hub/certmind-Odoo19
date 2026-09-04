# -*- coding: utf-8 -*-
from . import models
from . import controllers

# Modeles Groq deprecies a remplacer automatiquement.
_DEPRECATED_MODELS = (
    'llama-3.3-70b-versatile',
    'llama-3.1-8b-instant',
)
_SAFE_MODEL = 'openai/gpt-oss-120b'


def _lms_ai_fix_model(*args):
    """
    A l'installation/mise a jour : si le modele configure pour le tuteur LMS
    est un modele deprecie par Groq, on le remplace par un modele actuel.
    Evite les erreurs 404 dues aux anciens modeles.

    Compatible Odoo 17 (cr, registry) et Odoo 18+ (env).
    """
    from odoo import api, SUPERUSER_ID
    # Odoo 18+ : un seul argument `env`. Odoo <=17 : (cr, registry).
    if len(args) == 1:
        env = args[0]
    else:
        cr = args[0]
        env = api.Environment(cr, SUPERUSER_ID, {})

    icp = env['ir.config_parameter'].sudo()
    current = (icp.get_param('digii_lms_ai_agent.model') or '').strip()
    if not current or current in _DEPRECATED_MODELS:
        icp.set_param('digii_lms_ai_agent.model', _SAFE_MODEL)
