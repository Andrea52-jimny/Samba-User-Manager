#!/usr/bin/env bash
# Script di installazione per container LXC (Debian/Ubuntu based).
# Da eseguire come root DENTRO il container.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAMBA_GROUP="${SAMBA_GROUP:-smbgroup}"
SMB_ROOT_PATH="${SMB_ROOT_PATH:-/mnt/dati}"

echo "==> [1/7] Aggiornamento pacchetti e dipendenze di sistema"
apt-get update -y
apt-get install -y samba samba-common-bin acl python3 python3-venv python3-pip

echo "==> [2/7] Creazione gruppo di sistema '${SAMBA_GROUP}'"
getent group "${SAMBA_GROUP}" >/dev/null || groupadd "${SAMBA_GROUP}"

echo "==> [3/7] Controllo supporto ACL POSIX su ZFS (se applicabile)"
if command -v zfs >/dev/null 2>&1; then
  DATASET=$(zfs list -H -o name,mountpoint 2>/dev/null | awk -v p="${SMB_ROOT_PATH}" '$2==p{print $1}' || true)
  if [ -n "${DATASET:-}" ]; then
    ACLTYPE=$(zfs get -H -o value acltype "${DATASET}" 2>/dev/null || echo "")
    if [ "${ACLTYPE}" != "posixacl" ]; then
      echo "    -> Imposto acltype=posixacl su dataset ${DATASET}"
      zfs set acltype=posixacl "${DATASET}"
      zfs set aclinherit=passthrough "${DATASET}"
    else
      echo "    -> acltype gia' correttamente impostato a posixacl"
    fi
  else
    echo "    -> Nessun dataset ZFS corrispondente a ${SMB_ROOT_PATH} rilevato automaticamente."
    echo "       Verificare manualmente: zfs get acltype <pool>/<dataset>"
  fi
else
  echo "    -> comando 'zfs' non trovato in questo container (normale se il pool e' gestito dall'host)."
  echo "       NOTA: se lo storage e' un bind mount da un host con ZFS, l'host DEVE avere"
  echo "       'acltype=posixacl' impostato sul dataset, altrimenti setfacl fallira'."
fi

echo "==> [4/7] Permessi di base sulla cartella radice condivisa"
chown root:"${SAMBA_GROUP}" "${SMB_ROOT_PATH}"
chmod 2770 "${SMB_ROOT_PATH}"

echo "==> [5/7] Creazione ambiente virtuale Python e installazione dipendenze"
cd "${APP_DIR}"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> [6/7] Inizializzazione database SQLite"
cd "${APP_DIR}"
"${APP_DIR}/venv/bin/python3" init_db.py

echo "==> [7/7] Installazione servizio systemd"
sed "s#__APP_DIR__#${APP_DIR}#g" "${APP_DIR}/smb-user-manager.service" > /etc/systemd/system/smb-user-manager.service
systemctl daemon-reload
systemctl enable smb-user-manager.service
systemctl restart smb-user-manager.service

echo ""
echo "============================================================"
echo " Installazione completata."
echo " Applicazione avviata su: http://<ip-container>:8000"
echo ""
echo " IMPORTANTE:"
echo " - Nel [Dati] di smb.conf e' presente 'force user = smbuser':"
echo "   accedere alla dashboard e usare il pulsante"
echo "   'Correggi configurazione ora' per rimuoverlo e attivare le ACL."
echo " - Se lo storage e' su ZFS, verificare 'acltype=posixacl' sul dataset."
echo " - Se il container LXC e' non privilegiato, verificare che siano"
echo "   abilitate le idmap per l'utente root del container (altrimenti"
echo "   setfacl/chown potrebbero fallire con 'Operation not permitted')."
echo "============================================================"
