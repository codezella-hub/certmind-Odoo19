# -*- coding: utf-8 -*-
"""
Assistant d'import de questions dans la banque (exam.category / survey.question).

Format de fichier attendu (1re ligne = en-têtes), .xlsx ou .csv :

    category | subcategory | difficulty | type | cognitive_type | question |
    choice_a | choice_b | choice_c | choice_d | choice_e | correct

  - category    : catégorie parente (créée si absente). Obligatoire (ou défaut).
  - subcategory : sous-catégorie (créée sous la parente si absente). Optionnel.
  - difficulty  : easy / medium / hard  (ou facile / moyen / difficile). Optionnel.
  - type        : simple_choice / multiple_choice (ou QCU / QCM). Défaut: simple_choice.
  - cognitive_type : memory / comprehension / application / analysis / experience
    (ou en français : mémoire / compréhension / application / analyse / expérience).
    Optionnel.
  - question    : intitulé de la question. Obligatoire.
  - choice_a..e : propositions de réponse (laisser vide celles non utilisées).
  - correct     : lettre(s) de la/les bonne(s) réponse(s), ex "A" ou "A,C".
"""
import base64
import csv
import io
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Colonnes attendues
HEADERS = [
    'category', 'subcategory', 'difficulty', 'type', 'cognitive_type',
    'question',
    'choice_a', 'choice_b', 'choice_c', 'choice_d', 'choice_e', 'correct',
]
CHOICE_COLS = ['choice_a', 'choice_b', 'choice_c', 'choice_d', 'choice_e']
LETTERS = ['A', 'B', 'C', 'D', 'E']

DIFFICULTY_MAP = {
    'easy': 'easy', 'facile': 'easy',
    'medium': 'medium', 'moyen': 'medium', 'moyenne': 'medium',
    'hard': 'hard', 'difficile': 'hard',
}
TYPE_MAP = {
    'simple_choice': 'simple_choice', 'simple': 'simple_choice',
    'unique': 'simple_choice', 'qcu': 'simple_choice', 'choix unique': 'simple_choice',
    'multiple_choice': 'multiple_choice', 'multiple': 'multiple_choice',
    'qcm': 'multiple_choice', 'choix multiple': 'multiple_choice',
}
# Type cognitif : accepte francais et anglais.
COGNITIVE_MAP = {
    'memory': 'memory', 'memoire': 'memory', 'mémoire': 'memory',
    'restitution': 'memory',
    'comprehension': 'comprehension', 'compréhension': 'comprehension',
    'understanding': 'comprehension',
    'application': 'application', 'apply': 'application',
    'analysis': 'analysis', 'analyse': 'analysis',
    'experience': 'experience', 'expérience': 'experience',
    'pratique': 'experience', 'practical': 'experience',
}


