# -*- coding: utf-8 -*-
"""
report.py — Generation du rapport PDF HUMAIN et PROFESSIONNEL.

Ameliorations design :
  - En-tete avec nom du systeme + date de generation
  - Bloc infos : candidat, examen, date de passage
  - Jauge visuelle du score (barre 0-100 graduee)
  - Code couleur par gravite dans le tableau
  - Accents francais corrects
  - Espacement aere et hierarchie visuelle claire
"""
import logging
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable,
)

from .proctoring_config import settings
from .schemas import AnalysisResult, RiskLevel

logger = logging.getLogger(__name__)

_RISK_COLORS = {
    RiskLevel.NONE: colors.HexColor("#1D9E75"),
    RiskLevel.SUSPECT: colors.HexColor("#E67E22"),
    RiskLevel.HIGH: colors.HexColor("#D85A30"),
    RiskLevel.VERY_HIGH: colors.HexColor("#C0392B"),
}

_RISK_LABELS = {
    RiskLevel.NONE: "Aucun risque",
    RiskLevel.SUSPECT: "À surveiller",
    RiskLevel.HIGH: "Très suspect",
    RiskLevel.VERY_HIGH: "Triche probable",
}

# Description humaine de chaque comportement + gravite + couleur.
_EVENT_HUMAN = {
    "multiple_persons": (
        "Une autre personne dans la pièce",
        "Le système a vu quelqu'un d'autre que le candidat devant la caméra.",
    ),
    "phone_detected": (
        "Téléphone visible",
        "Un téléphone portable est apparu dans le champ de la caméra.",
    ),
    "paper_detected": (
        "Papier ou notes",
        "Des documents papier ont été aperçus près du candidat.",
    ),
    "face_absent": (
        "Candidat absent de l'écran",
        "Le visage du candidat n'était plus visible devant la caméra.",
    ),
    "gaze_off_screen": (
        "Regard détourné de l'écran",
        "Le candidat a regardé sur les côtés, en dehors de son écran.",
    ),
    "gaze_down": (
        "Regard vers le bas",
        "Le candidat a souvent baissé les yeux (peut regarder des notes, "
        "ou simplement réfléchir).",
    ),
    "head_agitation": (
        "Mouvements de tête fréquents",
        "La tête du candidat a beaucoup bougé (peut être du stress).",
    ),
    "voice_detected": (
        "Voix entendue",
        "Une voix a été captée par le microphone pendant l'examen.",
    ),
}

# Gravite : 3=grave (rouge), 2=moyen (orange), 1=faible (gris/vert)
_EVENT_SEVERITY = {
    "multiple_persons": 3,
    "phone_detected": 3,
    "face_absent": 3,
    "voice_detected": 2,
    "paper_detected": 2,
    "gaze_off_screen": 2,
    "gaze_down": 1,
    "head_agitation": 1,
}

_SEVERITY_COLORS = {
    3: colors.HexColor("#FADBD8"),  # rouge clair
    2: colors.HexColor("#FDEBD0"),  # orange clair
    1: colors.HexColor("#F4F6F7"),  # gris clair
}


class ScoreGauge(Flowable):
    """Jauge visuelle horizontale du score (barre 0-100 graduee)."""

    def __init__(self, score, level_color, width=16 * cm, height=1.1 * cm):
        super().__init__()
        self.score = score
        self.level_color = level_color
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        bar_h = 0.5 * cm
        # Fond de la barre (gris)
        c.setFillColor(colors.HexColor("#E5E8E8"))
        c.roundRect(0, self.height - bar_h, self.width, bar_h, 4, fill=1, stroke=0)
        # Remplissage selon le score
        fill_w = self.width * (self.score / 100.0)
        c.setFillColor(self.level_color)
        if fill_w > 0:
            c.roundRect(0, self.height - bar_h, max(fill_w, 8), bar_h, 4,
                        fill=1, stroke=0)
        # Graduations 0, 25, 50, 75, 100
        c.setFont("Helvetica", 6.5)
        c.setFillColor(colors.HexColor("#7F8C8D"))
        for val in (0, 25, 50, 75, 100):
            x = self.width * (val / 100.0)
            x = min(max(x, 4), self.width - 4)
            c.drawCentredString(x, 0, str(val))


def _group_events(events):
    groups = {}
    for ev in events:
        key = ev.event_type.value
        if key not in groups:
            label, desc = _EVENT_HUMAN.get(key, (key, ""))
            groups[key] = {
                "type": key, "label": label, "description": desc,
                "count": 0, "first_time": ev.timestamp, "last_time": ev.timestamp,
                "severity": _EVENT_SEVERITY.get(key, 0),
            }
        g = groups[key]
        g["count"] += 1
        g["first_time"] = min(g["first_time"], ev.timestamp)
        g["last_time"] = max(g["last_time"], ev.timestamp)
    return sorted(groups.values(),
                  key=lambda g: (g["severity"], g["count"]), reverse=True)


