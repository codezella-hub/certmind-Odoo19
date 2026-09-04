# -*- coding: utf-8 -*-
"""
Extension de survey.question pour le workflow de validation IA.

Une question generee par l'IA arrive en etat 'proposed' avec
is_bank_question=False : elle n'entre donc PAS dans le pool de la banque
(le pool filtre sur is_bank_question=True). L'admin doit l'approuver pour
qu'elle bascule en banque officielle.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError


class SurveyQuestionAi(models.Model):
    _inherit = 'survey.question'

    ai_generated = fields.Boolean('Genere par IA', default=False, index=True)
    ai_validation_state = fields.Selection([
        ('proposed', 'Propose par IA'),
        ('approved', 'Approuve'),
        ('rejected', 'Rejete'),
        ('edited', 'Edite'),
    ], string='Validation IA', index=True)
    ai_generation_session_id = fields.Many2one(
        'digii.ai.generation.session', string='Session IA',
        ondelete='set null', index=True,
    )
    ai_confidence = fields.Selection([
        ('low', 'Faible'),
        ('medium', 'Moyenne'),
        ('high', 'Elevee'),
    ], string='Confiance IA')
    ai_explanation = fields.Text('Explication IA')

    # ------------------------------------------------------------------
    # Serialisation carte (frontend)
    # ------------------------------------------------------------------

    def _ai_card_data(self):
        self.ensure_one()
        answers = []
        for ans in self.suggested_answer_ids:
            answers.append({
                'id': ans.id,
                'text': ans.value or '',
                'correct': bool(ans.is_correct),
            })
        return {
            'id': self.id,
            'title': self.title or '',
            'type': self.question_type or 'simple_choice',
            'type_label': self._ai_type_label(),
            'difficulty': self.exam_difficulty or '',
            'difficulty_label': dict(
                self._fields['exam_difficulty'].selection).get(
                self.exam_difficulty, ''),
            'category': self.exam_category_id.name or '',
            'subcategory': self.exam_subcategory_id.name or '',
            'answers': answers,
            'explanation': self.ai_explanation or '',
            'confidence': self.ai_confidence or '',
            'validation_state': self.ai_validation_state or '',
        }

    def _ai_type_label(self):
        self.ensure_one()
        mapping = {
            'simple_choice': 'QCM (reponse unique)',
            'multiple_choice': 'QCM (choix multiple)',
        }
        return mapping.get(self.question_type, self.question_type or '')

    # ------------------------------------------------------------------
    # Application d'un payload IA (creation / regeneration)
    # ------------------------------------------------------------------

    def _ai_apply_payload(self, qd, session=None):
        """Remplace le contenu de la question avec un dict issu de l'IA."""
        self.ensure_one()
        Session = self.env['digii.ai.generation.session']
        qtype = qd.get('type')
        if qtype not in ('simple_choice', 'multiple_choice'):
            qtype = self.question_type or 'simple_choice'
        difficulty = qd.get('difficulty')
        if difficulty not in ('easy', 'medium', 'hard'):
            difficulty = self.exam_difficulty
        confidence = qd.get('confidence')
        if confidence not in ('low', 'medium', 'high'):
            confidence = self.ai_confidence

        cat_id, sub_id = Session._resolve_category(
            qd.get('category'), qd.get('subcategory'))

        # On reconstruit les reponses
        answer_cmds = [(5, 0, 0)]
        for ans in (qd.get('answers') or []):
            if not isinstance(ans, dict):
                continue
            text = (ans.get('text') or '').strip()
            if not text:
                continue
            is_ok = bool(ans.get('correct'))
            answer_cmds.append((0, 0, {
                'value': text,
                'is_correct': is_ok,
                'answer_score': 1.0 if is_ok else 0.0,
            }))

        vals = {
            'title': (qd.get('title') or self.title or '').strip(),
            'question_type': qtype,
            'exam_difficulty': difficulty,
            'ai_confidence': confidence,
            'ai_explanation': qd.get('explanation') or self.ai_explanation,
        }
        if cat_id:
            vals['exam_category_id'] = cat_id
        if sub_id:
            vals['exam_subcategory_id'] = sub_id
        if len(answer_cmds) > 1:
            vals['suggested_answer_ids'] = answer_cmds
        if session:
            vals['ai_generation_session_id'] = session.id
        self.write(vals)

    # ------------------------------------------------------------------
    # Actions de revue (approve / reject / edit)
    # ------------------------------------------------------------------

    def _check_bank_write_access(self):
        """Verifie que l'utilisateur peut ecrire sur la banque de questions."""
        try:
            self.check_access('write')
        except AccessError:
            raise AccessError(_(
                "Vous n'avez pas les droits pour modifier la banque de questions."))

    def ai_approve(self):
        """Approuve : la question entre dans la banque officielle."""
        for q in self:
            q._check_bank_write_access()
            if q.ai_validation_state not in ('proposed', 'edited'):
                raise UserError(_(
                    "Seules les questions proposees ou editees peuvent etre approuvees."))
            q.write({
                'ai_validation_state': 'approved',
                'is_bank_question': True,
            })
        return True

    def ai_reject(self):
        """Rejette : la question est archivee (active=False)."""
        for q in self:
            q._check_bank_write_access()
            q.write({
                'ai_validation_state': 'rejected',
                'is_bank_question': False,
                'active': False,
            })
        return True

    def ai_mark_edited(self):
        for q in self:
            if q.ai_generated:
                q.ai_validation_state = 'edited'
        return True

    # Actions appelees depuis les boutons de la vue liste/form de revue
    def action_ai_approve(self):
        self.ai_approve()
        return True

    def action_ai_reject(self):
        self.ai_reject()
        return True
