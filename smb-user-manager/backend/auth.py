"""
Autenticazione amministratore.
- Hashing password: Bcrypt (salt automatico, cost factor di default 12).
- Verifica credenziali: query parametrizzata (prepared statement).
- Sessioni: token opachi casuali (secrets.token_urlsafe) salvati in SQLite,
  esposti al browser tramite cookie HttpOnly.
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Request

from config import SESSION_TTL_HOURS
from database import db_cursor


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def authenticate_admin(username: str, password: str) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT password_hash FROM admins WHERE username = ?", (username,))
        row = cur.fetchone()
    if row is None:
        # Esegue comunque un hash "dummy" per non rivelare via timing se
        # l'utente esiste o meno.
        bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
        return False
    return verify_password(password, row["password_hash"])


def create_session(admin_username: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO sessions (token, admin_username, expires_at) VALUES (?, ?, ?)",
            (token, admin_username, expires_at),
        )
    return token


def destroy_session(token: str):
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_session_admin(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    with db_cursor() as cur:
        cur.execute(
            "SELECT admin_username, expires_at FROM sessions WHERE token = ?", (token,)
        )
        row = cur.fetchone()
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
        destroy_session(token)
        return None
    return row["admin_username"]


def get_current_admin(request: Request) -> Optional[str]:
    from config import SESSION_COOKIE_NAME
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return get_session_admin(token)


def change_admin_password(username: str, new_password: str):
    new_hash = hash_password(new_password)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE admins SET password_hash = ? WHERE username = ?",
            (new_hash, username),
        )
