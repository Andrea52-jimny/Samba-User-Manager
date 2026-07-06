"""
Livello di accesso al database SQLite.
Tutte le query utilizzano SEMPRE placeholder "?" (prepared statements) per
essere immuni da SQL Injection: nessuna stringa esterna viene mai
concatenata direttamente in una query SQL.
"""
import sqlite3
import threading
from contextlib import contextmanager

from .config import DB_PATH

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """Ritorna una connessione SQLite per-thread (SQLite non e' thread-safe
    se la stessa connessione viene condivisa tra thread diversi)."""
    if not hasattr(_local, "conn"):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return _local.conn


@contextmanager
def db_cursor(commit: bool = False):
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    admin_username TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expiry_date TEXT,            -- NULL = durata infinita, altrimenti YYYY-MM-DD
    suspended INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    path TEXT NOT NULL,          -- percorso relativo alla ROOT_PATH ("" = root)
    can_read INTEGER NOT NULL DEFAULT 0,
    can_write INTEGER NOT NULL DEFAULT 0,
    can_delete INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(username, path)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    admin_username TEXT,
    action TEXT NOT NULL,
    target TEXT,
    details TEXT
);
"""


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()


def log_action(admin_username: str, action: str, target: str = "", details: str = ""):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO audit_log (admin_username, action, target, details) VALUES (?, ?, ?, ?)",
            (admin_username, action, target, details),
        )
