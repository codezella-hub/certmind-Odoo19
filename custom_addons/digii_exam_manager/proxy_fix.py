# -*- coding: utf-8 -*-
"""
Correctif proxy pour Azure Container Apps.

Odoo n'applique proxy_mode (ProxyFix) que si l'en-tête X-Forwarded-Host
est présent. L'ingress Azure Container Apps envoie X-Forwarded-Proto
mais PAS X-Forwarded-Host : Odoo croit donc être servi en http://.
Conséquence : les iframes des cours PDF (/slides/embed/...) sont
générées en http:// et bloquées par le navigateur (Mixed Content).

Ce patch recopie Host dans X-Forwarded-Host quand il manque, pour
que la logique proxy_mode native d'Odoo s'applique normalement.
"""
from odoo import http

if not getattr(http.Application, '_certmind_proxy_patched', False):
    _original_call = http.Application.__call__

    def _certmind_call(self, environ, start_response):
        if environ.get('HTTP_X_FORWARDED_PROTO') and not environ.get('HTTP_X_FORWARDED_HOST'):
            environ['HTTP_X_FORWARDED_HOST'] = environ.get('HTTP_HOST', '')
        return _original_call(self, environ, start_response)

    http.Application.__call__ = _certmind_call
    http.Application._certmind_proxy_patched = True
