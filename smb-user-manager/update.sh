#!/usr/bin/env bash
# Aggiorna l'app in produzione a partire dal repo Git, SENZA toccare
# database SQLite, ambiente virtuale ne' configurazioni locali.
# Da eseguire come root dentro il container LXC.
set -euo pipefail

REPO_DIR="/opt/scripts/HomeLab-smbUserManager"   # repo Git (sorgente)
APP_DIR="/opt/samba-manager"                     # cartella in esecuzione
SERVICE_NAME="samba-manager"                     # nome unit systemd

echo "==> [1/6] Pull ultime modifiche da GitHub"
cd "${REPO_DIR}"
git fetch --all
git reset --hard origin/main   # scarta eventuali modifiche locali nel repo
git pull
echo "    Ultimo commit: $(git log -1 --oneline)"

# Controllo di sicurezza: il repo DEVE avere la stessa struttura della
# produzione (app/, static/, templates/), altrimenti il tar sottostante
# copierebbe file in cartelle che l'app in esecuzione non legge mai,
# dando l'impressione che "non si aggiorna nulla".
if [[ ! -d "${REPO_DIR}/app" ]]; then
  echo "ERRORE: ${REPO_DIR}/app non esiste." >&2
  echo "Il repo non ha la struttura attesa (app/, static/, templates/)." >&2
  echo "Esegui prima: ./reset-repo-from-prod.sh" >&2
  exit 1
fi

echo "==> [2/6] Sincronizzazione file verso ${APP_DIR}"
# rsync non e' disponibile in questo container: si usa tar per copiare in modo
# ricorsivo escludendo dati runtime/venv/cache (cp da solo non supporta
# esclusioni ricorsive). NOTA: a differenza di rsync --delete, i file rimossi
# dal repo NON vengono rimossi da APP_DIR: restano li' finche' non li elimini
# a mano (rm) se necessario.
BEFORE_HASH=$(md5sum "${APP_DIR}/app/main.py" 2>/dev/null | awk '{print $1}' || echo "n/a")

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

AFTER_HASH=$(md5sum "${APP_DIR}/app/main.py" 2>/dev/null | awk '{print $1}' || echo "n/a")
if [[ "${BEFORE_HASH}" == "${AFTER_HASH}" ]]; then
  echo "    main.py invariato (nessuna modifica in questo aggiornamento, e' normale se non hai toccato quel file)"
else
  echo "    main.py aggiornato: hash cambiato (${BEFORE_HASH} -> ${AFTER_HASH})"
fi

echo "==> [3/6] Aggiornamento dipendenze Python"
cd "${APP_DIR}"
source venv/bin/activate
pip install --upgrade -r requirements.txt --quiet
deactivate

echo "==> [4/6] Riavvio servizio"
systemctl restart "${SERVICE_NAME}"
sleep 2

echo "==> [5/6] Verifica stato"
systemctl is-active --quiet "${SERVICE_NAME}" && echo "OK: ${SERVICE_NAME} attivo" || {
  echo "ERRORE: il servizio non e' partito, controlla i log:"
  echo "  journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  exit 1
}

echo "==> [6/6] Log recenti"
journalctl -u "${SERVICE_NAME}" -n 10 --no-pager
