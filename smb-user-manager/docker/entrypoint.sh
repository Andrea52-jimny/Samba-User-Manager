#!/usr/bin/env bash
# Entrypoint del container: seeda lo stato persistente al primo avvio,
# poi lancia smbd e l'app FastAPI nello stesso processo/namespace, cosi'
# che gli utenti creati da useradd/smbpasswd siano visibili a entrambi.
set -euo pipefail

seed_if_empty() {
  local target="$1"
  local default="$2"
  if [ ! -s "${target}" ]; then
    echo "[entrypoint] seed iniziale di ${target}"
    cp "${default}" "${target}"
  fi
}

# --- Stato utenti/gruppi di sistema (bind-mount di singoli file da compose) ---
seed_if_empty /etc/passwd  /opt/defaults/passwd
seed_if_empty /etc/shadow  /opt/defaults/shadow
seed_if_empty /etc/group   /opt/defaults/group
seed_if_empty /etc/gshadow /opt/defaults/gshadow

# --- Configurazione e stato Samba (volumi su /etc/samba e /var/lib/samba) ---
mkdir -p /etc/samba /var/lib/samba/private /var/log/samba
seed_if_empty /etc/samba/smb.conf /opt/defaults/smb.conf.default

# --- Gruppo di sistema per gli utenti Samba gestiti dall'app ---
getent group "${SAMBA_GROUP:-smbgroup}" >/dev/null || groupadd "${SAMBA_GROUP:-smbgroup}"

# --- Cartella dati persistente per il DB SQLite dell'app ---
mkdir -p "$(dirname "${SMB_DB_PATH:-/app/data/smb_manager.db}")"

# --- Inizializzazione DB al primissimo avvio ---
if [ ! -s "${SMB_DB_PATH:-/app/data/smb_manager.db}" ]; then
  echo "[entrypoint] database non trovato, inizializzo..."
  python3 /app/init_db.py
fi

# --- Avvio smbd in foreground (background job qui, monitorato sotto) ---
echo "[entrypoint] avvio smbd"
/usr/sbin/smbd --foreground --no-process-group &
SMBD_PID=$!

# --- Avvio dell'app FastAPI ---
echo "[entrypoint] avvio Samba Access Manager (uvicorn)"
cd /app
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
APP_PID=$!

# Se uno dei due processi muore, ferma anche l'altro e termina il container
# (systemd/Docker restart policy si occupa di ripartire tutto puliti).
terminate() {
  echo "[entrypoint] arresto in corso..."
  kill "${SMBD_PID}" "${APP_PID}" 2>/dev/null || true
  wait
}
trap terminate SIGTERM SIGINT

wait -n "${SMBD_PID}" "${APP_PID}"
EXIT_CODE=$?
echo "[entrypoint] uno dei due processi e' terminato (exit ${EXIT_CODE}), chiudo il container"
terminate
exit "${EXIT_CODE}"
