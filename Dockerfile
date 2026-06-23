FROM odoo:19.0

USER root

# Install extra Python dependencies if needed
# Uncomment and add packages below when required:
# RUN pip3 install --no-cache-dir --break-system-packages \
#     pandas \
#     openpyxl
# Installer les dépendances Python
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt


COPY ./custom_addons /mnt/extra-addons
COPY ./config/odoo.conf /etc/odoo/odoo.conf

RUN chown -R odoo:odoo /mnt/extra-addons \
    && chown odoo:odoo /etc/odoo/odoo.conf

USER odoo

EXPOSE 8069
CMD ["odoo", "--config=/etc/odoo/odoo.conf"]