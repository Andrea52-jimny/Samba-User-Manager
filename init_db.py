#!/usr/bin/env python3
"""
Script di inizializzazione, da eseguire UNA VOLTA dopo l'installazione:

    cd /opt/samba-manager
    source venv/bin/activate
    python init_db.py

Crea lo schema SQLite (se non esiste già) e chiede in modo interattivo
username/password del primo amministratore, salvando solo l'hash Bcrypt
(mai la password in chiaro). Rieseguibile in sicurezza in seguito per
aggiungere un ulteriore amministratore.
"""
import getpass
import sys

from app.database import init_db, db_cursor
from app.security import hash_password


def main():
    init_db()
    print("Schema SQLite pronto.\n")

    username = input("Username del nuovo amministratore: ").strip()
    if not username:
        print("Username vuoto, uscita.")
        sys.exit(1)

    password = getpass.getpass("Password: ")
    password_confirm = getpass.getpass("Conferma password: ")
    if password != password_confirm:
        print("Le due password non coincidono, uscita.")
        sys.exit(1)
    if len(password) < 8:
        print("La password deve avere almeno 8 caratteri.")
        sys.exit(1)

    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM admin_users WHERE username = ?", (username,))
        if cur.fetchone():
            print(f"L'amministratore '{username}' esiste già.")
            sys.exit(1)
        cur.execute(
            "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )

    print(f"\nAmministratore '{username}' creato correttamente.")


if __name__ == "__main__":
    main()
