"""
Scansione DINAMICA del filesystem + gestione permessi granulari POSIX ACL.

Nessuna struttura di cartelle e' mai salvata staticamente: ogni richiesta
dell'albero legge direttamente il disco con os.scandir (approccio "tree"
ricorsivo ma con caricamento pigro/lazy per non dover attraversare interi
sottoalberi enormi ad ogni click, restituendo solo i figli diretti della
cartella richiesta). Se una cartella viene aggiunta o rimossa sul disco,
la prossima richiesta dell'albero la rileva automaticamente: zero
configurazione manuale, zero record statici nel DB.

Mappatura permessi -> bit POSIX (per singola cartella):
  Lettura   (Read)   -> bit 'r' (contenuto/listato leggibile)
  Modifica  (Write)  -> bit 'w' (creazione/modifica file dentro la cartella)
  Eliminazione (Delete) -> bit 'w' sulla cartella stessa

NOTA TECNICA IMPORTANTE: in POSIX, la cancellazione di una voce (file o
sottocartella) e' governata dal permesso di SCRITTURA sulla cartella
CONTENITORE, non da un bit dedicato sul singolo file (a differenza delle
ACL NTFS di Windows). Per questo "Modifica" e "Eliminazione" agiscono
entrambe sul bit 'w' della directory: la separazione in due checkbox viene
comunque mantenuta a livello di interfaccia/DB per chiarezza amministrativa
e per una futura estensione (es. sticky bit / ACL di default differenziate
per file vs. sottocartelle). Il bit 'x' viene sempre aggiunto se e' presente
almeno uno tra read/write/delete, perche' senza 'x' non e' possibile
attraversare la cartella.

Ereditarieta': per ogni assegnazione vengono impostate SIA le ACL "effettive"
ricorsive sull'albero esistente (setfacl -R -m ...) SIA le ACL "di default"
sulla cartella (setfacl -d -m ...), cosi' che i file/le sottocartelle create
in futuro ereditino automaticamente lo stesso permesso. Un permesso
assegnato esplicitamente su una sottocartella specifica sovrascrive quanto
ereditato dal genitore, perche' viene scritto puntualmente su quel path.
"""
import os
import subprocess
from pathlib import Path
from typing import Optional

from .config import ROOT_PATH
from .database import db_cursor


class AclError(RuntimeError):
    pass


