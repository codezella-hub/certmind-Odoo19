# ─────────────────────────────────────────────────────────────────
# Dockerfile — Odoo 19 + modules Certmind
#
# POINT CRITIQUE : torch en version CPU uniquement.
# ultralytics et silero-vad déclarent torch/torchaudio en dépendance.
# Installés normalement, pip va chercher torch sur PyPI (version GPU)
# et télécharge ~1 Go de CUDA, inutile sur Azure qui n'a pas de GPU.
# On les installe donc avec --no-deps, après le torch CPU.
# ─────────────────────────────────────────────────────────────────

FROM odoo:19.0

USER root

# ── 1. Outils système ─────────────────────────────────────────────
# gettext-base : fournit envsubst (génération de odoo.conf)
# ffmpeg       : conversion WebM→MP4 du pipeline proctoring
# wkhtmltopdf  : rapports PDF Odoo (certificats)
# libgl1 etc.  : dépendances natives d'OpenCV et MediaPipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    gettext-base curl \
    ffmpeg \
    wkhtmltopdf xfonts-base xfonts-75dpi \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN ffmpeg -version | head -1 && wkhtmltopdf --version \
    && echo "=== Outils système OK ==="

# ── 2. Configuration pip (connexions lentes) ─────────────────────
ENV PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=15 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

# ── 2b. Limitation des threads des bibliothèques de calcul ───────
#
# numpy, torch et mediapipe s'appuient sur OpenBLAS, qui tente de
# créer un thread par cœur CPU détecté (souvent 16). Dans un container
# contraint, pthread_create échoue :
#   OpenBLAS blas_thread_init: pthread_create failed ... 
# et le processus Odoo meurt sans écrire d'erreur Python — d'où des
# crashs silencieux à l'installation du module de proctoring.
#
# On force donc un seul thread par bibliothèque. L'analyse vidéo est
# marginalement plus lente, mais elle ne fait plus tomber le serveur.
ENV OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1

# ── 3. torch CPU (~200 Mo au lieu de ~1 Go avec CUDA) ────────────
RUN pip3 install --ignore-installed \
    --index-url https://download.pytorch.org/whl/cpu \
    torch torchvision torchaudio

# ── 4. Dépendances, sans les paquets qui retirent torch ─────────
COPY requirements.txt /tmp/requirements.txt
RUN grep -vE '^(ultralytics|silero-vad)' /tmp/requirements.txt > /tmp/req-base.txt \
    && echo "--- paquets installés avec leurs dépendances ---" \
    && grep -vE '^\s*(#|$)' /tmp/req-base.txt \
    && pip3 install --ignore-installed -r /tmp/req-base.txt

# ── 5. Paquets torch-dépendants, sans leurs dépendances ─────────
RUN pip3 install --ignore-installed --no-deps \
    ultralytics ultralytics-thop silero-vad

# ── 6. Dépendances légères d'ultralytics (ajoutées à la main) ────
RUN pip3 install --ignore-installed \
    polars psutil py-cpuinfo pyyaml tqdm pandas seaborn

# ── 7. Vérification : le build échoue si une lib manque ─────────
RUN python3 -c "import cv2;         print('cv2        ', cv2.__version__)" \
 && python3 -c "import numpy;       print('numpy      ', numpy.__version__)" \
 && python3 -c "import mediapipe;   print('mediapipe  ', mediapipe.__version__)" \
 && python3 -c "import torch;       print('torch      ', torch.__version__)" \
 && python3 -c "import ultralytics; print('ultralytics OK')" \
 && python3 -c "import librosa;     print('librosa    OK')" \
 && python3 -c "import jwt;         print('PyJWT      OK')" \
 && python3 -c "import pydantic;    print('pydantic   OK')" \
 && python3 -c "import dotenv;      print('dotenv     OK')" \
 && python3 -c "import reportlab;   print('reportlab  OK')" \
 && python3 -c "import openai;      print('openai     OK')" \
 && python3 -c "import boto3;       print('boto3      OK')" \
 && python3 -c "import openpyxl;    print('openpyxl   OK')" \
 && echo "=== Toutes les dépendances Python OK ==="

# ── 8. Application ────────────────────────────────────────────────
COPY ./custom_addons /mnt/extra-addons
COPY ./config/odoo.conf.template /etc/odoo/odoo.conf.template
COPY ./entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && chown -R odoo:odoo /mnt/extra-addons \
    && chown odoo:odoo /etc/odoo/odoo.conf.template /entrypoint.sh

USER odoo

# start-period long : Odoo met du temps à charger tous les modules
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
    CMD curl -f http://localhost:8069/web/health || exit 1

EXPOSE 8069
ENTRYPOINT ["/entrypoint.sh"]
CMD []
