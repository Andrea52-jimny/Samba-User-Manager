"""
Gestione della connessione SQLite e definizione dello schema.
SQLite viene usato SOLO per tracciare stato applicativo (sessioni admin,
sospensioni, scadenze, log dei permessi dichiarati). La fonte di verità
per i permessi effettivi resta il file system (POSIX ACL / getfacl).
"""
import sqlite3
from contextlib import contextmanager

from app.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token           TEXT PRIMARY KEY,
    admin_username  TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS managed_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    expiry_date   TEXT,              -- ISO date, NULL = nessuna scadenza
    is_suspended  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    suspended_at  TEXT
);

-- Stato "dichiarato" dei permessi per cartella. La riga con is_explicit=1
-- rappresenta un'assegnazione fatta esplicitamente dall'amministratore su
-- quel percorso; l'assenza di riga significa "eredita dal genitore".
CREATE TABLE IF NOT EXISTS permissions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT NOT NULL,
    path         TEXT NOT NULL,
    can_read     INTEGER NOT NULL DEFAULT 0,
    can_write    INTEGER NOT NULL DEFAULT 0,
    can_delete   INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(username, path)
);

CREATE INDEX IF NOT EXISTS idx_permissions_user ON permissions(username);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
"""


def init_db():
    with db_cursor() as cur:
        cur.executescript(SCHEMA)
