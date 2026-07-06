#!/usr/bin/env bash
# DA ESEGUIRE UNA TANTUM: allinea il repository Git allo stato REALE e
# funzionante di produzione (/opt/samba-manager), cosi' che i futuri
# 'update.sh' restino sempre coerenti (stessa struttura app/, static/,
# templates/ sia nel repo che in produzione).
#
# Dopo questo script, /opt/scripts/HomeLab-smbUserManager (repo) sara'
# una copia esatta del codice di /opt/samba-manager (esclusi venv/data/db).
set -euo pipefail

APP_DIR="/opt/samba-manager"
REPO_DIR="/opt/scripts/HomeLab-smbUserManager"

if [[ ! -d "${REPO_DIR}/.git" ]]; then
  echo "ERRORE: ${REPO_DIR} non e' un repository git (manca .git)." >&2
  exit 1
fi
if [[ ! -d "${APP_DIR}/app" ]]; then
  echo "ERRORE: ${APP_DIR}/app non trovato: controlla il valore di APP_DIR." >&2
  exit 1
fi

BACKUP="${REPO_DIR}.bak-$(date +%Y%m%d-%H%M%S)"
echo "==> [1/4] Backup di sicurezza del repo attuale in ${BACKUP}"
cp -a "${REPO_DIR}" "${BACKUP}"

echo "==> [2/4] Svuoto il repo (tranne .git) per ripartire da uno stato pulito"
find "${REPO_DIR}" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +

echo "==> [3/4] Copio lo stato attuale di produzione nel repo (esclusi dati/venv/cache)"
tar -cf - \
  --exclude='venv' \
  --exclude='data' \
  --exclude='state' \
  --exclude='*.db' \
  --exclude='*.db-journal' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  -C "${APP_DIR}" . \
  | tar -xf - -C "${REPO_DIR}"

cd "${REPO_DIR}"
cat > .gitignore <<'EOF'
venv/
data/
state/
*.db
*.db-journal
__pycache__/
*.pyc
EOF

echo "==> [4/4] Commit e push"
git add -A
git commit -m "Allinea il repo allo stato reale di produzione (app/, static/, templates/)" || echo "(nessuna modifica da committare)"
git push

echo ""
echo "Fatto. Il repository ora rispecchia esattamente cio' che gira su ${APP_DIR}."
echo "Backup del vecchio repo conservato in: ${BACKUP}"
echo "Da ora in poi 'update.sh' sincronizzera' correttamente le modifiche future."
