# -*- coding: utf-8 -*-
"""
Extensions de res.users pour le LMS.

Les rôles ne sont plus gérés par un champ maison : on utilise le système
natif d'Odoo (groupes et permissions), visible dans l'onglet « Droits
d'accès » du formulaire utilisateur. Les quatre rôles du projet sont
définis dans security/lms_groups.xml et partagent un même privilège, ce
qui les fait apparaître dans une seule liste déroulante.

Ce fichier ne conserve que l'avatar affiché dans l'en-tête du portail.
"""
from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # ── Avatar de l'en-tête (initiales + couleur déterministe) ────────
    lms_initials = fields.Char(
        string="Initiales LMS", compute='_compute_lms_avatar')
    lms_avatar_color = fields.Char(
        string="Couleur avatar LMS", compute='_compute_lms_avatar')

    @api.depends('name')
    def _compute_lms_avatar(self):
        palette = [
            '#2C5F8D', '#E67E22', '#27AE60', '#8E44AD', '#C0392B',
            '#16A085', '#D35400', '#2980B9', '#2C3E50', '#F39C12',
        ]
        for user in self:
            name = (user.name or '?').strip()
            parts = [p for p in name.split() if p]
            if parts:
                initials = parts[0][:1]
                if len(parts) > 1:
                    initials += parts[1][:1]
            else:
                initials = '?'
            user.lms_initials = initials.upper()
            user.lms_avatar_color = palette[sum(map(ord, name)) % len(palette)]
