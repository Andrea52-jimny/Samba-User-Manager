"""
Configurazione centrale dell'applicazione.
Tutti i valori sono sovrascrivibili tramite variabili d'ambiente, cosi' da
non avere alcun percorso o nome "hard-coded" nella logica applicativa.
Nessun dato di struttura cartelle e' mai salvato staticamente: viene tutto
letto dal filesystem al volo (vedi acl_manager.py).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Percorso radice dello share Samba (bind mount ZFS) ------------------
# Deve corrispondere al parametro "path" della sezione [Dati] in smb.conf
ROOT_PATH = Path(os.environ.get("SMB_ROOT_PATH", "/mnt/dati"))

# --- Samba / Sistema -------------------------------------------------------
SMB_CONF_PATH = os.environ.get("SMB_CONF_PATH", "/etc/samba/smb.conf")
SMB_SHARE_SECTION = os.environ.get("SMB_SHARE_SECTION", "Dati")
SAMBA_GROUP = os.environ.get("SAMBA_GROUP", "smbgroup")
NOLOGIN_SHELL = os.environ.get("NOLOGIN_SHELL", "/usr/sbin/nologin")

# --- Database ---------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = os.environ.get("SMB_DB_PATH", str(DATA_DIR / "smb_manager.db"))

# --- Sessioni admin ----------------------------------------------------------
SESSION_COOKIE_NAME = "smb_admin_session"
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "12"))
# Impostare a True quando l'app gira dietro reverse proxy TLS
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

# --- Admin di bootstrap (usato solo da init_db.py alla prima installazione)
DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")

# --- Controllo scadenze account (thread di background) -----------------------
# La scadenza ora ha granularita' data+ora (vedi selettore datetime in UI):
# un intervallo piu' breve del precedente (300s) riduce il ritardo massimo
# fra l'orario di scadenza impostato e la sospensione automatica effettiva.
EXPIRY_CHECK_INTERVAL_SECONDS = int(os.environ.get("EXPIRY_CHECK_INTERVAL_SECONDS", "60"))

# --- Persistenza utenti/gruppi Linux in ambiente Docker -----------------------
# Se valorizzata (solo nel container Docker, vedi docker-compose.yml), dopo
# ogni operazione che modifica /etc/passwd,shadow,group,gshadow l'app ne fa
# una copia in questa cartella (montata come volume persistente), perche'
# NON si puo' bind-montare direttamente il singolo file /etc/passwd: i tool
# useradd/groupadd/passwd scrivono con schema "tmpfile + rename()", e un
# rename non puo' sostituire un mountpoint (da qui l'errore "failure while
# writing changes to /etc/group" se si prova). Vuota/non impostata = nessun
# effetto (percorso di installazione diretta LXC/systemd, senza Docker).
PERSIST_USERS_DIR = os.environ.get("PERSIST_USERS_DIR", "")
