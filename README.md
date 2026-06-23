# Odoo 19 — Docker Setup

## Structure du projet

```
odoo19-docker/
├── Dockerfile                  # Image Odoo 19 custom
├── docker-compose.yml          # Services : odoo + postgresql
├── .env                        # Variables d'environnement
├── .gitignore
├── config/
│   └── odoo.conf               # Config Odoo (db, port, addons...)
├── custom_addons/              # ← Tes modules custom ici
│   └── my_module/
│       ├── __manifest__.py
│       └── __init__.py
└── data/                       # Ignoré par git (filestore local si besoin)
```

## ⚠️ Port : 8070 (évite le conflit avec Odoo local sur 8069)

---

## Commandes

### Démarrer
```bash
docker compose up -d
```

### Voir les logs
```bash
docker compose logs -f odoo
```

### Arrêter
```bash
docker compose down
```

### Arrêter + supprimer les volumes (reset complet)
```bash
docker compose down -v
```

### Rebuild après modification du Dockerfile
```bash
docker compose up -d --build
```

### Accéder au shell du container Odoo
```bash
docker exec -it odoo19_app bash
```

### Accéder à psql
```bash
docker exec -it odoo19_db psql -U odoo
```

---

## Ajouter un module custom

1. Crée ton dossier dans `custom_addons/mon_module/`
2. Ajoute `__manifest__.py` et `__init__.py`
3. Restart Odoo :
```bash
docker compose restart odoo
```
4. Dans Odoo → Activer le mode développeur → Mettre à jour la liste des applications

---

## Accès

| Service   | URL / Hôte              |
|-----------|------------------------|
| Odoo      | http://localhost:8070  |
| Master PW | `admin123`             |
| DB user   | `odoo` / `odoo`        |

---

## Odoo local (pas de conflit)

Ton Odoo local tourne sur `localhost:8069` avec ses propres fichiers.  
Docker tourne sur `localhost:8070` avec sa propre base PostgreSQL dans un volume isolé.  
Les deux coexistent sans interférence.
"# certmind-Odoo19" 