def _format_duration(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    m, s = seconds // 60, seconds % 60
    return f"{m} min {s} s" if s else f"{m} min"


def _build_human_summary(result, groups):
    if not groups:
        return ("Aucun comportement suspect n'a été détecté pendant "
                "l'examen. Le candidat est resté concentré sur son écran.")
    top = groups[:3]
    parts = []
    for g in top:
        n = "une fois" if g["count"] == 1 else f"{g['count']} fois"
        parts.append(f"{g['label'].lower()} ({n})")
    listing = ", ".join(parts)
    intro = "Pendant l'examen, le système a principalement remarqué : "
    level = result.risk_level
    if level == RiskLevel.NONE:
        ctx = ("Ces signaux sont faibles et peuvent s'expliquer par du "
               "stress ou de la réflexion. Rien n'indique une triche évidente.")
    elif level == RiskLevel.SUSPECT:
        ctx = ("Ces comportements méritent un coup d'œil sur la vidéo "
               "pour vérifier, mais ne prouvent pas une triche.")
    else:
        ctx = ("Ces signaux sont importants. Il est fortement conseillé "
               "de revoir la vidéo en détail.")
    return intro + listing + ". " + ctx


def generate_report(result: AnalysisResult, output_path: str) -> str:
    """Genere le PDF du rapport humain et professionnel."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=1.6 * cm, bottomMargin=1.8 * cm,
        leftMargin=2 * cm, rightMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    h_title = ParagraphStyle("HT", parent=styles["Title"], fontSize=19,
                             spaceAfter=2, textColor=colors.HexColor("#1A2530"))
    h_sub = ParagraphStyle("HS", parent=styles["Normal"], fontSize=9.5,
                           textColor=colors.HexColor("#7F8C8D"), spaceAfter=2)
    sec = ParagraphStyle("SEC", parent=styles["Normal"], fontSize=12,
                         fontName="Helvetica-Bold", spaceBefore=10,
                         spaceAfter=5, textColor=colors.HexColor("#2C3E50"))
    body = ParagraphStyle("B", parent=styles["Normal"], fontSize=10.5,
                          leading=15, spaceAfter=5)
    cell = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8.5, leading=11)
    cell_head = ParagraphStyle("CH", parent=styles["Normal"], fontSize=8.5,
                               leading=11, textColor=colors.white,
                               fontName="Helvetica-Bold")

    story = []

    # ============ EN-TETE ============
    header = Table([[
        Paragraph("<b>Digii Exam</b> — Surveillance d'examen par IA", h_sub),
        Paragraph(
            "Généré le " + datetime.now().strftime("%d/%m/%Y à %H:%M"),
            ParagraphStyle("HR", parent=h_sub, alignment=2)),
    ]], colWidths=[10 * cm, 6 * cm])
    header.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#2C3E50")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header)
    story.append(Spacer(1, 0.4 * cm))

    # ============ TITRE ============
    story.append(Paragraph("Rapport d'analyse de surveillance", h_title))
    story.append(Spacer(1, 0.3 * cm))

    # ============ INFOS CANDIDAT / EXAMEN ============
    candidate = result.candidate_name or "Non renseigné"
    exam = result.exam_name or "Non renseigné"
    exam_date = result.exam_date or "Non renseignée"
    info_tbl = Table([
        [Paragraph("<b>Candidat</b>", cell), Paragraph(candidate, cell),
         Paragraph("<b>Examen</b>", cell), Paragraph(exam, cell)],
        [Paragraph("<b>Date de l'examen</b>", cell), Paragraph(exam_date, cell),
         Paragraph("<b>Durée analysée</b>", cell),
         Paragraph(_format_duration(result.stats.duration_seconds), cell)],
    ], colWidths=[3 * cm, 5 * cm, 3 * cm, 5 * cm])
    info_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8F9F9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D5D8DC")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EAECEE")),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 0.5 * cm))

    # ============ SCORE + JAUGE ============
    risk_color = _RISK_COLORS.get(result.risk_level, colors.grey)
    risk_label = _RISK_LABELS.get(result.risk_level, "-")

    score_head = Table([[
        Paragraph(f'<font size="11" color="white"><b>NIVEAU : '
                  f'{risk_label.upper()}</b></font>', body),
        Paragraph(f'<font size="20" color="white"><b>{result.risk_score}'
                  f'</b></font><font size="10" color="white"> / 100</font>',
                  ParagraphStyle("SR", parent=body, alignment=2)),
    ]], colWidths=[11 * cm, 5 * cm])
    score_head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), risk_color),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(score_head)
    story.append(Spacer(1, 0.25 * cm))
    story.append(ScoreGauge(result.risk_score, risk_color))
    story.append(Spacer(1, 0.6 * cm))

    # ============ CE QUI A ETE OBSERVE ============
    groups = _group_events(result.events)
    story.append(Paragraph("Ce qui a été observé", sec))
    story.append(Paragraph(_build_human_summary(result, groups), body))

    # ============ ANALYSE LLM ============
    if result.interpretation is not None:
        interp = result.interpretation
        story.append(Paragraph("Analyse détaillée", sec))
        story.append(Paragraph(interp.conclusion, body))
        if interp.recommendation:
            story.append(Paragraph(
                "<b>Conseil :</b> " + interp.recommendation, body))

    # ============ TABLEAU DES COMPORTEMENTS ============
    story.append(Paragraph("Détail des comportements remarqués", sec))
    if not groups:
        story.append(Paragraph(
            "Aucun comportement suspect n'a été relevé.", body))
    else:
        rows = [[
            Paragraph("Comportement", cell_head),
            Paragraph("Nombre", cell_head),
            Paragraph("Quand", cell_head),
            Paragraph("Ce que ça veut dire", cell_head),
        ]]
        row_colors = []
        for g in groups:
            if g["first_time"] == g["last_time"]:
                when = f"à {_format_duration(g['first_time'])}"
            else:
                when = (f"de {_format_duration(g['first_time'])} "
                        f"à {_format_duration(g['last_time'])}")
            rows.append([
                Paragraph(f"<b>{g['label']}</b>", cell),
                Paragraph(f"{g['count']} fois", cell),
                Paragraph(when, cell),
                Paragraph(g["description"], cell),
            ])
            row_colors.append(_SEVERITY_COLORS.get(g["severity"],
                                                   colors.white))

        tbl = Table(rows, colWidths=[3.6 * cm, 1.8 * cm, 2.6 * cm, 7.0 * cm])
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D5D8DC")),
            ("PADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        # Couleur de fond par ligne selon la gravite.
        for i, rc in enumerate(row_colors, start=1):
            style.append(("BACKGROUND", (0, i), (-1, i), rc))
        tbl.setStyle(TableStyle(style))
        story.append(tbl)

        # Legende des couleurs
        story.append(Spacer(1, 0.2 * cm))
        legend = Table([[
            Paragraph('<font size="7">■</font> Signal grave', 
                      ParagraphStyle("L1", parent=cell, fontSize=7.5,
                                     textColor=colors.HexColor("#C0392B"))),
            Paragraph('<font size="7">■</font> Signal moyen',
                      ParagraphStyle("L2", parent=cell, fontSize=7.5,
                                     textColor=colors.HexColor("#E67E22"))),
            Paragraph('<font size="7">■</font> Signal faible',
                      ParagraphStyle("L3", parent=cell, fontSize=7.5,
                                     textColor=colors.HexColor("#7F8C8D"))),
        ]], colWidths=[3 * cm, 3 * cm, 3 * cm])
        legend.setStyle(TableStyle([("PADDING", (0, 0), (-1, -1), 1)]))
        story.append(legend)

    story.append(Spacer(1, 0.4 * cm))

    # ============ INFO SIGNAUX ============
    story.append(Paragraph(
        f"<i>Nombre total de signaux détectés : "
        f"{result.stats.total_alerts}.</i>",
        ParagraphStyle("Info", parent=styles["Normal"], fontSize=9,
                       textColor=colors.HexColor("#7F8C8D"))))
    story.append(Spacer(1, 0.4 * cm))

    # ============ AVERTISSEMENT ============
    story.append(Paragraph(
        "<b>Important :</b> Ce rapport est une aide à la décision. "
        "L'intelligence artificielle signale des comportements, mais elle "
        "peut se tromper (un reflet, un objet mal reconnu, du simple stress). "
        "La décision finale revient toujours à un responsable humain qui doit "
        "vérifier la vidéo.",
        ParagraphStyle("Warn", parent=styles["Normal"], fontSize=9,
                       textColor=colors.HexColor("#5F5E5A"),
                       borderPadding=10, leading=13,
                       backColor=colors.HexColor("#FEF9E7"),
                       borderColor=colors.HexColor("#F9E79F"),
                       borderWidth=0.5)))

    doc.build(story)
    logger.info("Rapport PDF genere : %s", output_path)
    return output_path
