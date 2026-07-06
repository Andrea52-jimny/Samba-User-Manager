#!/usr/bin/env bash
# Aggiorna l'app in produzione a partire dal repo Git, SENZA toccare
# database SQLite, ambiente virtuale ne' configurazioni locali.
# Da eseguire come root dentro il container LXC.
set -euo pipefail

REPO_DIR="/opt/scripts/HomeLab-smbUserManager"   # repo Git (sorgente)
APP_DIR="/opt/samba-manager"                     # cartella in esecuzione
SERVICE_NAME="samba-manager"                     # nome unit systemd

echo "==> [1/5] Pull ultime modifiche da GitHub"
cd "${REPO_DIR}"
git fetch --all
git reset --hard origin/main   # scarta eventuali modifiche locali nel repo
git pull

echo "==> [2/5] Sincronizzazione file verso ${APP_DIR}"
# rsync non e' disponibile in questo container: si usa tar per copiare in modo
# ricorsivo escludendo dati runtime/venv/cache (cp da solo non supporta
# esclusioni ricorsive). NOTA: a differenza di rsync --delete, i file rimossi
# dal repo NON vengono rimossi da APP_DIR: restano li' finche' non li elimini
# a mano (rm) se necessario.
mkdir -p "${APP_DIR}"
tar -cf - \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='data' \
  --exclude='*.db' \
  --exclude='*.db-journal' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.gitignore' \
  -C "${REPO_DIR}" . \
  | tar -xf - -C "${APP_DIR}"

echo "==> [3/5] Aggiornamento dipendenze Python"
cd "${APP_DIR}"
source venv/bin/activate
pip install --upgrade -r requirements.txt --quiet
deactivate

echo "==> [4/5] Riavvio servizio"
systemctl restart "${SERVICE_NAME}"
sleep 2

echo "==> [5/5] Verifica stato"
systemctl is-active --quiet "${SERVICE_NAME}" && echo "OK: ${SERVICE_NAME} attivo" || {
  echo "ERRORE: il servizio non e' partito, controlla i log:"
  echo "  journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  exit 1
}

echo ""
echo "Aggiornamento completato. Log recenti:"
journalctl -u "${SERVICE_NAME}" -n 10 --no-pager
