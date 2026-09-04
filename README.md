# Certmind — Odoo 19 (LMS + Examens + Proctoring IA)

Plateforme d'apprentissage et de certification : cours en ligne, examens
générés, surveillance par IA et agents conversationnels.

## Modules

| Module | Rôle |
|---|---|
| `digii_lms` | Cours, classes, portail eLearning |
| `digii_exam_manager` | Examens, questions, certificats, proctoring |
| `digii_proctoring_ai` | Analyse vidéo anti-triche (MediaPipe, YOLOv8) |
| `digii_exam_ai_agent` | Agent IA : génération de questions et de règles |
| `digii_lms_ai_agent` | Tuteur IA côté étudiant (portail) |

Ordre d'installation : `digii_lms` → `digii_exam_manager` →
`digii_proctoring_ai` → `digii_exam_ai_agent` → `digii_lms_ai_agent`.

## Démarrage en local

```bash
docker compose up -d --build   # --build est nécessaire après toute
                               # modification du Dockerfile ou des
                               # dépendances Python
```

Odoo est ensuite disponible sur <http://localhost:8070>.

```bash
docker compose logs -f odoo    # suivre les logs
docker compose down            # arrêter
docker compose down -v         # arrêter ET supprimer les données
```

## Configuration

Toute la configuration passe par des variables d'environnement.
`entrypoint.sh` les injecte dans `config/odoo.conf.template` au démarrage,
ce qui permet d'utiliser la même image en développement et en production.

| Variable | Dev | Production Azure |
|---|---|---|
| `DB_HOST` | `db` | `certmind-db.postgres.database.azure.com` |
| `DB_SSLMODE` | `disable` | `require` |
| `ODOO_WORKERS` | `0` | `2` |
| `ODOO_LOG_LEVEL` | `info` | `warn` |

`ODOO_LOG_LEVEL` doit être en minuscules : `info`, `warn`, `error`, `debug`.

### Clés API des agents IA

Elles se configurent dans Odoo, pas dans les fichiers :
**Paramètres → Technique → Paramètres système**

| Clé | Usage |
|---|---|
| `digii_exam_ai_agent.api_key` | Agent examen |
| `digii_exam_ai_agent.model` | Modèle Groq de l'agent examen |
| `digii_lms_ai_agent.api_key` | Tuteur LMS |
| `digii_lms_ai_agent.model` | Modèle Groq du tuteur |

Modèle recommandé : `openai/gpt-oss-120b`.
`llama-3.3-70b-versatile` a été déprécié par Groq et renvoie une erreur 404.

## Note sur torch et CUDA

`ultralytics` et `silero-vad` déclarent `torch` en dépendance. Installés
normalement, pip télécharge la version GPU depuis PyPI, soit environ 1 Go
de bibliothèques CUDA inutiles (Azure Container Apps n'a pas de GPU).

Le Dockerfile installe donc d'abord torch en version CPU depuis l'index
PyTorch dédié, puis ces deux paquets avec `--no-deps` afin que pip ne
résolve pas leurs dépendances et réutilise le torch déjà présent.

## Dépendances système

Installées par le Dockerfile : `ffmpeg` (conversion vidéo),
`wkhtmltopdf` (rapports PDF), `gettext-base` (envsubst), et les
bibliothèques natives requises par OpenCV et MediaPipe.

## Déploiement Azure

Ressources créées :

- Groupe de ressources `rg-certmind` (France Central)
- PostgreSQL Flexible Server `certmind-db`
- Container Registry `certmindacr`

```bash
# Build et publication de l'image
docker build -t certmindacr.azurecr.io/certmind-odoo:latest .
docker push certmindacr.azurecr.io/certmind-odoo:latest
```

Les secrets (mots de passe, clés API) doivent passer par Azure Key Vault
et être référencés depuis Container Apps, jamais écrits dans le dépôt.
