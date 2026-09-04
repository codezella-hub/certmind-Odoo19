# digii_exam_ai_agent — Installation & Configuration

Assistant IA conversationnel pour la génération de questions et l'assistance
à la création d'examens, intégré à **Smart LMS** (Odoo 19).

## 1. Prérequis

- Odoo 19 avec les modules **`digii_lms`** et **`digii_exam_manager`** déjà installés.
- La bibliothèque Python **`openai`** (utilisée comme client générique, pointé
  vers l'API Groq) :

  ```bash
  pip install openai
  ```

## 2. Installation du module

1. Copier le dossier `digii_exam_ai_agent/` dans votre répertoire d'addons.
2. Redémarrer le serveur Odoo.
3. Activer le **mode développeur**, puis **Apps → Mettre à jour la liste des
   applications**.
4. Rechercher *Digii Exam AI Agent* et cliquer sur **Installer**.

## 3. Configuration de la clé API Groq

Toute la configuration passe par les **paramètres système** (aucune clé en dur).

Aller dans **Paramètres → Technique → Paramètres système** et créer/renseigner :

| Clé (`Key`)                       | Valeur                                  | Obligatoire |
|-----------------------------------|-----------------------------------------|-------------|
| `digii_exam_ai_agent.api_key`     | votre clé API Groq (`gsk_...`)          | **Oui**     |
| `digii_exam_ai_agent.model`       | `llama-3.3-70b-versatile` (par défaut)  | Non         |
| `digii_exam_ai_agent.base_url`    | `https://api.groq.com/openai/v1`        | Non         |

> Obtenez une clé gratuite sur https://console.groq.com (section *API Keys*).

Si la clé est absente, le panneau s'ouvre mais affiche un message invitant à la
configurer.

### Changer de modèle

Groq héberge plusieurs modèles. Pour en changer, modifiez simplement la valeur de
`digii_exam_ai_agent.model` (ex. un autre modèle Llama ou Mixtral disponible sur
votre compte Groq). Aucun redémarrage nécessaire.

## 4. Droits d'accès

Le module crée le groupe **« Assistant IA Examens »**
(`digii_exam_ai_agent.group_exam_ai_user`). Il est **automatiquement accordé**
aux utilisateurs ayant le rôle **Survey → Manager** (qui gèrent déjà la banque de
questions et les examens). Aucun réglage supplémentaire n'est requis pour eux.

Pour donner l'accès à un autre utilisateur sans en faire un manager Survey,
ajoutez-lui le groupe « Assistant IA Examens » depuis sa fiche utilisateur
(mode développeur).

## 5. Utilisation

**Trois points d'entrée :**

1. **Bouton « Assistant IA » dans la barre supérieure (systray)** — ouvre le
   panneau partout dans le back-office (mode génération de questions par défaut).
2. **Bouton « Assistant IA » sur la fiche d'un examen** (`survey.survey` en mode
   examen) — ouvre le panneau pré-lié à cet examen, en mode *co-pilote de règles*.
3. **Menu Examens → « Assistant IA (validation) »** — vue de validation en masse
   des questions proposées par l'IA (filtrées sur l'état *proposé*).

**Workflow :**

- L'IA **propose** des questions → elles arrivent en état *« Proposé par IA »*,
  **hors** de la banque officielle.
- L'admin **approuve** (la question passe `is_bank_question = True` et entre en
  banque), **édite**, **rejette** (archivée) ou **demande une régénération
  ciblée** (« rends-la plus difficile », « reformule »…).
- Pour les examens, le **co-pilote de règles** propose des lignes
  `exam.generation.rule` et **vérifie la faisabilité** sur le pool réel de la
  banque (avertissement si le pool est insuffisant).

## 6. Traçabilité / debug

Chaque demande crée une **Session de génération IA** (menu *Examens → Sessions
IA*) qui conserve le prompt système, la réponse brute et les objets créés. La page
*Debug* (visible en mode développeur) montre le prompt et la réponse JSON.

## 7. Remarques

- Les appels à l'IA sont **synchrones** : le panneau affiche une animation de
  saisie pendant la génération (quelques secondes selon le modèle).
- Les questions de type *vrai/faux* sont produites comme un QCM à réponse unique
  à deux propositions (Odoo `survey.question` n'a pas de type natif vrai/faux).
- Les catégories/sous-catégories proposées par l'IA sont **mappées sur celles
  existantes** dans la banque ; si aucune ne correspond, le champ est laissé vide
  (l'admin complète) — l'IA ne crée pas de catégorie automatiquement.
