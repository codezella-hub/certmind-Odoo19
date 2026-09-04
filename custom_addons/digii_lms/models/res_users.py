from odoo import models, fields, api
import hashlib

class ResUsers(models.Model):
    _inherit = 'res.users'
    lms_group = fields.Selection([ ('admin', 'Administrateur'),
                                   ('professor', 'Professeur'),
                                   ('student', 'Étudiant'), ],
                                 string='Groupe LMS', required=True,
                                 default='student')

    # ── Avatar header (initiales + couleur déterministe) ──────────────
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
            digest = hashlib.md5(name.encode('utf-8')).hexdigest()
            user.lms_avatar_color = palette[int(digest, 16) % len(palette)]

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        for user in users:
            user._assign_lms_groups()
            return users
    def write(self, vals):
        res = super().write(vals)
        if 'lms_group' in vals:
            for user in self:
                user._assign_lms_groups()
                return res
    def _assign_lms_groups(self):
        group_admin = self.env.ref('digii_lms.group_lms_admin')
        group_professor = self.env.ref('digii_lms.group_lms_professor')
        group_student = self.env.ref('digii_lms.group_lms_student')
        all_groups = [group_admin, group_professor, group_student] # sudo() obligatoire pour modifier les groupes user_sudo = self.sudo() # Retirer tous les groupes LMS for g in all_groups: if g in user_sudo.groups_id: user_sudo.groups_id = [(3, g.id)] # Ajouter le bon groupe mapping = { 'admin': group_admin, 'professor': group_professor, 'student': group_student, } group = mapping.get(self.lms_group) if group: user_sudo.groups_id = [(4, group.id)]