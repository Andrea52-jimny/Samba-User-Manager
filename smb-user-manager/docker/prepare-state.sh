#!/usr/bin/env bash
# Da eseguire UNA VOLTA, prima del primissimo "docker compose up", nella
# cartella che contiene docker-compose.yml.
#
# Motivo: se un percorso bind-mount non esiste ancora sull'host, Docker lo
# crea come DIRECTORY, non come file. Dato che /etc/passwd, /etc/shadow,
# /etc/group e /etc/gshadow devono essere singoli FILE dentro al container,
# vanno pre-creati come file vuoti sull'host, altrimenti il container non
# si avvia (o smbd/useradd falliscono in modo poco chiaro).
set -euo pipefail

mkdir -p state/app-data state/samba-etc state/samba-private state/samba-log

for f in passwd shadow group gshadow; do
  [ -f "state/${f}" ] || touch "state/${f}"
done

echo "Struttura ./state/ pronta. Ora puoi eseguire: docker compose up -d --build"
