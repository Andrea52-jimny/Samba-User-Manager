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
import subprocess
from dataclasses import dataclass
from typing import Optional

from config import SAMBA_GROUP, NOLOGIN_SHELL


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


def ensure_samba_group():
    """Crea il gruppo di sistema smbgroup se non esiste (idempotente)."""
    check = subprocess.run(["getent", "group", SAMBA_GROUP], capture_output=True, text=True)
    if check.returncode != 0:
        _run(["groupadd", SAMBA_GROUP])


def linux_user_exists(username: str) -> bool:
    result = subprocess.run(["id", "-u", username], capture_output=True, text=True)
    return result.returncode == 0


def create_linux_user(username: str):
    """Crea un utente di sistema SENZA home directory e SENZA shell di
    login (solo accesso file via Samba), membro del gruppo smbgroup."""
    ensure_samba_group()
    if linux_user_exists(username):
        return
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


def set_samba_password(username: str, password: str, new_user: bool = False):
    """Imposta la password Samba (e, grazie a 'unix password sync = yes',
    anche quella Unix) in modalita' non interattiva (-s, stdin)."""
    args = ["smbpasswd", "-s"]
    if new_user:
        args.append("-a")
    args.append(username)
    stdin_payload = f"{password}\n{password}\n"
    _run(args, input_data=stdin_payload)


def enable_samba_user(username: str):
    _run(["smbpasswd", "-e", username])
    # Riabilita anche l'account di sistema
    subprocess.run(["usermod", "-U", username], capture_output=True, text=True)


def disable_samba_user(username: str):
    """Sospensione: l'utente non potra' PIU' autenticarsi via Samba,
    quindi non potra' vedere ne' accedere ad alcuna cartella condivisa."""
    _run(["smbpasswd", "-d", username])
    # Blocco addizionale lato sistema (difesa in profondita')
    subprocess.run(["usermod", "-L", username], capture_output=True, text=True)


def set_account_expiry(username: str, expiry_date: Optional[str]):
    """expiry_date: stringa 'YYYY-MM-DD' oppure None per durata infinita."""
    if expiry_date:
        _run(["chage", "-E", expiry_date, username])
    else:
        _run(["chage", "-E", "-1", username])


def delete_user_completely(username: str):
    """Rimuove l'utente da Samba, dal sistema Linux e (a cura del chiamante)
    dal database applicativo."""
    subprocess.run(["smbpasswd", "-x", username], capture_output=True, text=True)
    subprocess.run(["deluser", username], capture_output=True, text=True)


def reset_password(username: str, new_password: str):
    set_samba_password(username, new_password, new_user=False)
