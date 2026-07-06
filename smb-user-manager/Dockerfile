# Samba Access Manager - immagine unica che contiene sia Samba (smbd) sia
# la Web App FastAPI. Devono girare nello STESSO container perche' l'app
# gestisce utenti Linux reali (useradd/smbpasswd/setfacl) che devono essere
# visti dal demone Samba nello stesso namespace di sistema.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
        samba \
        samba-common-bin \
        acl \
        python3 \
        python3-venv \
        python3-pip \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Salva una copia "pulita" dei file di sistema che verranno poi montati come
# volumi persistenti (vedi entrypoint.sh): serve per popolarli al primissimo
# avvio, quando i volumi sul host sono ancora vuoti.
RUN mkdir -p /opt/defaults \
    && cp /etc/passwd /etc/shadow /etc/group /etc/gshadow /opt/defaults/ \
    && (cp /etc/samba/smb.conf /opt/defaults/smb.conf 2>/dev/null || true)

WORKDIR /app

COPY requirements.txt .
RUN pip install --break-system-packages --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY templates ./templates
COPY init_db.py .
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/smb.conf.default /opt/defaults/smb.conf.default
RUN chmod +x /entrypoint.sh

ENV SMB_ROOT_PATH=/mnt/dati \
    SMB_CONF_PATH=/etc/samba/smb.conf \
    SAMBA_GROUP=smbgroup \
    SMB_DB_PATH=/app/data/smb_manager.db \
    PERSIST_USERS_DIR=/persist/users \
    ADMIN_USERNAME=admin \
    ADMIN_PASSWORD=ChangeMe123!

EXPOSE 8000 445 139

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD curl -fs http://127.0.0.1:8000/login >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
