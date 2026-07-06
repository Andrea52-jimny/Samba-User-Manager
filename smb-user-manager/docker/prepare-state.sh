#!/usr/bin/env bash
# Da eseguire prima del primo "docker compose up" (o dopo un cambiamento di
# struttura dei volumi), nella cartella che contiene docker-compose.yml.
# Crea semplicemente le directory persistenti se non esistono ancora.
set -euo pipefail

mkdir -p state/app-data state/samba-etc state/samba-private state/samba-log state/users

echo "Struttura ./state/ pronta. Ora puoi eseguire: docker compose up -d --build"
