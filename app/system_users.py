"""
Wrapper sicuri attorno ai comandi di sistema per gestire utenti Linux e Samba.

Regole di sicurezza applicate ovunque in questo modulo:
- subprocess.run è SEMPRE invocato con una lista di argomenti (mai shell=True
  con stringhe concatenate), quindi non esiste superficie di command injection.
- Ogni username viene validato con USERNAME_REGEX prima di essere usato in
  qualunque comando.
- Le password vengono passate ai comandi (smbpasswd) via STDIN, mai come
  argomento in chiaro (che finirebbe nella process list / negli log).
"""
import re
import subprocess

from app.config import USERNAME_REGEX, SAMBA_GROUP, SAMBA_USER_SHELL
from app.shell import run_command as _run, SystemCommandError

__all__ = [
    "SystemCommandError", "validate_username", "linux_user_exists",
    "ensure_samba_group_exists", "create_system_and_samba_user",
    "reset_samba_password", "suspend_samba_user", "reactivate_samba_user",
    "delete_system_and_samba_user",
]


def validate_username(username: str) -> None:
    if not re.match(USERNAME_REGEX, username):
        raise ValueError(
            "Username non valido: usare solo minuscole, numeri, '_' o '-', "
            "massimo 32 caratteri, non iniziare con un numero."
        )


def linux_user_exists(username: str) -> bool:
    result = subprocess.run(["id", "-u", username], capture_output=True, text=True)
    return result.returncode == 0


def ensure_samba_group_exists() -> None:
    result = subprocess.run(["getent", "group", SAMBA_GROUP], capture_output=True, text=True)
    if result.returncode != 0:
        _run(["groupadd", SAMBA_GROUP])


def create_system_and_samba_user(username: str, password: str) -> None:
    """Crea l'utente Linux (senza home, shell non interattiva), lo aggiunge al
    gruppo Samba e crea l'account Samba con la password fornita, attivo."""
    validate_username(username)
    if linux_user_exists(username):
        raise SystemCommandError(f"L'utente Linux '{username}' esiste già.")

    ensure_samba_group_exists()

    # -M: non creare la home directory (non serve, l'utente accede solo via Samba)
    # -N: non creare un gruppo personale con lo stesso nome
    # -g: gruppo primario
    # -s: shell di login disabilitata
    _run([
        "useradd", "-M", "-N",
        "-g", SAMBA_GROUP,
        "-s", SAMBA_USER_SHELL,
        username,
    ])

    # Blocca la password di sistema (login diretto non consentito, solo Samba)
    _run(["passwd", "-l", username])

    # Crea l'utente in Samba. smbpasswd -s legge "password\npassword\n" da stdin.
    _run(["smbpasswd", "-a", "-s", username], input_text=f"{password}\n{password}\n")
    _run(["smbpasswd", "-e", username])  # assicura che sia abilitato


def reset_samba_password(username: str, new_password: str) -> None:
    validate_username(username)
    if not linux_user_exists(username):
        raise SystemCommandError(f"L'utente '{username}' non esiste sul sistema.")
    _run(["smbpasswd", "-s", username], input_text=f"{new_password}\n{new_password}\n")


def suspend_samba_user(username: str) -> None:
    """Disabilita l'account Samba (nessun accesso alla condivisione) e blocca
    anche l'account Linux per sicurezza extra."""
    validate_username(username)
    _run(["smbpasswd", "-d", username])
    _run(["usermod", "-L", username])


def reactivate_samba_user(username: str) -> None:
    validate_username(username)
    _run(["smbpasswd", "-e", username])
    _run(["usermod", "-U", username])


def delete_system_and_samba_user(username: str) -> None:
    validate_username(username)
    # Rimuove l'utente dal database Samba (ignora errori se già assente)
    subprocess.run(["smbpasswd", "-x", username], capture_output=True, text=True)
    # Rimuove l'utente Linux (-r rimuove anche una eventuale home/mail spool)
    if linux_user_exists(username):
        _run(["userdel", "-r", username])
