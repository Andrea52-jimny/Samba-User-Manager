"""
Configurazione centrale della Web App.
Modifica qui i valori se il tuo ambiente differisce da quello di riferimento.
"""
import os

# --- Percorsi di sistema ---
DB_PATH = "/opt/samba-manager/data/samba_manager.db"

# Radice reale della condivisione sul file system (bind mount ZFS -> LXC)
SHARE_ROOT = "/mnt/dati"

# File di configurazione Samba
SMB_CONF_PATH = "/etc/samba/smb.conf"
SMB_SHARE_SECTION = "Dati"          # nome della sezione [Dati] in smb.conf

# Gruppo Linux/Samba usato in "valid users = @smbgroup"
SAMBA_GROUP = "smbgroup"

# Shell assegnata agli utenti Samba creati (nessun accesso login interattivo)
SAMBA_USER_SHELL = "/usr/sbin/nologin"

# --- Sicurezza sessioni web ---
SESSION_COOKIE_NAME = "sm_session"
SESSION_DURATION_HOURS = 12
# Imposta a True SOLO se l'app è servita via HTTPS (es. dietro reverse proxy
# con TLS). Se accedi via http://ip-lxc:8000 sulla LAN senza TLS, lascialo a
# False: altrimenti il browser scarterà il cookie di sessione e il login
# sembrerà non funzionare mai.
SESSION_COOKIE_SECURE = os.environ.get("SM_COOKIE_SECURE", "false").lower() == "true"

# --- Scheduler ---
EXPIRY_CHECK_INTERVAL_MINUTES = 15

# --- Validazione ---
# Username Linux/Samba validi: minuscole, numeri, underscore, trattino; 1-32 caratteri
USERNAME_REGEX = r"^[a-z_][a-z0-9_-]{0,31}$"

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
