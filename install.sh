#!/usr/bin/env bash
#
# install.sh - Setup della Web App "Samba Manager" dentro il container LXC.
#
# USO:
#   1. Copia l'intera cartella samba-manager/ dentro il container, es. in /root/samba-manager
#   2. cd /root/samba-manager
#   3. sudo bash install.sh
#
# Il container deve avere già il bind mount attivo verso il pool ZFS
# dell'host (path atteso: /mnt/dati). Vedi la sezione "PREREQUISITI SULL'HOST"
# più sotto: quei comandi vanno eseguiti sull'HOST (TrueNAS/Proxmox), NON
# dentro questo container, e sono riportati solo come promemoria.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Questo script deve essere eseguito come root (usa sudo)." >&2
  exit 1
fi

APP_DIR="/opt/samba-manager"
SAMBA_GROUP="smbgroup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> [1/7] Aggiornamento pacchetti e installazione dipendenze di sistema"
apt-get update -y
apt-get install -y \
  samba \
  acl \
  python3 \
  python3-venv \
  python3-pip

echo "==> [2/7] Verifica che il bind mount /mnt/dati sia presente e scrivibile"
if ! mountpoint -q /mnt/dati 2>/dev/null && [[ ! -d /mnt/dati ]]; then
  echo "ATTENZIONE: /mnt/dati non esiste in questo container." >&2
  echo "Configura il bind mount LXC verso il dataset ZFS dell'host prima di continuare." >&2
  exit 1
fi

echo "==> [3/7] Creazione gruppo Samba/Linux condiviso '${SAMBA_GROUP}'"
getent group "${SAMBA_GROUP}" >/dev/null || groupadd "${SAMBA_GROUP}"

echo "==> [4/7] Copia applicazione in ${APP_DIR}"
mkdir -p "${APP_DIR}"
rsync -a --exclude 'venv' --exclude '__pycache__' "${SCRIPT_DIR}/" "${APP_DIR}/"
mkdir -p "${APP_DIR}/data"

echo "==> [5/7] Creazione ambiente virtuale Python e installazione dipendenze"
cd "${APP_DIR}"
python3 -m venv venv
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install -r requirements.txt

echo "==> [6/7] Backup di sicurezza di smb.conf originale"
cp -n /etc/samba/smb.conf "/etc/samba/smb.conf.pre-samba-manager.bak" || true

echo "==> [7/7] Installazione servizio systemd"
cp "${APP_DIR}/samba-manager.service" /etc/systemd/system/samba-manager.service
systemctl daemon-reload
systemctl enable samba-manager.service

cat <<'EOF'

============================================================
 Installazione completata.
============================================================

PROSSIMI PASSI (obbligatori):

  1) Crea il primo amministratore della Web App:
       cd /opt/samba-manager
       source venv/bin/activate
       python init_db.py

  2) Avvia il servizio:
       systemctl start samba-manager

  3) Apri il browser su:
       http://<ip-del-container>:8000

  4) Accedi con le credenziali admin create al punto 1, poi:
     - se compare l'avviso "force user = smbuser", clicca su
       "Correggi automaticamente" per sistemare /etc/samba/smb.conf
       (viene fatto un backup automatico con timestamp prima di ogni modifica)
     - crea i tuoi utenti e assegna i permessi dall'albero delle cartelle

NOTA IMPORTANTE (da eseguire SULL'HOST, non nel container):
  Perché le ACL POSIX per-utente vengano rispettate dal file system,
  il dataset ZFS che fornisce /mnt/dati deve avere il supporto ACL attivo.
  Sull'host (es. shell TrueNAS/Proxmox) esegui una tantum:

      zfs set acltype=posixacl <pool>/<dataset>
      zfs set xattr=sa <pool>/<dataset>

  Sostituisci <pool>/<dataset> con il dataset reale che fornisce /mnt/dati
  (es. data-pool/condivisione_rete indicato nel brief).

============================================================
EOF
