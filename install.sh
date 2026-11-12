#!/usr/bin/env bash
# Bare-metal / LXC installer for Debian and Ubuntu based systems.
# Run as root INSIDE the container or VM that will serve Samba.
#
# Prefer the Docker Compose deployment unless you have a reason not to:
# see the README. This path is kept for people who already run Samba
# natively and do not want a container runtime.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAMBA_GROUP="${SAMBA_GROUP:-smbgroup}"
SMB_ROOT_PATH="${SMB_ROOT_PATH:-/mnt/dati}"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: this script must be run as root." >&2
  exit 1
fi

echo "==> [1/7] Installing system packages"
apt-get update -y
apt-get install -y samba samba-common-bin acl python3 python3-venv python3-pip

echo "==> [2/7] Creating system group '${SAMBA_GROUP}'"
getent group "${SAMBA_GROUP}" >/dev/null || groupadd "${SAMBA_GROUP}"

echo "==> [3/7] Checking POSIX ACL support on ZFS (if applicable)"
if command -v zfs >/dev/null 2>&1; then
  DATASET=$(zfs list -H -o name,mountpoint 2>/dev/null | awk -v p="${SMB_ROOT_PATH}" '$2==p{print $1}' || true)
  if [ -n "${DATASET:-}" ]; then
    ACLTYPE=$(zfs get -H -o value acltype "${DATASET}" 2>/dev/null || echo "")
    if [ "${ACLTYPE}" != "posixacl" ]; then
      echo "    -> setting acltype=posixacl on dataset ${DATASET}"
      zfs set acltype=posixacl "${DATASET}"
      zfs set aclinherit=passthrough "${DATASET}"
    else
      echo "    -> acltype is already set to posixacl"
    fi
  else
    echo "    -> no ZFS dataset found for ${SMB_ROOT_PATH}."
    echo "       Check manually: zfs get acltype <pool>/<dataset>"
  fi
else
  echo "    -> 'zfs' command not found here (normal when the pool is managed by the host)."
  echo "       NOTE: if the storage is a bind mount from a ZFS host, the HOST must have"
  echo "       'acltype=posixacl' set on the dataset, otherwise setfacl will fail."
fi

echo "==> [4/7] Base permissions on the share root"
chown root:"${SAMBA_GROUP}" "${SMB_ROOT_PATH}"
chmod 2770 "${SMB_ROOT_PATH}"

echo "==> [5/7] Creating the Python virtual environment"
cd "${APP_DIR}"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> [6/7] Initialising the SQLite database"
"${APP_DIR}/venv/bin/python3" init_db.py

echo "==> [7/7] Installing the systemd service"
sed "s#__APP_DIR__#${APP_DIR}#g" "${APP_DIR}/smb-user-manager.service" > /etc/systemd/system/smb-user-manager.service
systemctl daemon-reload
systemctl enable smb-user-manager.service
systemctl restart smb-user-manager.service

echo ""
echo "============================================================"
echo " Installation complete."
echo " Web UI: http://<host-ip>:8000"
echo ""
echo " IMPORTANT:"
echo " - Log in with the bootstrap administrator and CHANGE THE PASSWORD"
echo "   immediately (default: admin / ChangeMe123!)."
echo " - If your smb.conf has 'force user' in the managed share, open the"
echo "   dashboard and use 'Fix configuration now': per-user ACLs have no"
echo "   effect while that option is active."
echo " - On ZFS, make sure 'acltype=posixacl' is set on the dataset."
echo " - In an unprivileged LXC container, check that idmaps allow root in"
echo "   the container to run setfacl/chown, otherwise they fail with"
echo "   'Operation not permitted'."
echo "============================================================"
