# -*- coding: utf-8 -*-
"""
Conversations du tuteur IA cote etudiant (portail LMS).

Historique enrichi par rapport a l'agent examen :
  - rattachement au cours et a la lecon (organisation par cours)
  - favori / epingle
  - titre renommable
  - recherche (via le champ name + le contenu des messages)
  - suppression (une conversation ou tout l'historique)

Chaque etudiant ne voit QUE ses propres conversations (record rules).
"""
from odoo import api, fields, models


class LmsAiChatSession(models.Model):
    _name = 'digii.lms.ai.chat.session'
    _description = "Conversation avec le tuteur IA"
    _order = 'is_pinned desc, write_date desc'

    name = fields.Char(
        "Titre", default="Nouvelle conversation",
        help="Titre de la conversation. Généré automatiquement à partir de "
             "la première question, mais renommable par l'étudiant.")
    user_id = fields.Many2one(
        'res.users', string="Étudiant", required=True,
        default=lambda self: self.env.user, index=True, ondelete='cascade')

    # Rattachement au contexte pedagogique (organisation par cours).
    channel_id = fields.Many2one(
        'slide.channel', string="Cours", index=True, ondelete='set null',
        help="Cours auquel se rapporte la conversation.")
    slide_id = fields.Many2one(
        'slide.slide', string="Leçon", ondelete='set null',
        help="Leçon précise sur laquelle porte la conversation.")

    # Historique enrichi.
    is_pinned = fields.Boolean(
        "Épinglé", default=False,
        help="Les conversations épinglées apparaissent en premier.")

    message_ids = fields.One2many(
        'digii.lms.ai.chat.message', 'session_id', string="Messages")
    message_count = fields.Integer(
        "Nb messages", compute='_compute_message_count', store=True)

    @api.depends('message_ids')
    def _compute_message_count(self):
        for session in self:
            session.message_count = len(session.message_ids)

    def _auto_title_from(self, question):
        """Genere un titre court a partir de la premiere question."""
        self.ensure_one()
        if self.name and self.name != "Nouvelle conversation":
            return
        text = (question or '').strip().replace('\n', ' ')
        if text:
            self.name = (text[:57] + '...') if len(text) > 60 else text


class LmsAiChatMessage(models.Model):
    _name = 'digii.lms.ai.chat.message'
    _description = "Message du tuteur IA"
    _order = 'create_date asc, id asc'

    session_id = fields.Many2one(
        'digii.lms.ai.chat.session', string="Conversation",
        required=True, ondelete='cascade', index=True)
    role = fields.Selection(
        [('user', "Étudiant"), ('assistant', "Tuteur IA")],
        string="Rôle", required=True)
    content = fields.Text("Contenu", required=True)

    # Favori : l'etudiant marque une reponse utile pour la retrouver.
    is_favorite = fields.Boolean(
        "Favori", default=False,
        help="Réponses marquées comme utiles par l'étudiant.")
