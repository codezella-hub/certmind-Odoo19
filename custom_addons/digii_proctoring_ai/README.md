# Digii Proctoring IA (module Odoo)

Analyse de triche par IA **directement dans Odoo**, sans microservice FastAPI.
Le pipeline (MediaPipe, YOLOv8) tourne en arriere-plan via un CRON.

## Installation

### 1. Installer les dependances Python dans l'environnement d'Odoo

```bash
# Dans le meme environnement Python qui fait tourner Odoo :
pip install -r requirements.txt
```

Sous Windows, activez d'abord l'environnement d'Odoo, puis lancez pip.

### 2. Installer le module

Copiez le dossier `digii_proctoring_ai` dans vos addons, puis :

```bash
odoo -u digii_proctoring_ai -d votre_base
```

### 3. (Optionnel) Configurer la cle Groq pour l'interpretation LLM

Parametres techniques > Parametres systeme >
`digii_proctoring_ai.groq_api_key` = votre cle.

## Utilisation

1. Ouvrez une session de proctoring qui a une video enregistree.
2. Cliquez sur **"Analyser (local)"**.
3. L'analyse se lance en arriere-plan (CRON, toutes les minutes).
4. Le score, les alertes et le rapport PDF apparaissent une fois termine.

## Notes de performance

- L'analyse est asynchrone : elle ne bloque jamais l'interface.
- Le CRON traite 3 sessions max par execution (configurable).
- La 1re analyse telecharge le modele YOLOv8n (~6 Mo) automatiquement.
- Pour la production avec beaucoup de sessions, prevoir un worker dedie
  ou augmenter la frequence du CRON.
