#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# entrypoint.sh — point d'entrée du container Odoo
# ─────────────────────────────────────────────────────────────────
set -e

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

envsubst < /etc/odoo/odoo.conf.template > /etc/odoo/odoo.conf
echo "[entrypoint] /etc/odoo/odoo.conf généré."

# ── Correctif Azure : force wsgi.url_scheme=https ─────────────────
# Odoo 19 (http.py:2830) n'active proxy_mode que si X-Forwarded-Host
# est présent. Azure Container Apps envoie X-Forwarded-Proto:https
# mais pas X-Forwarded-Host. Ce script Python corrige l'environnement
# WSGI à chaque requête AVANT qu'Odoo le lise.
python3 - << 'INSTALL_FIX'
fix_code = '''
import logging
_logger = logging.getLogger("azure_proxy_fix")

def _fix_azure_https():
    try:
        import odoo.http as http_mod
        if getattr(http_mod.Application, "_azure_fix", False):
            return
        _orig = http_mod.Application.__call__
        def __call__(self, environ, start_response):
            if environ.get("HTTP_X_FORWARDED_PROTO", "").lower() == "https":
                environ["wsgi.url_scheme"] = "https"
                if not environ.get("HTTP_X_FORWARDED_HOST"):
                    environ["HTTP_X_FORWARDED_HOST"] = environ.get("HTTP_HOST", "")
            return _orig(self, environ, start_response)
        http_mod.Application.__call__ = __call__
        http_mod.Application._azure_fix = True
        _logger.warning("azure_proxy_fix ACTIF")
    except Exception as exc:
        _logger.error("azure_proxy_fix ECHEC: %s", exc)

_fix_azure_https()
'''

import site, os, sys

candidates = []
try:
    candidates += site.getsitepackages()
except Exception:
    pass
try:
    candidates.append(site.getusersitepackages())
except Exception:
    pass

installed = False
for d in candidates:
    target = os.path.join(d, "sitecustomize.py")
    try:
        with open(target, "w") as f:
            f.write(fix_code)
        print(f"[entrypoint] azure_proxy_fix installé dans {target}")
        installed = True
        break
    except Exception:
        continue

if not installed:
    print("[entrypoint] AVERTISSEMENT: impossible d'installer azure_proxy_fix", file=sys.stderr)

INSTALL_FIX
# ──────────────────────────────────────────────────────────────────

exec odoo --config=/etc/odoo/odoo.conf "$@"
