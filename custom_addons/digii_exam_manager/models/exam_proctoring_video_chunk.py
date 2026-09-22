# -*- coding: utf-8 -*-
"""
Enregistrement video PAR MORCEAUX.

Avant : le navigateur gardait toute la video en memoire et l'envoyait en
un seul bloc a la fin de l'examen. Pour un examen de 30 min (~125 Mo),
l'envoi etait long, depassait les limites (taille Odoo, delai de l'ingress
Azure) et etait coupe par la redirection vers /my/exams.

Maintenant : le navigateur envoie un morceau (~1 Mo) toutes les 15 s
pendant l'examen. Chaque morceau est stocke en ir.attachment. A la fin,
les morceaux sont concatenes dans video_recording (les morceaux WebM
produits par MediaRecorder avec un timeslice se concatenent tels quels).

Si le candidat ferme l'onglet avant la fin, un CRON assemble les
morceaux deja recus : on ne perd au pire que les 15 dernieres secondes.
"""
import base64
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CHUNK_MARKER = 'digii_proctoring_video_chunk'
# Taille max d'un morceau (15 s a ~0,6 Mbit/s = ~1 Mo ; marge large).
MAX_CHUNK_BYTES = 20 * 1024 * 1024
# Delai sans nouveau morceau avant que le CRON assemble la video.
ORPHAN_DELAY_MINUTES = 3


class ExamProctoringSessionVideoChunk(models.Model):
    _inherit = 'exam.proctoring.session'

    video_chunk_last_upload = fields.Datetime(
        'Dernier morceau video recu', readonly=True, copy=False)
    video_finalized = fields.Boolean(
        'Video assemblee', readonly=True, copy=False,
        help="Vrai quand les morceaux ont ete assembles dans la video finale.")

    def _video_chunk_domain(self):
        self.ensure_one()
        return [
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('description', '=', CHUNK_MARKER),
        ]

    def store_video_chunk(self, index, data):
        """Enregistre un morceau. Idempotent : un renvoi remplace l'ancien."""
        self.ensure_one()
        if self.video_finalized:
            raise UserError("La video de cette session est deja finalisee.")
        if not data:
            raise UserError("Morceau vide.")
        if len(data) > MAX_CHUNK_BYTES:
            raise UserError("Morceau trop volumineux.")

        Attachment = self.env['ir.attachment'].sudo()
        name = 'video_chunk_%05d.webm' % index
        Attachment.search(self._video_chunk_domain() + [('name', '=', name)]).unlink()
        Attachment.create({
            'name': name,
            'raw': data,
            'res_model': self._name,
            'res_id': self.id,
            'description': CHUNK_MARKER,
            'mimetype': 'video/webm',
        })
        self.sudo().write({'video_chunk_last_upload': fields.Datetime.now()})
        return True

    def finalize_video_chunks(self):
        """Concatene les morceaux dans video_recording. Retourne True si video."""
        self.ensure_one()
        if self.video_finalized:
            return bool(self.video_recording)

        chunks = self.env['ir.attachment'].sudo().search(
            self._video_chunk_domain(), order='name asc')
        if not chunks:
            return False

        indexes = [int(c.name[len('video_chunk_'):-len('.webm')]) for c in chunks]
        missing = sorted(set(range(indexes[-1] + 1)) - set(indexes))
        if missing:
            _logger.warning('[Proctoring video] Session %s : morceaux manquants %s',
                            self.id, missing)

        data = b''.join(chunk.raw or b'' for chunk in chunks)
        self.sudo().write({
            'video_recording': base64.b64encode(data),
            'video_filename': 'recording_%s.webm' % (self.name or self.id),
            'video_finalized': True,
        })
        chunks.unlink()
        _logger.info('[Proctoring video] Session %s : %d morceaux assembles (%d octets)',
                     self.id, len(indexes), len(data))
        return True

    @api.model
    def _cron_finalize_video_chunks(self):
        """Assemble les videos dont l'envoi s'est arrete (onglet ferme...)."""
        limit = fields.Datetime.now() - timedelta(minutes=ORPHAN_DELAY_MINUTES)
        sessions = self.sudo().search([
            ('video_finalized', '=', False),
            ('video_chunk_last_upload', '!=', False),
            ('video_chunk_last_upload', '<', limit),
        ])
        for session in sessions:
            try:
                session.finalize_video_chunks()
                self.env.cr.commit()
            except Exception:  # noqa: BLE001
                self.env.cr.rollback()
                _logger.exception('[Proctoring video] Echec assemblage session %s',
                                  session.id)
