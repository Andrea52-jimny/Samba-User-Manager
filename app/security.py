"""
Autenticazione amministratore: hashing Bcrypt delle password e gestione
sessioni via token opachi salvati in SQLite (niente JWT: token random +
lookup DB, così una sessione puo' essere revocata istantaneamente).
Tutte le query usano Prepared Statements (parametri '?') per prevenire
SQL Injection.
"""
import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import Cookie, HTTPException, status

from app.config import SESSION_COOKIE_NAME, SESSION_DURATION_HOURS
from app.database import db_cursor


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def authenticate_admin(username: str, password: str) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT password_hash FROM admin_users WHERE username = ?", (username,))
        row = cur.fetchone()
    if row is None:
        return False
    return verify_password(password, row["password_hash"])


def create_session(admin_username: str) -> str:
    token = secrets.token_urlsafe(48)
    expires_at = (datetime.utcnow() + timedelta(hours=SESSION_DURATION_HOURS)).isoformat()
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (token, admin_username, expires_at) VALUES (?, ?, ?)",
            (token, admin_username, expires_at),
        )
    return token


def destroy_session(token: str) -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_session_admin(token: str | None) -> str | None:
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


def require_login(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)
) -> str:
    """Dependency FastAPI: protegge le route che richiedono un admin autenticato."""
    admin = get_session_admin(session_token)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessione non valida o scaduta")
    return admin
