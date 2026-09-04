# Integration IA dans digii_exam_manager — fichiers modifies

L'analyse IA est integree DIRECTEMENT dans tes fichiers existants (pas
de module separe). Voici les 3 fichiers modifies a remplacer dans ton
module.

## Fichiers a remplacer

| Fichier modifie | Chemin dans ton module |
|---|---|
| `exam_proctoring_session.py` | `digii_exam_manager/models/` |
| `exam_proctoring_session_views.xml` | `digii_exam_manager/views/` |
| `livekit_config_data.xml` | `digii_exam_manager/data/` |
| `__manifest__.py` | `digii_exam_manager/` (racine) |

## Ce qui a change

### 1. models/exam_proctoring_session.py
- Imports ajoutes : `base64`, `requests`
- 10 nouveaux champs : `ai_task_id`, `ai_analysis_state`, `ai_risk_score`,
  `ai_risk_level`, `ai_alerts_count`, `ai_conclusion`, `ai_interpretation`,
  `ai_recommendation`, `ai_report`, `ai_report_filename`
- 4 nouvelles methodes : `_get_ai_service_url`, `_get_video_bytes`,
  `action_analyze_video`, `action_fetch_ai_result`

### 2. views/exam_proctoring_session_views.xml
- 2 boutons dans le header : "Analyser la video (IA)" et
  "Recuperer le resultat"
- 2 groupes dans le sheet : le score/rapport et les textes du LLM

### 3. data/livekit_config_data.xml
- 1 parametre ajoute : `digii_exam_manager.proctoring_ai_url`
  (URL du microservice, defaut http://localhost:8000)

### 4. __manifest__.py
- `requests` ajoute aux dependances Python

## Pas de nouvelle ligne dans `data` du manifest

Comme on a reutilise des fichiers deja declares (le data et la vue
existent deja dans le manifest), il n'y a RIEN a ajouter a la liste
`data`. Seule la dependance `requests` a ete ajoutee.

## Installation

```bash
# 1. Remplace les 3-4 fichiers dans ton module
# 2. Installe requests si absent
pip install requests
# 3. Mets a jour le module
odoo -u digii_exam_manager -d ta_base
```

## Utilisation

1. Lance le microservice : `uvicorn main:app --port 8000`
2. Ouvre une session de proctoring avec une video enregistree
3. Clique "Analyser la video (IA)" dans le header
4. Attends quelques secondes
5. Clique "Recuperer le resultat"
6. Le score, le niveau, les textes LLM et le PDF s'affichent dans le form

## Configurer l'URL du microservice

Parametres > Technique > Parametres systeme >
`digii_exam_manager.proctoring_ai_url`
- Meme machine : `http://localhost:8000`
- Serveur separe : `http://IP:8000`
