# -*- coding: utf-8 -*-
from odoo import fields, models


class ExamCertificateTemplate(models.Model):
    """
    Template de certificat personnalisable.

    Permet de définir l'apparence du certificat PDF :
    - Logo, couleurs, textes
    - Un template peut être marqué comme "par défaut" (is_default)
    - Chaque examen peut override le template global via certificate_template_id
    """
    _name = 'exam.certificate.template'
    _description = 'Template de certificat'
    _order = 'is_default desc, name'

    name = fields.Char('Nom du template', required=True)
    is_default = fields.Boolean(
        'Template par défaut',
        default=False,
        help="S'il n'y a pas de template spécifique sur l'examen, celui-ci sera utilisé.",
    )
    active = fields.Boolean('Actif', default=True)

    # Apparence
    logo = fields.Binary('Logo', attachment=True)
    header_color = fields.Char(
        'Couleur principale',
        default='#1B3F6B',
        help="Code couleur hexadécimal pour les titres et accents du certificat.",
    )
    header_text_color = fields.Char(
        'Couleur texte entête',
        default='#FFFFFF',
    )

    # --- Fond / arrière-plan du certificat (mode paysage) ---
    use_background = fields.Boolean(
        'Utiliser une image de fond',
        default=True,
        help="Si activé, le certificat est généré en mode paysage avec une "
             "image de fond pleine page. Sinon, le style classique est utilisé.",
    )
    background_image = fields.Binary(
        'Image de fond (override)',
        attachment=True,
        help="Image de fond personnalisée pour ce template (mode paysage, "
             "format A4 recommandé : 1403x992 px). Laissez vide pour utiliser "
             "le fond fourni par défaut avec le module.",
    )
    body_text_color = fields.Char(
        'Couleur du texte du corps',
        default='#1a1a1a',
        help="Couleur du texte affiché par-dessus l'image de fond.",
    )
    accent_color = fields.Char(
        'Couleur d\'accent',
        default='#5B2EC4',
        help="Couleur secondaire (soulignement du nom, libellés).",
    )

    # Contenu
    title_text = fields.Char(
        'Titre du certificat',
        default='Certificat de réussite',
        translate=True,
    )
    body_text = fields.Text(
        'Texte du corps',
        default=(
            "Nous certifions que {candidate} a réussi avec succès "
            "l'examen « {exam} » avec un score de {score}% "
            "le {date}."
        ),
        translate=True,
        help=(
            "Variables disponibles : {candidate}, {exam}, {score}, {date}, "
            "{certificate_number}"
        ),
    )
    footer_text = fields.Text(
        'Pied de page / Signataire',
        default='Direction des examens',
        translate=True,
    )
    signatory_name = fields.Char('Nom du signataire', translate=True)
    signatory_title = fields.Char('Titre du signataire', translate=True)
    signature_image = fields.Binary('Signature (image)', attachment=True)
