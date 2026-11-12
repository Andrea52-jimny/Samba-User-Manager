#!/usr/bin/env bash
# Container entrypoint: seed the persistent state on first start, then run
# smbd and the FastAPI app side by side in the same namespace, so that users
# created with useradd/smbpasswd are visible to both.
set -euo pipefail

seed_if_empty() {
  local target="$1"
  local default="$2"
  if [ ! -s "${target}" ]; then
    echo "[entrypoint] seeding ${target}"
    cp "${default}" "${target}"
  fi
}

# --- Persistent Linux users and groups --------------------------------------
# IMPORTANT: /etc/passwd, /etc/shadow, /etc/group and /etc/gshadow are NOT
# bind-mounted directly. If they were, each would be a mountpoint, and
# useradd/groupadd/passwd write with a "temp file + rename()" scheme: rename()
# cannot replace a mountpoint, so they would fail with errors such as
# "failure while writing changes to /etc/group". Instead ONE directory
# (PERSIST_USERS_DIR) holds persistent copies, which are copied INTO /etc at
# every start; after each change the app copies them back OUT to that same
# directory (see app/samba_manager.py).
PERSIST_USERS_DIR="${PERSIST_USERS_DIR:-/persist/users}"
mkdir -p "${PERSIST_USERS_DIR}"
for f in passwd shadow group gshadow; do
  if [ ! -s "${PERSIST_USERS_DIR}/${f}" ]; then
    echo "[entrypoint] seeding ${PERSIST_USERS_DIR}/${f}"
    cp "/opt/defaults/${f}" "${PERSIST_USERS_DIR}/${f}"
  fi
  cp "${PERSIST_USERS_DIR}/${f}" "/etc/${f}"
done

# --- Samba configuration and state (volumes on /etc/samba, /var/lib/samba) --
mkdir -p /etc/samba /var/lib/samba/private /var/log/samba
seed_if_empty /etc/samba/smb.conf /opt/defaults/smb.conf.default

# --- System group holding every Samba user managed by the app ---------------
if ! getent group "${SAMBA_GROUP:-smbgroup}" >/dev/null; then
  groupadd "${SAMBA_GROUP:-smbgroup}"
  for f in passwd shadow group gshadow; do
    cp "/etc/${f}" "${PERSIST_USERS_DIR}/${f}"
  done
fi

# --- Data directory for the application's SQLite database -------------------
mkdir -p "$(dirname "${SMB_DB_PATH:-/app/data/smb_manager.db}")"

# --- Database initialisation on the very first start ------------------------
if [ ! -s "${SMB_DB_PATH:-/app/data/smb_manager.db}" ]; then
  echo "[entrypoint] no database found, initialising..."
  python3 /app/init_db.py
fi

# --- Start smbd (background job here, supervised below) ---------------------
echo "[entrypoint] starting smbd"
/usr/sbin/smbd --foreground --no-process-group &
SMBD_PID=$!

# --- Start the FastAPI application ------------------------------------------
echo "[entrypoint] starting SMB User Manager (uvicorn)"
cd /app
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
APP_PID=$!

# If either process dies, stop the other and exit, so that Docker's restart
# policy brings the whole container back up in a clean state.
terminate() {
  echo "[entrypoint] shutting down..."
  kill "${SMBD_PID}" "${APP_PID}" 2>/dev/null || true
  wait
}
trap terminate SIGTERM SIGINT

wait -n "${SMBD_PID}" "${APP_PID}"
EXIT_CODE=$?
echo "[entrypoint] one of the two processes exited (code ${EXIT_CODE}), stopping the container"
terminate
exit "${EXIT_CODE}"
