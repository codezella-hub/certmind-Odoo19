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
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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


    # ── Cohérence portail / utilisateur interne ───────────────────────
    #
    # Odoo déclare `base.group_user` (Utilisateur interne) et
    # `base.group_portal` (Portail) mutuellement exclusifs. Or :
    #
    #   • à la création, Odoo attribue d'office l'utilisateur interne ;
    #   • cocher « Étudiant » ajoute le portail, via implied_ids.
    #
    # D'où l'erreur :
    #   « cannot be at the same time in exclusive groups
    #     'Role / User', 'Role / Portal' »
    #
    # Le widget natif ne peut pas résoudre seul ce conflit : il faudrait
    # décocher manuellement le groupe contraire, qui n'est même pas
    # affiché puisque la liste est filtrée sur les rôles du projet.
    #
    # On retire donc le groupe contraire automatiquement, AVANT que la
    # contrainte ne soit évaluée.

    def _ajuster_groupes_exclusifs(self, commandes):
        """
        Complète les commandes ORM pour retirer le groupe de base
        contraire au rôle demandé.

        Retourne la liste de commandes ajustée, ou None si le rôle n'est
        pas modifié (rien à faire).
        """
        etudiant = self.env.ref('digii_lms.group_lms_student',
                                raise_if_not_found=False)
        if not etudiant:
            return None

        interne = self.env.ref('base.group_user')
        portail = self.env.ref('base.group_portal')

        # Reconstituer l'ensemble des groupes visé par les commandes.
        cible = set()
        remplace = False
        for cmd in commandes:
            if not isinstance(cmd, (list, tuple)) or not cmd:
                continue
            code = cmd[0]
            if code == 6:                     # remplacement complet
                cible = set(cmd[2] or [])
                remplace = True
            elif code == 4:                   # ajout
                cible.add(cmd[1])
            elif code == 3:                   # retrait
                cible.discard(cmd[1])
            elif code == 5:                   # tout retirer
                cible = set()
                remplace = True

        # Sans remplacement complet, les groupes actuels restent en place.
        if not remplace:
            cible |= set(self.group_ids.ids)

        veut_portail = etudiant.id in cible
        contraire = interne if veut_portail else portail
        souhaite = portail if veut_portail else interne

        ajustees = list(commandes)
        # Retrait AVANT ajout : l'ORM applique les commandes dans l'ordre.
        ajustees.append((3, contraire.id))
        ajustees.append((4, souhaite.id))
        return ajustees

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('group_ids'):
                ajustees = self.browse()._ajuster_groupes_exclusifs(
                    vals['group_ids'])
                if ajustees is not None:
                    vals['group_ids'] = ajustees
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('group_ids'):
            # Un par un : les groupes actuels diffèrent d'un compte à l'autre.
            for user in self:
                v = dict(vals)
                ajustees = user._ajuster_groupes_exclusifs(vals['group_ids'])
                if ajustees is not None:
                    v['group_ids'] = ajustees
                super(ResUsers, user).write(v)
            return True
        return super().write(vals)


    # ── Invitation par courriel ───────────────────────────────────────
    def action_lms_send_invitation(self):
        """
        Envoie l'invitation NATIVE d'Odoo (module auth_signup).

        Le destinataire reçoit un lien à usage unique et définit
        lui-même son mot de passe. Préférable à la transmission d'un
        mot de passe en clair, qui resterait dans sa boîte de réception.

        On se contente de vérifier l'adresse avant de déléguer :
        `action_reset_password` échouerait avec un message peu clair sur
        un compte sans courriel.
        """
        sans_email = self.filtered(lambda u: not u.email)
        if sans_email:
            raise UserError(_(
                "Impossible d'envoyer l'invitation : aucune adresse "
                "électronique n'est renseignée pour %s.",
                ', '.join(sans_email.mapped('name'))))
        return self.action_reset_password()
