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

from . import samba_manager
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


def list_all_descendants(relpath: str = "") -> list:
    """Ritorna, ricorsivamente, TUTTI i percorsi relativi delle sottocartelle
    di relpath (a qualunque profondita'). Usato dalla UI per la selezione
    multipla "seleziona tutte le sottocartelle" di una cartella padre, senza
    dover espandere manualmente ogni nodo dell'albero lazy-loaded."""
    target = abs_path(relpath)
    if not target.is_dir():
        raise AclError(f"'{target}' non e' una cartella valida.")

    results = []
    for root, dirs, _files in os.walk(target):
        dirs.sort(key=str.lower)
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for d in dirs:
            full = Path(root) / d
            try:
                rel = full.resolve().relative_to(Path(ROOT_PATH).resolve())
            except ValueError:
                continue
            results.append(str(rel).replace(os.sep, "/"))
    return sorted(results)


def build_perm_string(read: bool, write: bool, delete: bool) -> str:
    r = "r" if read else "-"
    w = "w" if (write or delete) else "-"
    x = "x" if (read or write or delete) else "-"
    return f"{r}{w}{x}"


def _upsert_db_permission(username: str, relpath: str, read: bool, write: bool, delete: bool, recursive: bool = True):
    with db_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO permissions (username, path, can_read, can_write, can_delete, recursive, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(username, path) DO UPDATE SET
                 can_read=excluded.can_read,
                 can_write=excluded.can_write,
                 can_delete=excluded.can_delete,
                 recursive=excluded.recursive,
                 updated_at=datetime('now')""",
            (username, relpath, int(read), int(write), int(delete), int(recursive)),
        )


def _delete_db_permission(username: str, relpath: str):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM permissions WHERE username = ? AND path = ?",
            (username, relpath),
        )


def _lock_down_other(target: Path, flags: list):
    """Toglie l'accesso implicito alle classi Unix 'group' e 'other'
    (chmod go-rwx) e imposta 'group::0'/'other::0' anche nell'ACL di
    default, cosi' che le nuove voci create in futuro dentro la cartella
    ereditino la stessa chiusura.

    Necessario perche' le ACL gestite qui si AGGIUNGONO ai permessi POSIX di
    base, non li sostituiscono:
      - bit 'other' aperti (es. rwxr-xr-x) fanno accedere chiunque, anche
        senza alcuna ACL esplicita, perche' ricade nella classe 'altri';
      - bit 'group' aperti sono ANCORA PIU' insidiosi qui, perche' TUTTI gli
        utenti creati dall'app condividono lo stesso gruppo primario Linux
        (SAMBA_GROUP/smbgroup): se una cartella e' posseduta proprio da quel
        gruppo (capita spesso, es. per coincidenza di GID tra host e
        container) con bit group rwx, OGNI utente gestito dall'app ci accede
        automaticamente in quanto membro del gruppo proprietario, a
        prescindere da qualunque ACL o revoca specifica per quell'utente.
    Il controllo di accesso deve dipendere SOLO dalle assegnazioni esplicite
    (ACL per-utente) gestite dall'app, mai dai bit di gruppo/altri di base.

    NOTA TECNICA: qui si usa 'setfacl -m g::0,o::0' e NON 'chmod g-rwx'.
    Una volta che una cartella ha almeno una voce ACL nominale (es. un
    permesso gia' assegnato a un utente), 'ls -l'/chmod trattano la colonna
    "gruppo" come la MASK dell'ACL (il tetto massimo di permesso per le voci
    nominali), non piu' come il vero proprietario-gruppo: un 'chmod g-rwx'
    in quel caso azzererebbe la mask e spegnerebbe TUTTE le voci nominali
    gia' assegnate ad altri utenti su quella cartella. 'setfacl g::'/'o::'
    invece agiscono sempre sulla voce base proprietario-gruppo/altri, mai
    sulla mask, quindi non toccano le assegnazioni nominali esistenti.

    INOLTRE: riporta il PROPRIETARIO Unix (owner) a root:root. Questo e' il
    bug piu' insidioso di tutti, perche' la classe "owner" ha SEMPRE la
    precedenza assoluta su ACL/gruppo/altri: se una cartella risulta
    posseduta (owner reale, non solo gruppo) da un UID che poi coincide per
    caso con un utente Samba gestito dall'app (es. cartelle copiate/create
    fuori dall'app con owner UID 1000, e il primo utente creato dall'app
    dentro il container ottiene anch'esso UID 1000 da useradd), quell'utente
    ha SEMPRE pieno accesso rwx come proprietario del file, del tutto a
    prescindere da qualunque ACL, revoca o bit di gruppo/altri azzerato.
    root non viene mai assegnato come UID a un utente creato dall'app
    (useradd parte sempre da UID >= 1000), quindi non puo' mai piu'
    coincidere per caso con un utente Samba gestito.
    """
    _run(["setfacl", *flags, "-m", "g::0,o::0", str(target)], check=False)
    _run(["setfacl", *flags, "-d", "-m", "g::0,o::0", str(target)], check=False)
    _run(["chown", *flags, "root:root", str(target)], check=False)


def apply_permissions(username: str, relpath: str, read: bool, write: bool, delete: bool, recursive: bool = True) -> dict:
    target = abs_path(relpath)
    flags = ["-R"] if recursive else []

    _lock_down_other(target, flags)

    if not any([read, write, delete]):
        # IMPORTANTE: "nessun permesso" qui significa "blocca esplicitamente
        # l'accesso su QUESTO percorso", NON "rimuovi l'assegnazione e torna
        # a ereditare dal genitore" (che e' invece cio' che fa
        # remove_permissions/"Revoca tutto"). Se una cartella superiore ha
        # gia' un'assegnazione ricorsiva (es. rwx su tutta la sotto-albero),
        # cancellare semplicemente la riga DB di questa sottocartella
        # farebbe ripiegare la UI e la logica di ereditarieta' sul permesso
        # del genitore, facendolo apparire "tornato" anche se l'accesso
        # reale sul filesystem e' stato tolto correttamente (group/other
        # sono comunque azzerati da _lock_down_other). Si toglie la voce
        # ACL nominale (l'accesso reale e' zero) ma si mantiene una riga
        # esplicita nel DB con read/write/delete a 0, cosi' che sia la UI
        # sia get_effective_permission riportino "0 permessi qui" invece di
        # risalire erroneamente al genitore.
        _run(["setfacl", *flags, "-x", f"u:{username}", str(target)], check=False)
        _run(["setfacl", *flags, "-d", "-x", f"u:{username}", str(target)], check=False)
        _upsert_db_permission(username, relpath, False, False, False, recursive)
        samba_manager.disconnect_user_sessions(username)
        return {"path": relpath, "read": False, "write": False, "delete": False, "recursive": recursive}

    perm = build_perm_string(read, write, delete)
    _run(["setfacl", *flags, "-m", f"u:{username}:{perm}", str(target)])
    # ACL di default: valida solo sulle directory, applicata automaticamente
    # solo dove ha senso anche in modalita' ricorsiva.
    _run(["setfacl", *flags, "-d", "-m", f"u:{username}:{perm}", str(target)], check=False)

    _upsert_db_permission(username, relpath, read, write, delete, recursive)
    # Forza la riconnessione: un client Windows/macOS gia' connesso puo'
    # avere in cache locale (oplock/directory cache di Explorer) il listato
    # o il contenuto di file letti PRIMA della modifica, e continuare a
    # mostrarli come leggibili anche dopo che il permesso e' stato tolto sul
    # server, finche' non si riconnette. Chiudendo la sessione, la prossima
    # richiesta riparte da zero e rispetta subito la nuova ACL.
    samba_manager.disconnect_user_sessions(username)
    return {"path": relpath, "read": read, "write": write, "delete": delete, "recursive": recursive}


def remove_permissions(username: str, relpath: str, recursive: bool = True) -> dict:
    """Usato per "Ripristina ereditarieta'": elimina l'assegnazione ESPLICITA
    su questo percorso specifico (riga DB compresa), cosi' che torni a
    dipendere da quanto assegnato su una cartella antenata (o da nessun
    accesso, se non ce n'e' nessuna). Diverso da 'apply_permissions' con
    tutte le checkbox spente, che invece registra un blocco esplicito a 0
    permessi proprio su questo percorso (vedi commento li')."""
    target = abs_path(relpath)
    flags = ["-R"] if recursive else []
    _run(["setfacl", *flags, "-x", f"u:{username}", str(target)], check=False)
    _run(["setfacl", *flags, "-d", "-x", f"u:{username}", str(target)], check=False)
    _delete_db_permission(username, relpath)
    samba_manager.disconnect_user_sessions(username)
    return {"path": relpath, "read": False, "write": False, "delete": False, "recursive": recursive}


def remove_all_permissions_for_user(username: str):
    """Usato quando l'utente viene eliminato definitivamente."""
    root = Path(ROOT_PATH).resolve()
    subprocess.run(["setfacl", "-R", "-x", f"u:{username}", str(root)], capture_output=True, text=True)
    subprocess.run(["setfacl", "-R", "-d", "-x", f"u:{username}", str(root)], capture_output=True, text=True)
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM permissions WHERE username = ?", (username,))


def revoke_all_filesystem_acls_for_user(username: str):
    """Usato in SOSPENSIONE: toglie subito ogni accesso effettivo sul
    filesystem (setfacl -x su tutto l'albero), ma NON tocca le righe nel DB,
    cosi' che le assegnazioni granulari restino salvate e possano essere
    ripristinate automaticamente al momento della riattivazione (resume)."""
    root = Path(ROOT_PATH).resolve()
    subprocess.run(["setfacl", "-R", "-x", f"u:{username}", str(root)], capture_output=True, text=True)
    subprocess.run(["setfacl", "-R", "-d", "-x", f"u:{username}", str(root)], capture_output=True, text=True)


def restore_all_filesystem_acls_for_user(username: str):
    """Usato in RIATTIVAZIONE (resume): riapplica su disco tutte le
    assegnazioni ancora presenti in DB per l'utente (rimosse dal filesystem,
    ma non dal DB, al momento della sospensione)."""
    for row in list_all_permissions_for_user(username):
        read, write, delete = bool(row["can_read"]), bool(row["can_write"]), bool(row["can_delete"])
        if not any([read, write, delete]):
            continue
        try:
            target = abs_path(row["path"])
        except AclError:
            continue
        perm = build_perm_string(read, write, delete)
        flags = ["-R"] if bool(row["recursive"]) else []
        subprocess.run(["setfacl", *flags, "-m", f"u:{username}:{perm}", str(target)], capture_output=True, text=True)
        subprocess.run(["setfacl", *flags, "-d", "-m", f"u:{username}:{perm}", str(target)], capture_output=True, text=True)


def get_effective_permission(username: str, relpath: str) -> dict:
    """Risale dal path richiesto verso la root cercando la prima
    assegnazione esplicita in DB (il piu' vicino/specifico vince =
    logica di override sulle sottocartelle).

    IMPORTANTE: un'assegnazione fatta con "Applica (solo qui)" (recursive=0)
    NON si propaga davvero sul filesystem alle sottocartelle esistenti (solo
    setfacl -R lo fa). Per questo, quando si risale verso un ANTENATO (non il
    percorso esatto richiesto), un'assegnazione con recursive=0 viene
    ignorata e la ricerca prosegue piu' in alto: mostrarla come "ereditata"
    sarebbe fuorviante, perche' quella sottocartella in realta' non ha
    ricevuto alcun accesso reale da quell'antenato. Sul percorso ESATTO
    richiesto, invece, la propria riga vale sempre, ricorsiva o no."""
    safe = sanitize_relpath(relpath)
    segments = safe.split("/") if safe else []

    with db_cursor() as cur:
        for i in range(len(segments), -1, -1):
            candidate_path = "/".join(segments[:i])
            is_exact = candidate_path == safe
            cur.execute(
                "SELECT path, can_read, can_write, can_delete, recursive FROM permissions WHERE username = ? AND path = ?",
                (username, candidate_path),
            )
            row = cur.fetchone()
            if row and (is_exact or bool(row["recursive"])):
                return {
                    "read": bool(row["can_read"]),
                    "write": bool(row["can_write"]),
                    "delete": bool(row["can_delete"]),
                    "inherited_from": None if is_exact else candidate_path,
                }
    return {"read": False, "write": False, "delete": False, "inherited_from": None}


def list_all_permissions_for_user(username: str) -> list:
    with db_cursor() as cur:
        cur.execute(
            "SELECT path, can_read, can_write, can_delete, recursive, updated_at FROM permissions WHERE username = ? ORDER BY path",
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
