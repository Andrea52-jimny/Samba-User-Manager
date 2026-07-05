"""
Gestione della scansione dinamica dell'albero di cartelle e dei permessi
POSIX ACL (setfacl / getfacl).

IMPORTANTE - Semantica dei permessi su Linux:
Le 3 checkbox richieste (Lettura / Modifica / Eliminazione) sono mappate
direttamente ai 3 bit ACL standard r / w / x, così come indicato nelle
specifiche:
    Lettura     -> r
    Modifica    -> w
    Eliminazione -> x
Nota tecnica per l'amministratore: su Linux l'eliminazione di un file è in
realtà governata dal permesso di SCRITTURA sulla cartella che lo contiene
(non da un bit sul singolo file), mentre 'x' su una directory serve ad
attraversarla. Questa mappatura 1:1 richiesta è quindi una semplificazione
operativa: per una esperienza pienamente coerente si consiglia di abilitare
insieme Modifica + Eliminazione. Il comportamento reale del kernel prevale
sempre sulla semplificazione della UI.

Ereditarietà: quando un permesso viene assegnato su una cartella, viene
applicato ricorsivamente (setfacl -R) a tutto il sotto-albero ESISTENTE, e
viene impostato anche come ACL di default (setfacl -d) in modo che ogni
nuovo file/sottocartella creato in futuro erediti automaticamente lo stesso
permesso. Applicare successivamente un permesso diverso su una sottocartella
specifica sovrascrive semplicemente l'ACL su quel ramo (e su tutto ciò che
contiene), realizzando l'override esplicito richiesto.
"""
import os
import re
import subprocess
from dataclasses import dataclass, field

from app.config import SHARE_ROOT
from app.system_users import validate_username
from app.shell import run_command as _run, SystemCommandError


class PathSecurityError(Exception):
    """Sollevata se un percorso richiesto tenta di uscire da SHARE_ROOT."""


@dataclass
class DirNode:
    name: str
    path: str  # percorso assoluto reale sul filesystem
    rel_path: str  # percorso relativo a SHARE_ROOT (usato dal frontend)
    has_children: bool


def resolve_safe_path(rel_path: str) -> str:
    """Trasforma un percorso relativo (fornito dal frontend) in un percorso
    assoluto reale, garantendo che rimanga dentro SHARE_ROOT (anti path-traversal)."""
    rel_path = (rel_path or "").strip().lstrip("/")
    candidate = os.path.realpath(os.path.join(SHARE_ROOT, rel_path))
    share_real = os.path.realpath(SHARE_ROOT)
    if candidate != share_real and not candidate.startswith(share_real + os.sep):
        raise PathSecurityError("Percorso non consentito (fuori dalla condivisione).")
    if not os.path.isdir(candidate):
        raise FileNotFoundError(f"La cartella '{rel_path}' non esiste.")
    return candidate


def to_rel_path(abs_path: str) -> str:
    share_real = os.path.realpath(SHARE_ROOT)
    rel = os.path.relpath(abs_path, share_real)
    return "" if rel == "." else rel.replace(os.sep, "/")


def list_children(rel_path: str = "") -> list[DirNode]:
    """Scansione dinamica (non ricorsiva) delle sole sottocartelle dirette,
    letta live dal disco - nessun dato statico salvato in precedenza."""
    abs_path = resolve_safe_path(rel_path)
    nodes: list[DirNode] = []
    try:
        with os.scandir(abs_path) as it:
            entries = sorted(
                (e for e in it if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")),
                key=lambda e: e.name.lower(),
            )
    except PermissionError as exc:
        raise SystemCommandError(f"Permesso negato leggendo '{abs_path}'") from exc

    for entry in entries:
        child_abs = entry.path
        has_children = False
        try:
            with os.scandir(child_abs) as sub_it:
                has_children = any(
                    s.is_dir(follow_symlinks=False) and not s.name.startswith(".")
                    for s in sub_it
                )
        except PermissionError:
            has_children = False
        nodes.append(
            DirNode(
                name=entry.name,
                path=child_abs,
                rel_path=to_rel_path(child_abs),
                has_children=has_children,
            )
        )
    return nodes


# --- ACL: lettura stato corrente ---

_ACL_USER_LINE = re.compile(r"^user:([^:]+):([rwx-]{3})\s*$", re.MULTILINE)


def get_user_permission(username: str, rel_path: str) -> dict:
    """Legge live (getfacl) il permesso corrente dell'utente su quella
    specifica cartella. Nessuna cache: riflette sempre lo stato reale."""
    validate_username(username)
    abs_path = resolve_safe_path(rel_path)
    result = subprocess.run(
        ["getfacl", "-p", "--absolute-names", abs_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {"read": False, "write": False, "delete": False}

    for match in _ACL_USER_LINE.finditer(result.stdout):
        acl_user, bits = match.group(1), match.group(2)
        if acl_user == username:
            return {
                "read": bits[0] == "r",
                "write": bits[1] == "w",
                "delete": bits[2] == "x",
            }
    return {"read": False, "write": False, "delete": False}


def _perm_string(read: bool, write: bool, delete: bool) -> str:
    return f"{'r' if read else '-'}{'w' if write else '-'}{'x' if delete else '-'}"


def apply_permission(username: str, rel_path: str, read: bool, write: bool,
                      delete: bool, recursive: bool = True) -> None:
    """Applica il permesso via setfacl: ACL effettiva + ACL di default (per
    l'ereditarietà sui contenuti creati in futuro)."""
    validate_username(username)
    abs_path = resolve_safe_path(rel_path)
    perm = _perm_string(read, write, delete)

    if not (read or write or delete):
        # Nessun bit selezionato: equivale a rimuovere il permesso
        remove_permission(username, rel_path, recursive=recursive)
        return

    base_cmd = ["setfacl"]
    if recursive:
        base_cmd.append("-R")

    # ACL effettiva sui file/cartelle esistenti
    _run(base_cmd + ["-m", f"u:{username}:{perm}", abs_path])
    # ACL di default: garantisce che nuovi file/sottocartelle creati in
    # futuro dentro questo ramo ereditino automaticamente lo stesso permesso
    _run(base_cmd + ["-d", "-m", f"u:{username}:{perm}", abs_path])


def remove_permission(username: str, rel_path: str, recursive: bool = True) -> None:
    validate_username(username)
    abs_path = resolve_safe_path(rel_path)
    base_cmd = ["setfacl"]
    if recursive:
        base_cmd.append("-R")
    # Rimuove sia l'ACL effettiva sia quella di default per l'utente
    subprocess.run(base_cmd + ["-x", f"u:{username}", abs_path], capture_output=True, text=True)
    subprocess.run(base_cmd + ["-x", f"d:u:{username}", abs_path], capture_output=True, text=True)


def purge_user_acl_everywhere(username: str) -> None:
    """Usato quando un utente viene eliminato definitivamente: ripulisce ogni
    traccia di ACL sull'intera condivisione."""
    validate_username(username)
    share_real = os.path.realpath(SHARE_ROOT)
    subprocess.run(["setfacl", "-R", "-x", f"u:{username}", share_real], capture_output=True, text=True)
    subprocess.run(["setfacl", "-R", "-x", f"d:u:{username}", share_real], capture_output=True, text=True)
