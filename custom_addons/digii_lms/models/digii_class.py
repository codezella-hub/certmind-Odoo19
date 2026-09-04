from odoo import api, models, fields

class DigiiClass(models.Model):
    _name = 'digii.class'
    _description = 'Classe LMS'

    name = fields.Char(string="Nom de la classe", required=True)

    description = fields.Text(string="Description")

    # Etudiants dans la classe
    student_ids = fields.Many2many(
        'res.users',
        string="Étudiants",
    )

    # Cours de la classe
    course_ids = fields.Many2many(
        'slide.channel',
        string="Cours"
    )

    active = fields.Boolean(default=True)

    # Compteurs pour les smart buttons (en-tete du formulaire)
    student_count = fields.Integer(compute='_compute_counts', string="Nb étudiants")
    course_count = fields.Integer(compute='_compute_counts', string="Nb cours")

    @api.depends('student_ids', 'course_ids')
    def _compute_counts(self):
        for rec in self:
            rec.student_count = len(rec.student_ids)
            rec.course_count = len(rec.course_ids)

    def action_open_courses(self):
        """Ouvre tous les cours de cette classe"""
        self.ensure_one()
        return {
            'name': 'Cours de la Classe',
            'type': 'ir.actions.act_window',
            'res_model': 'slide.channel',
            'view_mode': 'kanban,list,form',
            'domain': [('id', 'in', self.course_ids.ids)],
        }

    def action_open_students(self):
        """Ouvre tous les étudiants de cette classe"""
        self.ensure_one()
        return {
            'name': 'Étudiants de la Classe',
            'type': 'ir.actions.act_window',
            'res_model': 'res.users',
            'view_mode': 'kanban,list,form',
            'domain': [('id', 'in', self.student_ids.ids)],
        }
