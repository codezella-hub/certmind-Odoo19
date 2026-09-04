from odoo import models, fields


class DigiiSlideChannelPartner(models.Model):
    _inherit = 'slide.channel.partner'

    custom_enrollment_source = fields.Selection([
        ('self', 'Auto-inscription'),
        ('admin', 'Par Administrateur'),
        ('invitation', 'Par Invitation'),
    ], string='Source d\'Inscription', default='self')

    custom_notes = fields.Text(
        string='Notes'
    )