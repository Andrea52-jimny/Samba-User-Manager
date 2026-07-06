#!/usr/bin/env bash
# Pulizia della cartella di produzione /opt/samba-manager.
# DI DEFAULT E' UNA DRY-RUN: mostra solo cosa verrebbe rimosso.
# Per rimuovere davvero:  ./cleanup.sh --force
set -euo pipefail

APP_DIR="/opt/samba-manager"
FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

# Whitelist: tutto cio' che serve al funzionamento reale dell'app.
# NON viene mai toccato.
KEEP=(app data static templates venv init_db.py requirements.txt
      samba-manager.service update.sh cleanup.sh install.sh
      reset-repo-from-prod.sh README.md .gitignore
      Dockerfile docker-compose.yml docker .dockerignore state)

is_kept() {
  local name="$1"
  for k in "${KEEP[@]}"; do
    [[ "$name" == "$k" ]] && return 0
  done
  return 1
}

echo "==> Contenuto attuale di ${APP_DIR}:"
ls -la "${APP_DIR}"
echo ""

echo "==> Elementi di primo livello NON nella whitelist (candidati alla rimozione):"
TO_REMOVE=()
shopt -s dotglob nullglob
for entry in "${APP_DIR}"/*; do
  name="$(basename "$entry")"
  if [[ "$name" == "." || "$name" == ".." ]]; then continue; fi
  if ! is_kept "$name"; then
    TO_REMOVE+=("$entry")
    echo "  - $entry"
  fi
done
shopt -u dotglob nullglob

if [[ ${#TO_REMOVE[@]} -eq 0 ]]; then
  echo "  (nessuno: la cartella di primo livello e' gia' pulita)"
fi

echo ""
echo "==> Cache Python da ripulire dentro app/, static/, templates/ (__pycache__, *.pyc):"
find "${APP_DIR}/app" "${APP_DIR}/static" "${APP_DIR}/templates" \
     \( -name '__pycache__' -o -name '*.pyc' \) -print 2>/dev/null || true

if [[ "$FORCE" != true ]]; then
  echo ""
  echo "Modalita' DRY-RUN: nessun file e' stato rimosso."
  echo "Rilancia con:  $0 --force   per eseguire la rimozione reale."
  exit 0
fi

echo ""
echo "==> Rimozione in corso..."
for entry in "${TO_REMOVE[@]}"; do
  echo "  rm -rf $entry"
  rm -rf "$entry"
done

find "${APP_DIR}/app" "${APP_DIR}/static" "${APP_DIR}/templates" \
     \( -name '__pycache__' -o -name '*.pyc' \) -exec rm -rf {} + 2>/dev/null || true

echo "==> Pulizia completata."
