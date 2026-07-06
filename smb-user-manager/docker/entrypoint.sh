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

# --- Stato utenti/gruppi di sistema -----------------------------------------
# IMPORTANTE: /etc/passwd, /etc/shadow, /etc/group, /etc/gshadow NON sono
# bind-montati direttamente (se lo fossero, sarebbero dei mountpoint e
# useradd/groupadd/passwd, che scrivono con schema "tmpfile + rename()",
# fallirebbero con "failure while writing changes to /etc/group": un rename
# non puo' sostituire un mountpoint). Si monta invece UNA directory
# (PERSIST_USERS_DIR) con le copie persistenti, che vengono copiate DENTRO
# /etc a ogni avvio; dopo ogni modifica (vedi app/samba_manager.py) l'app
# ricopia i file aggiornati FUORI, verso questa stessa directory.
PERSIST_USERS_DIR="${PERSIST_USERS_DIR:-/persist/users}"
mkdir -p "${PERSIST_USERS_DIR}"
for f in passwd shadow group gshadow; do
  if [ ! -s "${PERSIST_USERS_DIR}/${f}" ]; then
    echo "[entrypoint] seed iniziale di ${PERSIST_USERS_DIR}/${f}"
    cp "/opt/defaults/${f}" "${PERSIST_USERS_DIR}/${f}"
  fi
  cp "${PERSIST_USERS_DIR}/${f}" "/etc/${f}"
done

# --- Configurazione e stato Samba (volumi su /etc/samba e /var/lib/samba) ---
mkdir -p /etc/samba /var/lib/samba/private /var/log/samba
seed_if_empty /etc/samba/smb.conf /opt/defaults/smb.conf.default

# --- Gruppo di sistema per gli utenti Samba gestiti dall'app ---
if ! getent group "${SAMBA_GROUP:-smbgroup}" >/dev/null; then
  groupadd "${SAMBA_GROUP:-smbgroup}"
  for f in passwd shadow group gshadow; do
    cp "/etc/${f}" "${PERSIST_USERS_DIR}/${f}"
  done
fi

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
