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
        # Domaine calculé : on filtre sur le groupe natif plutôt que sur
        # un champ maison. `group_ids` inclut les groupes impliqués, donc
        # un administrateur (qui implique Professeur) reste sélectionnable.
        domain=lambda self: [
            ('all_group_ids', 'in',
             self.env.ref('digii_lms.group_lms_professor').ids)],
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