# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class ExamCertificateRejectWizard(models.TransientModel):
    """
    Wizard pour rejeter un certificat avec un motif obligatoire.
    """
    _name = 'exam.certificate.reject.wizard'
    _description = 'Rejet de certificat'

    certificate_id = fields.Many2one(
        'exam.certificate',
        string='Certificat',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    rejection_reason = fields.Text(
        'Motif de rejet',
        required=True,
        help="Expliquez pourquoi ce certificat est rejeté.",
    )

    def action_confirm_reject(self):
        """Confirme le rejet avec le motif saisi."""
        self.ensure_one()
        if not self.rejection_reason or not self.rejection_reason.strip():
            raise UserError("Veuillez saisir un motif de rejet.")

        cert = self.certificate_id
        cert.write({
            'state': 'rejected',
            'rejection_reason': self.rejection_reason,
            'rejected_by': self.env.uid,
        })

        # Marquer l'examen lié comme rejeté
        if cert.user_input_id:
            cert.user_input_id.mark_exam_rejected(self.rejection_reason)

        # Enregistrer un strike pour ce candidat
        self.env['exam.strike'].record_strike(
            cert.partner_id, 'certificate_reject',
            reason=self.rejection_reason,
            survey=cert.survey_id, certificate=cert,
        )

        # Email désactivé pour le moment
        # template = self.env.ref(
        #     'digii_exam_manager.mail_template_certificate_rejected',
        #     raise_if_not_found=False,
        # )
        # if template:
        #     template.send_mail(self.certificate_id.id, force_send=True)

        return {'type': 'ir.actions.act_window_close'}
