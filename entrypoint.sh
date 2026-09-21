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

# ─── Correctif Azure Container Apps ────────────────────────────────────────────
# Odoo 19 (http.py:2830) n'active proxy_mode QUE si X-Forwarded-Host est présent.
# Azure envoie X-Forwarded-Proto:https mais pas X-Forwarded-Host.
# Ce wrapper WSGI ajoute X-Forwarded-Host = HTTP_HOST quand il manque,
# ce qui permet à Odoo d'activer ProxyFix et de générer des URL en https.
cat > /tmp/odoo_proxy_wrapper.py << 'PYWRAP'
"""
Wrapper WSGI minimal : ajoute HTTP_X_FORWARDED_HOST si manquant.
Placé dans /tmp et chargé via PYTHONSTARTUP n'a aucun effet —
on patche directement odoo.http avant le démarrage.
"""
import sys, functools

def _patch():
    try:
        import odoo.http as _http
        if getattr(_http.Application, '_azure_proxy_fix', False):
            return
        _orig = _http.Application.__call__
        @functools.wraps(_orig)
        def _fixed(self, environ, start_response):
            if (environ.get('HTTP_X_FORWARDED_PROTO')
                    and not environ.get('HTTP_X_FORWARDED_HOST')
                    and environ.get('HTTP_HOST')):
                environ['HTTP_X_FORWARDED_HOST'] = environ['HTTP_HOST']
            return _orig(self, environ, start_response)
        _http.Application.__call__ = _fixed
        _http.Application._azure_proxy_fix = True
        import logging
        logging.getLogger(__name__).info(
            "azure_proxy_fix: X-Forwarded-Host activé (Azure Container Apps)")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("azure_proxy_fix: échec du patch — %s", e)

_patch()
PYWRAP

# Injecter le patch au démarrage Python via sitecustomize
SITE_PACKAGES=$(python3 -c "import site; print(site.getsitepackages()[0])" 2>/dev/null || echo "/usr/local/lib/python3.11/dist-packages")
cp /tmp/odoo_proxy_wrapper.py "${SITE_PACKAGES}/sitecustomize.py" 2>/dev/null || \
    cp /tmp/odoo_proxy_wrapper.py /usr/lib/python3/dist-packages/sitecustomize.py 2>/dev/null || \
    echo "[entrypoint] AVERTISSEMENT: impossible d'installer sitecustomize.py — le patch proxy ne sera pas actif"

echo "[entrypoint] azure_proxy_fix installé via sitecustomize.py"
# ───────────────────────────────────────────────────────────────────────────────

exec odoo --config=/etc/odoo/odoo.conf "$@"