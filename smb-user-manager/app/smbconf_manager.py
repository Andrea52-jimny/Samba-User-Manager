"""
Riscrittura sicura della sezione [Dati] di /etc/samba/smb.conf.

Problema da risolvere (vedi richiesta originale, NOTA ARCHITETTURALE):
la direttiva `force user = smbuser` fa si' che il filesystem veda SEMPRE
smbuser indipendentemente da chi si e' collegato, rendendo inutili le ACL
POSIX per-utente. Questo modulo:

  1. Legge smb.conf riga per riga (NON usiamo configparser perche' la
     sintassi di Samba non e' un vero INI: puo' avere righe duplicate,
     include, macro %U/%m, ecc. Un parser riga-per-riga mirato alla sola
     sezione [Dati] e' piu' sicuro e prevedibile).
  2. Fa un backup timestampato del file originale prima di ogni modifica.
  3. Rimuove la riga "force user = ..." dalla sezione [Dati].
  4. Garantisce la presenza di "valid users = @<SAMBA_GROUP>".
  5. Scrive in modo atomico (file temporaneo + os.replace).
  6. Valida la nuova configurazione con `testparm -s`; se non valida,
     ripristina automaticamente il backup.
  7. Ricarica Samba (smbcontrol smbd reload-config).
"""
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .config import SMB_CONF_PATH, SMB_SHARE_SECTION, SAMBA_GROUP


class SmbConfError(RuntimeError):
    pass


def _section_bounds(lines: list, section: str):
    """Trova (start, end) indici della sezione [section] (end esclusivo)."""
    header = f"[{section}]".lower()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == header:
            start = i
            break
    if start is None:
        raise SmbConfError(f"Sezione [{section}] non trovata in {SMB_CONF_PATH}")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = j
            break
    return start, end


def get_current_status() -> dict:
    """Diagnostica: dice se 'force user' e' ancora presente nella sezione."""
    path = Path(SMB_CONF_PATH)
    if not path.exists():
        return {"exists": False, "force_user_present": False, "valid_users_line": None}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    try:
        start, end = _section_bounds(lines, SMB_SHARE_SECTION)
    except SmbConfError:
        return {"exists": True, "force_user_present": False, "valid_users_line": None, "section_missing": True}

    section_lines = lines[start:end]
    force_user_present = any(re.match(r"^\s*force user\s*=", l, re.IGNORECASE) for l in section_lines)
    valid_users_line = next(
        (l.strip() for l in section_lines if re.match(r"^\s*valid users\s*=", l, re.IGNORECASE)),
        None,
    )
    return {
        "exists": True,
        "force_user_present": force_user_present,
        "valid_users_line": valid_users_line,
    }


def patch_smb_conf() -> dict:
    path = Path(SMB_CONF_PATH)
    if not path.exists():
        raise SmbConfError(f"{SMB_CONF_PATH} non trovato.")

    original_text = path.read_text(encoding="utf-8", errors="replace")
    lines = original_text.splitlines(keepends=True)

    start, end = _section_bounds(lines, SMB_SHARE_SECTION)
    section = lines[start:end]

    # Rileva l'indentazione usata nella sezione (prima riga "chiave = valore"
    # dopo l'intestazione), per mantenere lo stile coerente col resto del file.
    indent = "   "
    for line in section[1:]:
        m = re.match(r"^(\s+)\S", line)
        if m:
            indent = m.group(1)
            break

    new_section = []
    valid_users_written = False
    valid_users_value = f"{indent}valid users = @{SAMBA_GROUP}\n"

    for line in section:
        if re.match(r"^\s*force user\s*=", line, re.IGNORECASE):
            continue  # rimuove del tutto la riga "force user"
        if re.match(r"^\s*valid users\s*=", line, re.IGNORECASE):
            new_section.append(valid_users_value)
            valid_users_written = True
            continue
        new_section.append(line)

    if not valid_users_written:
        # Inserisce subito dopo l'intestazione della sezione
        new_section.insert(1, valid_users_value)

    new_lines = lines[:start] + new_section + lines[end:]
    new_text = "".join(new_lines)

    # --- backup ---
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{SMB_CONF_PATH}.bak-{timestamp}"
    shutil.copy2(SMB_CONF_PATH, backup_path)

    # --- scrittura atomica ---
    dir_ = str(path.parent)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, encoding="utf-8") as tmp:
        tmp.write(new_text)
        tmp_path = tmp.name
    Path(tmp_path).chmod(0o644)
    subprocess_result = subprocess.run(["testparm", "-s", tmp_path], capture_output=True, text=True)

    if subprocess_result.returncode != 0:
        Path(tmp_path).unlink(missing_ok=True)
        raise SmbConfError(
            f"La nuova configurazione non e' valida secondo testparm, modifica annullata: "
            f"{subprocess_result.stderr.strip()}"
        )

    import os
    os.replace(tmp_path, SMB_CONF_PATH)

    # --- validazione finale sul file reale + reload ---
    final_check = subprocess.run(["testparm", "-s"], capture_output=True, text=True)
    if final_check.returncode != 0:
        shutil.copy2(backup_path, SMB_CONF_PATH)
        raise SmbConfError("Validazione finale fallita, ripristinato il backup.")

    reload_result = subprocess.run(
        ["smbcontrol", "smbd", "reload-config"], capture_output=True, text=True
    )
    if reload_result.returncode != 0:
        # fallback a systemd reload
        subprocess.run(["systemctl", "reload", "smbd"], capture_output=True, text=True)

    return {
        "backup_path": backup_path,
        "force_user_removed": True,
        "valid_users": valid_users_value.strip(),
    }