class ExamQuestionImport(models.TransientModel):
    _name = 'exam.question.import'
    _description = "Import de questions dans la banque"

    import_file = fields.Binary('Fichier (.xlsx ou .csv)')
    import_filename = fields.Char('Nom du fichier')
    default_category_id = fields.Many2one(
        'exam.category', string="Catégorie par défaut",
        domain=[('parent_id', '=', False)],
        help="Utilisée pour les lignes dont la colonne 'category' est vide.",
    )
    create_missing_categories = fields.Boolean(
        "Créer les catégories manquantes", default=True,
        help="Crée automatiquement les catégories / sous-catégories absentes.",
    )
    skip_duplicates = fields.Boolean(
        "Ignorer les doublons", default=True,
        help="Si coché, une question déjà présente dans la banque "
             "(même intitulé + même catégorie / sous-catégorie) n'est PAS "
             "réimportée. Décochez pour forcer l'import de toutes les lignes.",
    )
    result_message = fields.Text('Résultat', readonly=True)

    # ------------------------------------------------------------------
    # Modèle Excel téléchargeable
    # ------------------------------------------------------------------
    def action_download_template(self):
        """Génère un fichier modèle .xlsx prêt à remplir."""
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Questions"

        head_fill = PatternFill("solid", fgColor="4F46E5")
        head_font = Font(color="FFFFFF", bold=True)
        for col, h in enumerate(HEADERS, start=1):
            c = ws.cell(row=1, column=col, value=h)
            c.fill = head_fill
            c.font = head_font
            c.alignment = Alignment(horizontal="center")
            ws.column_dimensions[c.column_letter].width = 16
        ws.column_dimensions['F'].width = 46  # question

        # Lignes d'exemple
        examples = [
            ['Python', 'POO', 'easy', 'simple_choice', 'memory',
             "Quel mot-clé définit une classe en Python ?",
             'class', 'def', 'function', 'object', '', 'A'],
            ['Python', 'POO', 'medium', 'multiple_choice', 'comprehension',
             "Lesquels sont des types natifs Python ?",
             'list', 'dict', 'array', 'tuple', '', 'A,B,D'],
            ['SQL', 'Jointures', 'medium', 'simple_choice', 'application',
             "Quelle clause joint deux tables ?",
             'JOIN', 'MERGE', 'LINK', 'BIND', '', 'A'],
            ['Réseau', '', 'hard', 'simple_choice', 'analysis',
             "Quel port utilise HTTPS par défaut ?",
             '80', '443', '21', '22', '', 'B'],
        ]
        for r in examples:
            ws.append(r)

        # Feuille légende
        legend = wb.create_sheet("Legende")
        legend_rows = [
            ["Colonne", "Description", "Valeurs possibles"],
            ["category", "Catégorie parente (obligatoire)", "Texte libre"],
            ["subcategory", "Sous-catégorie (optionnel)", "Texte libre"],
            ["difficulty", "Difficulté", "easy / medium / hard"],
            ["type", "Type de question", "simple_choice / multiple_choice"],
            ["cognitive_type", "Type cognitif (optionnel)",
             "memory / comprehension / application / analysis / experience "
             "(ou : mémoire / compréhension / application / analyse / expérience)"],
            ["question", "Intitulé de la question (obligatoire)", "Texte libre"],
            ["choice_a..e", "Propositions de réponse", "Texte (vide si inutilisé)"],
            ["correct", "Bonne(s) réponse(s)", "Lettres : A / A,C / B,D ..."],
        ]
        for row in legend_rows:
            legend.append(row)
        for col in ('A', 'B', 'C'):
            legend.column_dimensions[col].width = 34
        legend['A1'].font = Font(bold=True)
        legend['B1'].font = Font(bold=True)
        legend['C1'].font = Font(bold=True)

        buf = io.BytesIO()
        wb.save(buf)
        data = base64.b64encode(buf.getvalue())

        attachment = self.env['ir.attachment'].create({
            'name': 'modele_import_questions.xlsx',
            'type': 'binary',
            'datas': data,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    # ------------------------------------------------------------------
    # Lecture du fichier -> liste de dicts
    # ------------------------------------------------------------------
    def _read_rows(self):
        if not self.import_file:
            raise UserError(_("Veuillez d'abord sélectionner un fichier."))
        raw = base64.b64decode(self.import_file)
        fname = (self.import_filename or '').lower()

        if fname.endswith('.csv') or (not fname.endswith('.xlsx') and b',' in raw[:200]):
            return self._read_csv(raw)
        return self._read_xlsx(raw)

    def _read_csv(self, raw):
        text = raw.decode('utf-8-sig', errors='replace')
        # Détecte le séparateur , ou ;
        sample = text[:2000]
        delim = ';' if sample.count(';') > sample.count(',') else ','
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        rows = list(reader)
        if not rows:
            raise UserError(_("Fichier CSV vide."))
        header = [(h or '').strip().lower() for h in rows[0]]
        out = []
        for r in rows[1:]:
            if not any((c or '').strip() for c in r):
                continue
            out.append({header[i]: (r[i] if i < len(r) else '') for i in range(len(header))})
        return out

    def _read_xlsx(self, raw):
        try:
            import openpyxl
        except ImportError:
            raise UserError(_(
                "La librairie openpyxl est requise pour lire un .xlsx. "
                "Utilisez plutôt un fichier .csv."
            ))
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise UserError(_("Feuille Excel vide."))
        header = [(str(h).strip().lower() if h is not None else '') for h in rows[0]]
        out = []
        for r in rows[1:]:
            if r is None or not any(c not in (None, '') for c in r):
                continue
            d = {}
            for i in range(len(header)):
                val = r[i] if i < len(r) else None
                d[header[i]] = '' if val is None else str(val)
            out.append(d)
        return out

    # ------------------------------------------------------------------
    # Catégories
    # ------------------------------------------------------------------
    def _get_or_create_category(self, name, parent=None):
        Category = self.env['exam.category']
        name = (name or '').strip()
        if not name:
            return Category
        domain = [('name', '=ilike', name),
                  ('parent_id', '=', parent.id if parent else False)]
        cat = Category.search(domain, limit=1)
        if not cat:
            if not self.create_missing_categories:
                raise UserError(_(
                    "Catégorie introuvable : '%s' (création désactivée).", name))
            cat = Category.create({
                'name': name,
                'parent_id': parent.id if parent else False,
            })
        return cat

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_title(title):
        """Normalise un intitulé pour la comparaison de doublons :
        minuscules + espaces multiples réduits à un seul."""
        return ' '.join((title or '').lower().split())

    def _build_existing_signatures(self):
        """Pré-charge l'ensemble des questions déjà présentes dans la banque
        sous forme de signatures (titre normalisé, cat parente, sous-cat).
        Évite une requête SQL par ligne importée."""
        existing = self.env['survey.question'].sudo().search_read(
            [('is_bank_question', '=', True), ('is_page', '=', False)],
            ['title', 'exam_category_id', 'exam_subcategory_id'],
        )
        signatures = set()
        for q in existing:
            signatures.add((
                self._normalize_title(q['title']),
                q['exam_category_id'][0] if q['exam_category_id'] else False,
                q['exam_subcategory_id'][0] if q['exam_subcategory_id'] else False,
            ))
        return signatures

    def action_import(self):
        self.ensure_one()
        rows = self._read_rows()
        Question = self.env['survey.question']

        # Signatures déjà en base (pour ignorer les doublons existants)
        # + signatures rencontrées dans CE fichier (pour ignorer les
        #   doublons internes au fichier lui-même).
        existing_signatures = self._build_existing_signatures() if self.skip_duplicates else set()
        seen_in_file = set()

        created = 0
        duplicates = 0
        errors = []
        for idx, row in enumerate(rows, start=2):  # ligne 2 = 1re ligne de données
            try:
                title = (row.get('question') or '').strip()
                if not title:
                    errors.append(f"Ligne {idx} : question vide, ignorée.")
                    continue

                # Catégorie / sous-catégorie
                cat_name = (row.get('category') or '').strip()
                if cat_name:
                    parent = self._get_or_create_category(cat_name)
                else:
                    parent = self.default_category_id
                if not parent:
                    errors.append(f"Ligne {idx} : aucune catégorie.")
                    continue
                sub = self.env['exam.category']
                sub_name = (row.get('subcategory') or '').strip()
                if sub_name:
                    sub = self._get_or_create_category(sub_name, parent=parent)

                # ----------------------------------------------------------
                # Détection des doublons (titre + catégorie + sous-catégorie)
                # ----------------------------------------------------------
                signature = (
                    self._normalize_title(title),
                    parent.id,
                    sub.id if sub else False,
                )
                if self.skip_duplicates and (
                    signature in existing_signatures or signature in seen_in_file
                ):
                    duplicates += 1
                    continue
                seen_in_file.add(signature)

                # Difficulté / type / type cognitif
                diff = DIFFICULTY_MAP.get((row.get('difficulty') or '').strip().lower())
                qtype = TYPE_MAP.get((row.get('type') or '').strip().lower(), 'simple_choice')
                cognitive = COGNITIVE_MAP.get(
                    (row.get('cognitive_type') or '').strip().lower())

                # Bonnes réponses
                correct_raw = (row.get('correct') or '').strip().upper()
                correct_letters = {c.strip() for c in correct_raw.replace(';', ',').split(',') if c.strip()}

                # Choix
                answer_cmds = []
                for col, letter in zip(CHOICE_COLS, LETTERS):
                    val = (row.get(col) or '').strip()
                    if not val:
                        continue
                    is_ok = letter in correct_letters
                    answer_cmds.append((0, 0, {
                        'value': val,
                        'is_correct': is_ok,
                        'answer_score': 1.0 if is_ok else 0.0,
                    }))

                vals = {
                    'title': title,
                    'question_type': qtype,
                    'is_bank_question': True,
                    'survey_id': False,
                    'exam_category_id': parent.id,
                    'exam_subcategory_id': sub.id if sub else False,
                    'exam_difficulty': diff,
                }
                if cognitive:
                    vals['cognitive_type'] = cognitive
                if answer_cmds:
                    vals['suggested_answer_ids'] = answer_cmds

                Question.create(vals)
                created += 1
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Import ligne %s", idx)
                errors.append(f"Ligne {idx} : {exc}")

        msg = "✓ %d question(s) importée(s)." % created
        if duplicates:
            msg += "\n⊘ %d doublon(s) ignoré(s) (déjà présents dans la banque)." % duplicates
        if errors:
            msg += "\n\n⚠ %d problème(s) :\n" % len(errors) + "\n".join(errors[:30])
            if len(errors) > 30:
                msg += "\n… (%d autres)" % (len(errors) - 30)
        self.result_message = msg

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'exam.question.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context, import_done=True),
        }

    def action_view_bank(self):
        """Ouvre la banque de questions."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Banque de questions'),
            'res_model': 'survey.question',
            'view_mode': 'list,form',
            'domain': [('is_bank_question', '=', True), ('is_page', '=', False)],
        }
