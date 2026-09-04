from odoo import models, fields, api


class DigiiCourseCategory(models.Model):
    _name = 'digii.course.category'
    _description = 'Catégorie de Cours Personnalisée'
    _order = 'sequence, name'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(
        string='Nom de la Catégorie',
        required=True,
        translate=True
    )
    sequence = fields.Integer(
        string='Séquence',
        default=10
    )
    description = fields.Text(
        string='Description',
        translate=True
    )
    color = fields.Integer(
        string='Couleur',
        default=0
    )
    active = fields.Boolean(
        string='Actif',
        default=True
    )
    image = fields.Image(
        string='Image',
        max_width=256,
        max_height=256
    )

    # ── Relation avec slide.channel ─────────────────────
    channel_ids = fields.One2many(
        'slide.channel',
        'course_category_id',
        string='Cours liés'
    )
    channel_count = fields.Integer(
        string='Nombre de Cours',
        compute='_compute_channel_count',
        store=True
    )

    # ── Compute ─────────────────────────────────────────
    @api.depends('channel_ids')
    def _compute_channel_count(self):
        for rec in self:
            rec.channel_count = len(rec.channel_ids)

    # ── Action smart button ─────────────────────────────
    def action_view_channels(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Cours - {self.name}',
            'res_model': 'slide.channel',
            'view_mode': 'list,form,kanban',
            'domain': [('course_category_id', '=', self.id)],
            'context': {'default_course_category_id': self.id},
        }