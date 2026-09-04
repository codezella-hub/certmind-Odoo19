# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    exam_strike_ids = fields.One2many(
        'exam.strike', 'partner_id', string='Strikes',
    )
    exam_strike_count = fields.Integer(
        'Nombre de strikes', compute='_compute_exam_strike_count',
    )

    @api.depends('exam_strike_ids')
    def _compute_exam_strike_count(self):
        # Comptage groupé en une seule requête
        data = self.env['exam.strike']._read_group(
            [('partner_id', 'in', self.ids)],
            groupby=['partner_id'], aggregates=['__count'],
        )
        mapping = {partner.id: count for partner, count in data}
        for partner in self:
            partner.exam_strike_count = mapping.get(partner.id, 0)

    def action_view_exam_strikes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Strikes de %s' % self.name,
            'res_model': 'exam.strike',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
