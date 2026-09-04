# -*- coding: utf-8 -*-
"""
Ajout : recuperation AUTOMATIQUE des resultats d'analyse IA via cron.

Un cron Odoo appelle _cron_fetch_ai_results() toutes les 30 secondes.
Il parcourt les sessions en etat "processing" et va chercher leur
resultat aupres du microservice. Ainsi le procteur n'a PAS besoin de
cliquer "Rafraichir" : le resultat apparait tout seul (il suffit de
recharger la page, ou Odoo le montre au prochain rafraichissement).

Ce fichier COMPLETE exam_proctoring_session.py (meme modele, _inherit).
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ExamProctoringSessionCron(models.Model):
    _inherit = 'exam.proctoring.session'

    @api.model
    def _cron_fetch_ai_results(self):
        """
        Cron : recupere les resultats des analyses IA en cours.
        Appele automatiquement toutes les 30 secondes.
        """
        sessions = self.search([('ai_analysis_state', '=', 'processing')])
        if not sessions:
            return

        _logger.info('[Proctoring IA Cron] %d session(s) a verifier',
                     len(sessions))

        for session in sessions:
            try:
                # _fetch_ai_result_core met a jour la session si l'analyse
                # est terminee, sinon retourne 'not_ready' (reste en cours).
                session._fetch_ai_result_core()
            except Exception as exc:
                # On ne bloque pas le cron pour une session en erreur.
                _logger.warning(
                    '[Proctoring IA Cron] Session %s : %s',
                    session.id, exc,
                )