def _run(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AclError(f"Comando ACL fallito ({' '.join(cmd)}): {result.stderr.strip()}")
    return result


def sanitize_relpath(relpath: Optional[str]) -> str:
    """Normalizza un percorso relativo impedendo path traversal (../)."""
    relpath = (relpath or "").strip().strip("/").replace("\\", "/")
    parts = [p for p in relpath.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


def abs_path(relpath: str) -> Path:
    safe = sanitize_relpath(relpath)
    root_resolved = Path(ROOT_PATH).resolve()
    candidate = (root_resolved / safe).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise AclError("Percorso non valido (path traversal rilevato).")
    return candidate


def list_children(relpath: str = "") -> list:
    """Ritorna le sottocartelle DIRETTE di relpath, lette in tempo reale dal
    disco. Ogni elemento indica se possiede a sua volta sottocartelle
    (has_children), per disegnare la freccia di espansione nel frontend."""
    target = abs_path(relpath)
    if not target.is_dir():
        raise AclError(f"'{target}' non e' una cartella valida.")

    children = []
    with os.scandir(target) as it:
        entries = sorted(
            (e for e in it if e.is_dir(follow_symlinks=False)),
            key=lambda e: e.name.lower(),
        )
    for entry in entries:
        rel = f"{relpath}/{entry.name}".strip("/") if relpath else entry.name
        try:
            has_children = any(
                sub.is_dir(follow_symlinks=False) for sub in os.scandir(entry.path)
            )
        except PermissionError:
            has_children = False
        children.append({"name": entry.name, "path": rel, "has_children": has_children})
    return children


def build_perm_string(read: bool, write: bool, delete: bool) -> str:
    r = "r" if read else "-"
    w = "w" if (write or delete) else "-"
    x = "x" if (read or write or delete) else "-"
    return f"{r}{w}{x}"


def _upsert_db_permission(username: str, relpath: str, read: bool, write: bool, delete: bool):
    with db_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO permissions (username, path, can_read, can_write, can_delete, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(username, path) DO UPDATE SET
                 can_read=excluded.can_read,
                 can_write=excluded.can_write,
                 can_delete=excluded.can_delete,
                 updated_at=datetime('now')""",
            (username, relpath, int(read), int(write), int(delete)),
        )


def _delete_db_permission(username: str, relpath: str):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM permissions WHERE username = ? AND path = ?",
            (username, relpath),
        )


def apply_permissions(username: str, relpath: str, read: bool, write: bool, delete: bool, recursive: bool = True) -> dict:
    if not any([read, write, delete]):
        return remove_permissions(username, relpath, recursive=recursive)

    target = abs_path(relpath)
    perm = build_perm_string(read, write, delete)
    flags = ["-R"] if recursive else []

    _run(["setfacl", *flags, "-m", f"u:{username}:{perm}", str(target)])
    # ACL di default: valida solo sulle directory, applicata automaticamente
    # solo dove ha senso anche in modalita' ricorsiva.
    _run(["setfacl", *flags, "-d", "-m", f"u:{username}:{perm}", str(target)], check=False)

    _upsert_db_permission(username, relpath, read, write, delete)
    return {"path": relpath, "read": read, "write": write, "delete": delete, "recursive": recursive}


def remove_permissions(username: str, relpath: str, recursive: bool = True) -> dict:
    target = abs_path(relpath)
    flags = ["-R"] if recursive else []
    _run(["setfacl", *flags, "-x", f"u:{username}", str(target)], check=False)
    _run(["setfacl", *flags, "-d", "-x", f"u:{username}", str(target)], check=False)
    _delete_db_permission(username, relpath)
    return {"path": relpath, "read": False, "write": False, "delete": False, "recursive": recursive}


def remove_all_permissions_for_user(username: str):
    """Usato quando l'utente viene eliminato definitivamente."""
    root = Path(ROOT_PATH).resolve()
    subprocess.run(["setfacl", "-R", "-x", f"u:{username}", str(root)], capture_output=True, text=True)
    subprocess.run(["setfacl", "-R", "-d", "-x", f"u:{username}", str(root)], capture_output=True, text=True)
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM permissions WHERE username = ?", (username,))


def get_effective_permission(username: str, relpath: str) -> dict:
    """Risale dal path richiesto verso la root cercando la prima
    assegnazione esplicita in DB (il piu' vicino/specifico vince =
    logica di override sulle sottocartelle)."""
    safe = sanitize_relpath(relpath)
    segments = safe.split("/") if safe else []

    with db_cursor() as cur:
        for i in range(len(segments), -1, -1):
            candidate_path = "/".join(segments[:i])
            cur.execute(
                "SELECT path, can_read, can_write, can_delete FROM permissions WHERE username = ? AND path = ?",
                (username, candidate_path),
            )
            row = cur.fetchone()
            if row:
                return {
                    "read": bool(row["can_read"]),
                    "write": bool(row["can_write"]),
                    "delete": bool(row["can_delete"]),
                    "inherited_from": candidate_path if candidate_path != safe else None,
                }
    return {"read": False, "write": False, "delete": False, "inherited_from": None}


def list_all_permissions_for_user(username: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT path, can_read, can_write, can_delete, updated_at FROM permissions WHERE username = ? ORDER BY path",
            (username,),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def check_zfs_acl_support() -> Optional[str]:
    """Controllo diagnostico best-effort: su ZFS le ACL POSIX funzionano
    solo se il dataset ha 'acltype=posixacl'. Ritorna un messaggio di
    avviso se il controllo fallisce o rileva una configurazione errata,
    altrimenti None."""
    try:
        result = subprocess.run(
            ["zfs", "list", "-H", "-o", "name,mountpoint"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None  # zfs non disponibile/non rilevante, nessun avviso
        root_resolved = str(Path(ROOT_PATH).resolve())
        dataset = None
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 2 and root_resolved.startswith(parts[1]):
                dataset = parts[0]
        if not dataset:
            return None
        acltype = subprocess.run(
            ["zfs", "get", "-H", "-o", "value", "acltype", dataset],
            capture_output=True, text=True, timeout=5,
        )
        if acltype.returncode == 0 and "posixacl" not in acltype.stdout:
            return (
                f"ATTENZIONE: il dataset ZFS '{dataset}' non ha acltype=posixacl. "
                f"Eseguire: zfs set acltype=posixacl {dataset}"
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return None
