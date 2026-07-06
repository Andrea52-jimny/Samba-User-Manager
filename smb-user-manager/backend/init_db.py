#!/usr/bin/env python3
"""
Script di inizializzazione del database SQLite.
Da eseguire UNA SOLA VOLTA alla prima installazione nel container LXC:

    cd backend
    python3 init_db.py

Crea le tabelle e un amministratore di bootstrap. La password di default
puo' essere personalizzata tramite le variabili d'ambiente ADMIN_USERNAME
e ADMIN_PASSWORD; se non viene eseguito, il login iniziale sara':

    utente: admin
    password: ChangeMe123!

L'app RICORDA di cambiare questa password al primo accesso.
"""
import sys

import bcrypt

from config import DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD
from database import init_db, db_cursor


def create_bootstrap_admin():
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM admins")
        count = cur.fetchone()["n"]
    if count > 0:
        print("Un amministratore esiste gia'. Nessuna azione necessaria.")
        return

    password_hash = bcrypt.hashpw(
        DEFAULT_ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            (DEFAULT_ADMIN_USERNAME, password_hash),
        )

    print("=" * 60)
    print("Amministratore di bootstrap creato:")
    print(f"  username: {DEFAULT_ADMIN_USERNAME}")
    print(f"  password: {DEFAULT_ADMIN_PASSWORD}")
    print("CAMBIARE QUESTA PASSWORD AL PRIMO ACCESSO.")
    print("=" * 60)


if __name__ == "__main__":
    init_db()
    create_bootstrap_admin()
    sys.exit(0)
