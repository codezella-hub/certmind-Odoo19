# -*- coding: utf-8 -*-
"""
Correctif Mixed Content pour slide.slide.embed_code

Azure Container Apps ne transmet pas X-Forwarded-Proto. Odoo construit
alors l'URL de l'iframe en http://, bloquée par le navigateur.

La source du problème est le champ embed_code de slide.slide, qui utilise
base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

web.base.url est bien en https://, MAIS le code utilise parfois
request.httprequest.url_root à la place, qui est en http://.

On force https:// en remplaçant http:// dans embed_code.
"""
from odoo import api, models


class SlideSlide(models.Model):
    _inherit = 'slide.slide'

    @api.depends('url', 'slide_type', 'mime_type', 'channel_id')
    def _compute_embed_code(self):
        """Surcharge pour forcer https:// dans les URLs des iframes."""
        super()._compute_embed_code()
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', '')
        if base_url.startswith('https://'):
            for slide in self:
                if slide.embed_code and 'http://' in slide.embed_code:
                    slide.embed_code = slide.embed_code.replace(
                        'http://', 'https://')
