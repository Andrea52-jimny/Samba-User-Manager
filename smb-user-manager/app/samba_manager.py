"""
Gestione utenti Linux/Samba a basso livello.

IMPORTANTE (vedi NOTA ARCHITETTURALE nella richiesta originale):
La configurazione attuale di smb.conf usa:
    unix password sync = Yes
    passwd program = /usr/bin/passwd %u
    passwd chat = ...
Questo significa che quando la password Samba viene impostata con
`smbpasswd`, il sistema sincronizza AUTOMATICAMENTE anche la password Unix
tramite il programma /usr/bin/passwd. Per questo motivo non serve chiamare
`chpasswd` separatamente: basta creare l'utente Linux con account bloccato
(-N -M, nessuna password utilizzabile via login diretto, shell nologin) e poi
impostare la password tramite `smbpasswd`, che si occupa di tutto.

Tutti i comandi vengono eseguiti con subprocess usando liste di argomenti
(NON shell=True), quindi non sono soggetti a shell injection: ogni parametro
e' passato come argomento separato al processo figlio.
"""
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import SAMBA_GROUP, NOLOGIN_SHELL, PERSIST_USERS_DIR

_USER_DB_FILES = ("passwd", "shadow", "group", "gshadow")


class SambaCommandError(RuntimeError):
    def __init__(self, cmd, result):
        self.cmd = cmd
        self.returncode = result.returncode
        self.stdout = result.stdout
        self.stderr = result.stderr
        super().__init__(
            f"Comando fallito ({' '.join(cmd)}): [{result.returncode}] {result.stderr.strip()}"
        )


def _run(cmd: list, input_data: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise SambaCommandError(cmd, result)
    return result


def _sync_user_db_to_persist():
    """In ambiente Docker (PERSIST_USERS_DIR valorizzata dall'entrypoint),
    copia /etc/passwd,shadow,group,gshadow verso il volume persistente dopo
    ogni operazione che li modifica. Necessario perche' questi file NON sono
    bind-montati direttamente (rname() di useradd/groupadd/passwd non puo'
    sostituire un mountpoint): l'entrypoint li copia IN /etc all'avvio, e qui
    li ricopiamo FUORI dopo ogni modifica, cosi' la prossima ricreazione del
    container riparte dallo stato aggiornato. Fuori da Docker (variabile non
    impostata) questa funzione non fa nulla.
    """
    if not PERSIST_USERS_DIR:
        return
    try:
        Path(PERSIST_USERS_DIR).mkdir(parents=True, exist_ok=True)
        for name in _USER_DB_FILES:
            shutil.copy2(f"/etc/{name}", str(Path(PERSIST_USERS_DIR) / name))
    except OSError as exc:
        print(f"[samba_manager] ATTENZIONE: sync stato utenti verso {PERSIST_USERS_DIR} fallito: {exc}")


def ensure_samba_group():
    """Crea il gruppo di sistema smbgroup se non esiste (idempotente)."""
    check = subprocess.run(["getent", "group", SAMBA_GROUP], capture_output=True, text=True)
    if check.returncode != 0:
        try:
            _run(["groupadd", SAMBA_GROUP])
        finally:
            _sync_user_db_to_persist()


def linux_user_exists(username: str) -> bool:
    result = subprocess.run(["id", "-u", username], capture_output=True, text=True)
    return result.returncode == 0


def create_linux_user(username: str):
    """Crea un utente di sistema SENZA home directory e SENZA shell di
    login (solo accesso file via Samba), membro del gruppo smbgroup."""
    ensure_samba_group()
    if linux_user_exists(username):
        return
    try:
        _run([
            "useradd",
            "-M",                 # nessuna home directory
            "-N",                 # nessun gruppo privato personale
            "-g", SAMBA_GROUP,
            "-s", NOLOGIN_SHELL,
            username,
        ])
        # L'account Linux resta bloccato per il login diretto (password '!'):
        _run(["usermod", "-L", username])
    finally:
        _sync_user_db_to_persist()


def set_samba_password(username: str, password: str, new_user: bool = False):
    """Imposta la password Samba (e, grazie a 'unix password sync = yes',
    anche quella Unix) in modalita' non interattiva (-s, stdin)."""
    args = ["smbpasswd", "-s"]
    if new_user:
        args.append("-a")
    args.append(username)
    stdin_payload = f"{password}\n{password}\n"
    try:
        _run(args, input_data=stdin_payload)
    finally:
        _sync_user_db_to_persist()


def disconnect_user_sessions(username: str):
    """Termina IMMEDIATAMENTE ogni sessione SMB gia' stabilita per l'utente.

    Disabilitare la password (smbpasswd -d) o eliminare l'utente blocca solo
    i NUOVI login: un client Windows/macOS gia' connesso mantiene la propria
    sessione aperta (con relativo smbd figlio dedicato) finche' non si
    disconnette da solo, e continua a leggere/scrivere/cancellare file anche
    dopo la sospensione/eliminazione. Per questo va chiusa a forza la
    connessione esistente, individuando il PID del processo smbd figlio
    dedicato a quell'utente (via 'smbstatus -b') e terminandolo.
    """
    try:
        result = subprocess.run(
            ["smbstatus", "-b"], capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return
    for line in result.stdout.splitlines():
        parts = line.split()
        # Formato riga: PID  Username  Group  Machine  ...
        if len(parts) >= 2 and parts[0].isdigit() and parts[1] == username:
            try:
                os.kill(int(parts[0]), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass


def enable_samba_user(username: str):
    try:
        _run(["smbpasswd", "-e", username])
        # Riabilita anche l'account di sistema
        subprocess.run(["usermod", "-U", username], capture_output=True, text=True)
    finally:
        _sync_user_db_to_persist()


def disable_samba_user(username: str):
    """Sospensione: l'utente non potra' PIU' autenticarsi via Samba,
    quindi non potra' vedere ne' accedere ad alcuna cartella condivisa."""
    try:
        _run(["smbpasswd", "-d", username])
        # Blocco addizionale lato sistema (difesa in profondita')
        subprocess.run(["usermod", "-L", username], capture_output=True, text=True)
    finally:
        _sync_user_db_to_persist()


def set_account_expiry(username: str, expiry_value: Optional[str]):
    """expiry_value: stringa 'YYYY-MM-DDTHH:MM' (data e ora) oppure None per
    durata infinita.

    NOTA: /etc/shadow (e quindi 'chage -E') ha granularita' di un GIORNO
    intero, non supporta un orario preciso: e' un limite del formato stesso,
    non di questa applicazione. Per questo 'chage' viene comunque impostato
    come difesa aggiuntiva a livello di sistema operativo (usando solo la
    parte di DATA, arrotondata al giorno), ma il taglio preciso all'ORARIO
    esatto e' applicato dal thread di sospensione automatica dell'app
    (vedi main.py: _check_expired_accounts), che confronta l'orario corrente
    con l'intero valore data+ora salvato nel database.
    """
    try:
        if expiry_value:
            date_part = expiry_value.split("T")[0]
            _run(["chage", "-E", date_part, username])
        else:
            _run(["chage", "-E", "-1", username])
    finally:
        _sync_user_db_to_persist()


def delete_user_completely(username: str):
    """Rimuove l'utente da Samba, dal sistema Linux e (a cura del chiamante)
    dal database applicativo."""
    try:
        subprocess.run(["smbpasswd", "-x", username], capture_output=True, text=True)
        subprocess.run(["deluser", username], capture_output=True, text=True)
    finally:
        _sync_user_db_to_persist()


def reset_password(username: str, new_password: str):
    set_samba_password(username, new_password, new_user=False)
