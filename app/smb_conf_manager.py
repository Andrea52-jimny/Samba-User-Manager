"""
Riscrittura sicura della sezione [Dati] di /etc/samba/smb.conf.

Problema risolto (vedi nota architetturale del brief):
`force user = smbuser` fa sì che il file system veda SEMPRE smbuser,
indipendentemente da chi si è autenticato, rendendo inutili i permessi
POSIX ACL per-utente. Questo modulo:
  1. fa un backup con timestamp di smb.conf,
  2. rimuove ogni riga 'force user' dentro la sezione [Dati],
  3. impone 'valid users = @smbgroup' (crea o sostituisce la riga),
  4. valida la nuova configurazione con `testparm -s`,
  5. se la validazione fallisce, ripristina automaticamente il backup,
  6. se ok, ricarica Samba (`smbcontrol all reload-config`).

Viene sempre scritto un file temporaneo e poi rinominato (os.replace) per
evitare di lasciare smb.conf in uno stato a metà se il processo viene
interrotto.
"""
import os
import shutil
import subprocess
import time

from app.config import SMB_CONF_PATH, SMB_SHARE_SECTION, SAMBA_GROUP
from app.shell import SystemCommandError


def _read_conf() -> list[str]:
    with open(SMB_CONF_PATH, "r", encoding="utf-8") as f:
        return f.readlines()


def _backup_conf() -> str:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = f"{SMB_CONF_PATH}.bak-{timestamp}"
    shutil.copy2(SMB_CONF_PATH, backup_path)
    return backup_path


def _find_section_bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    """Ritorna (start, end) indici [start, end) della sezione [section],
    dove start è la riga dell'intestazione e end è la prima riga della
    sezione successiva (o len(lines) se è l'ultima)."""
    header = f"[{section}]".lower()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == header:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = j
            break
    return start, end


def fix_dati_section() -> str:
    """Esegue la correzione descritta sopra. Ritorna il percorso del backup
    creato. Solleva SystemCommandError se qualcosa va storto (con rollback
    automatico già eseguito)."""
    if not os.path.isfile(SMB_CONF_PATH):
        raise SystemCommandError(f"File non trovato: {SMB_CONF_PATH}")

    lines = _read_conf()
    bounds = _find_section_bounds(lines, SMB_SHARE_SECTION)
    if bounds is None:
        raise SystemCommandError(f"Sezione [{SMB_SHARE_SECTION}] non trovata in {SMB_CONF_PATH}")

    start, end = bounds
    backup_path = _backup_conf()

    new_section: list[str] = [lines[start]]  # riga [Dati]
    valid_users_written = False
    for line in lines[start + 1:end]:
        key = line.strip().split("=", 1)[0].strip().lower()
        if key == "force user":
            continue  # rimossa: causava l'appiattimento di tutti gli utenti su smbuser
        if key == "valid users":
            new_section.append(f"        valid users = @{SAMBA_GROUP}\n")
            valid_users_written = True
            continue
        new_section.append(line)

    if not valid_users_written:
        new_section.append(f"        valid users = @{SAMBA_GROUP}\n")

    new_lines = lines[:start] + new_section + lines[end:]

    tmp_path = f"{SMB_CONF_PATH}.tmp-{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    os.replace(tmp_path, SMB_CONF_PATH)

    # Validazione sintattica: se fallisce, ripristina immediatamente il backup
    check = subprocess.run(["testparm", "-s", SMB_CONF_PATH], capture_output=True, text=True)
    if check.returncode != 0:
        shutil.copy2(backup_path, SMB_CONF_PATH)
        raise SystemCommandError(
            f"smb.conf non valido dopo la modifica, ripristinato il backup. Dettagli: {check.stderr.strip()}"
        )

    # Ricarica la configurazione di Samba senza interrompere le sessioni attive
    reload_result = subprocess.run(["smbcontrol", "all", "reload-config"], capture_output=True, text=True)
    if reload_result.returncode != 0:
        # Non fatale: la config su disco è comunque valida e verrà letta al
        # prossimo restart del servizio smbd.
        pass

    return backup_path


def is_force_user_active() -> bool:
    """Controllo diagnostico: True se 'force user' è ancora presente e attivo
    nella sezione [Dati] (utile per mostrare un avviso nella dashboard)."""
    if not os.path.isfile(SMB_CONF_PATH):
        return False
    lines = _read_conf()
    bounds = _find_section_bounds(lines, SMB_SHARE_SECTION)
    if bounds is None:
        return False
    start, end = bounds
    for line in lines[start + 1:end]:
        stripped = line.strip()
        if stripped.startswith(";") or stripped.startswith("#"):
            continue
        if stripped.split("=", 1)[0].strip().lower() == "force user":
            return True
    return False
