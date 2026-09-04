# digii_exam_manager — Guide d'installation complet (v7)

## Architecture

```
[Candidat]  →  caméra/micro  →  [LiveKit Docker]
                                        │
                              LiveKit Egress (enregistrement)
                                        │
                                 [Minio Docker]  ←  stocke le MP4
                                        │
                              [Odoo] génère URL → affiche dans
                              la fiche Certificat pour le procteur
```

## Étape 1 — Installer les dépendances Python

```bash
pip install PyJWT requests boto3
```

> boto3 est optionnel mais recommandé : il génère des URLs présignées
> Minio avec expiration 24h.

## Étape 2 — Lancer l'infrastructure Docker

Placez ces fichiers dans un même dossier :
- docker-compose.yml
- livekit.yaml
- egress.yaml

```bash
docker compose up -d
docker compose ps   # vérifier que tout tourne
```

Le service minio-init crée automatiquement le bucket exam-recordings.

## Étape 3 — Installer le module dans Odoo

```bash
odoo-bin -d votre_base -u digii_exam_manager
```

## Étape 4 — Paramètres système (Settings > Technical > System Parameters)

| Clé | Valeur dev |
|-----|-----------|
| digii_exam_manager.livekit_url | ws://localhost:7880 |
| digii_exam_manager.livekit_api_key | devkey |
| digii_exam_manager.livekit_api_secret | secret |
| digii_exam_manager.minio_endpoint | http://minio:9000 |
| digii_exam_manager.minio_access_key | minioadmin |
| digii_exam_manager.minio_secret_key | minioadmin |
| digii_exam_manager.minio_bucket | exam-recordings |
| digii_exam_manager.minio_public_url | http://localhost:9000 |

IMPORTANT : minio_endpoint = URL interne Docker (pour Odoo/Python)
            minio_public_url = URL vue par le navigateur du procteur

## Étape 5 — Console Minio

http://localhost:9001  →  minioadmin / minioadmin
Après un examen : fichier session_<ID>.mp4 visible dans le bucket.

## Flux complet

1. Candidat entre en salle d'attente
2. Procteur voit le live, autorise
3. Candidat démarre → Odoo appelle LiveKit Egress → MP4 dans Minio
4. Candidat termine → Egress s'arrête → MP4 finalisé
5. Certificat créé automatiquement (état : En attente)
6. Procteur ouvre le certificat → player vidéo intégré
7. Procteur clique Approuver ou Rejeter

## Dépannage

Vidéo absente : docker compose logs livekit-egress
               + vérifier console Minio http://localhost:9001
               + cliquer "Rafraîchir l'URL" dans la fiche certificat

minio_endpoint doit pointer vers l'adresse interne Docker (http://minio:9000)
et non localhost depuis un container.
