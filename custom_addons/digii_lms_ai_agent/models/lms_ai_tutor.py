# -*- coding: utf-8 -*-
"""
Cerveau de l'agent tuteur : lit le contenu d'une lecon et interroge l'IA.

Lecture du contenu par phases (cf. discussion) :
  - Phase 1 : TEXTE (html_content, description) -> direct
  - Phase 2 : PDF -> extraction du texte
  - Phase 3 : VIDEO -> description texte si dispo (transcription = futur)

Utilise le service IA dédié au LMS (digii.lms.ai.service).
"""
import logging
import re

from odoo import api, models, _

_logger = logging.getLogger(__name__)

# Longueur max du contenu envoye a l'IA (evite de saturer le contexte).
MAX_CONTENT_CHARS = 8000


class LmsAiTutor(models.AbstractModel):
    _name = 'digii.lms.ai.tutor'
    _description = "Service tuteur IA (lecture de contenu + appels IA)"

    # ------------------------------------------------------------------
    # Lecture du contenu d'une lecon (le coeur du systeme)
    # ------------------------------------------------------------------
    @api.model
    def _extract_slide_text(self, slide):
        """
        Retourne le texte lisible d'une lecon, selon son type.
        Phase 1 (texte) prioritaire ; PDF et video en complement.
        """
        if not slide:
            return ''

        parts = []
        # Titre + description : toujours utiles comme contexte.
        if slide.name:
            parts.append("Titre de la leçon : %s" % slide.name)
        desc = self._html_to_text(getattr(slide, 'description', '') or '')
        if desc:
            parts.append(desc)

        # --- Phase 1 : contenu texte / article (html_content) ---
        html = getattr(slide, 'html_content', '') or ''
        text = self._html_to_text(html)
        if text:
            parts.append(text)

        # --- Phase 2 : PDF (extraction du texte) ---
        slide_type = getattr(slide, 'slide_category', False) or \
            getattr(slide, 'slide_type', False)
        if slide_type in ('document', 'infographic') and getattr(
                slide, 'datas', False):
            pdf_text = self._extract_pdf_text(slide)
            if pdf_text:
                parts.append(pdf_text)

        # --- Phase 3 : video -> on se contente de la description pour l'instant.
        # (La transcription audio est une evolution future.)

        content = "\n\n".join(p for p in parts if p).strip()
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "\n[...contenu tronqué...]"
        return content

    @api.model
    def _html_to_text(self, html):
        """Convertit du HTML en texte lisible (simple, sans dependance)."""
        if not html:
            return ''
        # Retire les balises script/style entierement.
        html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html,
                      flags=re.DOTALL | re.IGNORECASE)
        # Remplace les <br> et </p> par des sauts de ligne.
        html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</p>', '\n', html, flags=re.IGNORECASE)
        # Retire toutes les autres balises.
        text = re.sub(r'<[^>]+>', ' ', html)
        # Decode quelques entites courantes.
        for ent, char in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'),
                          ('&gt;', '>'), ('&quot;', '"'), ('&#39;', "'")):
            text = text.replace(ent, char)
        # Normalise les espaces.
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        return text.strip()

    @api.model
    def _extract_pdf_text(self, slide):
        """Extrait le texte d'une lecon PDF (base64 dans slide.datas)."""
        try:
            import base64
            import io
            data = base64.b64decode(slide.datas)
            # pypdf est generalement disponible dans Odoo.
            try:
                from pypdf import PdfReader
            except ImportError:
                from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(data))
            pages = []
            for page in reader.pages[:20]:  # 20 premieres pages suffisent
                pages.append(page.extract_text() or '')
            return "\n".join(pages).strip()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[LMS IA] Extraction PDF échouée : %s", exc)
            return ''

    # ------------------------------------------------------------------
    # Appel au tuteur IA (repond a une question sur la lecon)
    # ------------------------------------------------------------------
    @api.model
    def ask_tutor(self, slide, question, history=None):
        """
        Pose une question au tuteur sur une lecon donnee.
        `history` : liste de dicts {role, content} pour le contexte.
        Retourne le texte de la reponse.
        """
        service = self.env['digii.lms.ai.service'].sudo()
        if not service.is_configured():
            return _("Le tuteur IA n'est pas encore configuré. "
                     "Contactez votre administrateur.")

        content = self._extract_slide_text(slide)
        lang_hint = self._detect_lang(question)

        system_prompt = (
            "Tu es un tuteur pédagogique bienveillant qui aide un étudiant à "
            "comprendre le contenu d'un cours en ligne. Réponds de manière "
            "claire, pédagogique et encourageante. Base-toi EN PRIORITÉ sur le "
            "contenu de la leçon fourni ci-dessous. Si la question sort du "
            "contenu, tu peux aider mais précise-le. Donne des exemples "
            "concrets. Ne donne jamais les réponses d'un examen officiel ; "
            "aide l'étudiant à COMPRENDRE, pas à tricher. "
            "Réponds dans la langue de la question (%s).\n\n"
            "=== CONTENU DE LA LEÇON ===\n%s\n=== FIN DU CONTENU ==="
            % (lang_hint, content or "(contenu non disponible)")
        )

        # Construit le prompt utilisateur avec un peu d'historique.
        convo = []
        for msg in (history or [])[-6:]:  # 3 derniers echanges max
            who = "Étudiant" if msg.get('role') == 'user' else "Tuteur"
            convo.append("%s : %s" % (who, msg.get('content', '')))
        convo.append("Étudiant : %s" % question)
        user_prompt = "\n".join(convo)

        # On demande une reponse JSON {"answer": "..."} pour rester robuste.
        system_json = system_prompt + (
            "\n\nRéponds UNIQUEMENT avec un objet JSON de la forme "
            '{"answer": "ta réponse ici"}.'
        )
        try:
            data, _raw = service.chat_json(system_json, user_prompt,
                                           temperature=0.5)
            return (data.get('answer') or '').strip() or _(
                "Je n'ai pas su formuler de réponse. Reformule ta question ?")
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[LMS IA] ask_tutor a échoué : %s", exc)
            return _("Une erreur est survenue en interrogeant le tuteur. "
                     "Réessaie dans un instant.")

    @api.model
    def _detect_lang(self, text):
        """Detection tres simple de la langue (fr par defaut)."""
        t = (text or '').lower()
        # Quelques mots anglais frequents.
        en_markers = (' the ', ' what ', ' how ', ' why ', ' is ', ' are ',
                      'explain', 'give me')
        if any(m in ' %s ' % t for m in en_markers):
            return 'anglais'
        return 'français'
