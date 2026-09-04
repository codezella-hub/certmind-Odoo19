from odoo import models

class Forum(models.Model):
    _inherit = 'forum.forum'

class ForumPost(models.Model):
    _inherit = 'forum.post'