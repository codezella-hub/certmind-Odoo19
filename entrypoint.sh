#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# entrypoint.sh — point d'entrée du container Odoo
#
# Remplace les ${VARIABLES} de odoo.conf.template par les valeurs
# des variables d'environnement, puis lance Odoo. La même image
# fonctionne ainsi en dev (docker-compose) et en prod (Azure) :
# seules les variables changent.
# ─────────────────────────────────────────────────────────────────
set -e

# Valeurs par défaut si une variable n'est pas fournie.
: "${DB_HOST:=db}"
: "${DB_PORT:=5432}"
: "${DB_USER:=odoo}"
: "${DB_PASSWORD:=odoo}"
: "${DB_SSLMODE:=disable}"
: "${ODOO_ADMIN_PASSWD:=admin}"
: "${ODOO_WORKERS:=0}"
: "${ODOO_LOG_LEVEL:=info}"

export DB_HOST DB_PORT DB_USER DB_PASSWORD DB_SSLMODE \
       ODOO_ADMIN_PASSWD ODOO_WORKERS ODOO_LOG_LEVEL

echo "[entrypoint] DB_HOST=${DB_HOST}:${DB_PORT} user=${DB_USER} ssl=${DB_SSLMODE}"
echo "[entrypoint] workers=${ODOO_WORKERS} log_level=${ODOO_LOG_LEVEL}"
# Les mots de passe ne sont jamais affichés.

envsubst < /etc/odoo/odoo.conf.template > /etc/odoo/odoo.conf
echo "[entrypoint] /etc/odoo/odoo.conf généré."

exec odoo --config=/etc/odoo/odoo.conf "$@"
