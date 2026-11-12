#!/usr/bin/env bash
# Run once before the first "docker compose up" (or after changing the volume
# layout), from the directory containing docker-compose.yml. It only creates
# the persistent directories if they do not exist yet.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

mkdir -p state/app-data state/samba-etc state/samba-private state/samba-log state/users

echo "./state/ is ready. You can now run: docker compose up -d --build"
