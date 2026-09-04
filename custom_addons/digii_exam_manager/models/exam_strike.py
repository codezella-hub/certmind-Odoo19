# -*- coding: utf-8 -*-
"""
Strikes (sanctions) candidats.

Un « strike » est enregistré chaque fois qu'un candidat est sanctionné sur un
examen :
    - proctoring_reject : rejeté en salle d'attente / avant de démarrer
    - exclusion         : exclu en cours d'examen par le procteur
    - certificate_reject: certificat rejeté après visionnage de la vidéo

Le modèle sert de journal détaillé (une ligne = un strike) ET de base aux
compteurs par candidat (vue liste groupée + pivot + smart button sur la fiche
contact). On compte ainsi facilement le nombre de strikes de chaque utilisateur.
"""
from odoo import api, fields, models


class ExamStrike(models.Model):
    _name = 'exam.strike'
    _description = "Strike / Sanction candidat"
    _order = 'create_date desc'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one(
        'res.partner', string='Candidat',
        required=True, ondelete='cascade', index=True,
    )
    user_id = fields.Many2one(
        'res.users', string='Utilisateur', readonly=True,
    )
    survey_id = fields.Many2one(
        'survey.survey', string='Examen',
        ondelete='set null', readonly=True,
    )
    session_id = fields.Many2one(
        'exam.proctoring.session', string='Session de proctoring',
        ondelete='set null', readonly=True,
    )
    certificate_id = fields.Many2one(
        'exam.certificate', string='Certificat',
        ondelete='set null', readonly=True,
    )

    strike_type = fields.Selection([
        ('proctoring_reject',  'Rejet (salle d\'attente)'),
        ('exclusion',          'Exclusion (en examen)'),
        ('certificate_reject', 'Rejet du certificat'),
    ], string='Type', required=True, default='proctoring_reject')

    reason = fields.Text('Motif')
    proctor_id = fields.Many2one(
        'res.users', string='Procteur',
        default=lambda self: self.env.uid, readonly=True,
    )
    date = fields.Datetime(
        'Date', default=fields.Datetime.now, readonly=True,
    )

    # ------------------------------------------------------------------
    # Helper central : enregistre un strike
    # ------------------------------------------------------------------
    @api.model
    def record_strike(self, partner, strike_type, reason='',
                      survey=None, session=None, certificate=None):
        """Crée un strike pour `partner`. Tolérant : ne lève jamais d'erreur
        bloquante (un échec d'écriture du strike ne doit pas casser le rejet)."""
        if not partner:
            return self.browse()
        partner_id = partner.id if hasattr(partner, 'id') else partner
        user = self.env['res.users'].sudo().search(
            [('partner_id', '=', partner_id)], limit=1)
        return self.sudo().create({
            'partner_id':     partner_id,
            'user_id':        user.id if user else False,
            'survey_id':      survey.id if survey else False,
            'session_id':     session.id if session else False,
            'certificate_id': certificate.id if certificate else False,
            'strike_type':    strike_type,
            'reason':         reason or '',
        })
