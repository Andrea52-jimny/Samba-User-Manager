# SMB User Manager - a single image containing both Samba (smbd) and the
# FastAPI web application.
#
# They must run in the SAME container: the app manages real Linux users
# (useradd / smbpasswd / setfacl) that the Samba daemon has to see in the same
# system namespace. See docs/ARCHITECTURE.md for the full reasoning.
FROM debian:bookworm-slim

# Timezone baked into the image. Override at build time with
#   docker compose build --build-arg TZ=America/New_York
# and keep the TZ environment variable in docker-compose.yml in sync.
ARG TZ=Europe/Rome

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    TZ=${TZ}

RUN apt-get update && apt-get install -y --no-install-recommends \
        samba \
        samba-common-bin \
        acl \
        python3 \
        python3-venv \
        python3-pip \
        curl \
        tzdata \
    && ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

# Keep a pristine copy of the system files that will later be backed by
# persistent volumes (see docker/entrypoint.sh). They are used to seed those
# volumes on the very first start, while the host directories are still empty.
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

# Defaults; all of them are overridden by docker-compose.yml at runtime.
ENV SMB_ROOT_PATH=/mnt/dati \
    SMB_CONF_PATH=/etc/samba/smb.conf \
    SMB_SHARE_SECTION=Dati \
    SAMBA_GROUP=smbgroup \
    SMB_DB_PATH=/app/data/smb_manager.db \
    PERSIST_USERS_DIR=/persist/users \
    ADMIN_USERNAME=admin \
    ADMIN_PASSWORD=ChangeMe123!

# 8000 web UI / API, 445 SMB, 139 NetBIOS (not published by default).
EXPOSE 8000 445 139

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD curl -fs http://127.0.0.1:8000/login >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
