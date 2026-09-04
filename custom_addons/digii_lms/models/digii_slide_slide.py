from odoo import models


class DigiiSlideSlide(models.Model):
    _inherit = 'slide.slide'

    def action_publish_slide(self):
        for rec in self:
            rec.is_published = True

    def action_unpublish_slide(self):
        for rec in self:
            rec.is_published = False