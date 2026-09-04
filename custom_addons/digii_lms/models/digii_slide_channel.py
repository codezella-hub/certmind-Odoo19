from odoo import models, fields, api
class DigiiSlideChannel(models.Model):
    _inherit = 'slide.channel'


    custom_difficulty = fields.Selection([
        ('beginner', 'Débutant'),
        ('intermediate', 'Intermédiaire'),
        ('advanced', 'Avancé'),
        ('expert', 'Expert'),
    ], string='Niveau', default='beginner', tracking=True)

    custom_language = fields.Selection([
        ('fr', 'Français'),
        ('en', 'Anglais'),
        ('ar', 'Arabe'),
        ('es', 'Espagnol'),
    ], string='Langue', default='fr')

    custom_prerequisites = fields.Text(
        string='Prérequis',
        translate=True
    )

    # ── Relation avec digii.course.category ─────────────────────
    course_category_id = fields.Many2one(
        'digii.course.category',
        string='Catégorie',
        ondelete='set null',
        index=True,
        tracking=True
    )
    professor_ids = fields.Many2many(
        'res.users',
        string="Professeurs",
        domain="[('lms_group','=','professor')]"
    )
    # ── Méthodes publication ────────────────────────────
    def action_publish(self):
        for rec in self:
            rec.is_published = True

    def action_unpublish(self):
        for rec in self:
            rec.is_published = False

    def action_publish_all_slides(self):
        """Publier le cours ET toutes ses leçons"""
        for rec in self:
            rec.is_published = True
            rec.slide_ids.filtered(
                lambda s: not s.is_category
            ).write({'is_published': True})