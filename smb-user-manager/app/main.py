"""
Entry point FastAPI - Web App gestione utenti e permessi granulari Samba.

Avvio (dalla cartella radice del progetto, che contiene il pacchetto app/):
    uvicorn app.main:app --host 0.0.0.0 --port 8000
(vedi anche smb-user-manager.service per systemd, oppure Dockerfile/docker-compose.yml
per l'esecuzione containerizzata)
"""
import re
import threading
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Depends, HTTPException, Body
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import acl_manager
from . import samba_manager
from . import smbconf_manager
from .auth import (
    authenticate_admin, create_session, destroy_session, get_current_admin,
    change_admin_password, verify_password, hash_password,
)
from .config import SESSION_COOKIE_NAME, SESSION_COOKIE_SECURE, EXPIRY_CHECK_INTERVAL_SECONDS, SAMBA_GROUP
from .database import init_db, db_cursor, log_action

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="Samba User & Permission Manager")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

USERNAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


# --------------------------------------------------------------------------
# Helpers di autenticazione
# --------------------------------------------------------------------------
def require_admin_api(request: Request) -> str:
    admin = get_current_admin(request)
    if not admin:
        raise HTTPException(status_code=401, detail="Sessione non valida, effettuare il login.")
    return admin


def set_session_cookie(response, token: str):
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=SESSION_COOKIE_SECURE,
        max_age=60 * 60 * 12,
    )


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    init_db()
    t = threading.Thread(target=_expiry_watcher_loop, daemon=True)
    t.start()


def _expiry_watcher_loop():
    while True:
        try:
            _check_expired_accounts()
        except Exception as exc:  # non deve mai far crashare il thread
            print(f"[expiry-watcher] errore: {exc}")
        time.sleep(EXPIRY_CHECK_INTERVAL_SECONDS)


def _check_expired_accounts():
    today = date.today().isoformat()
    with db_cursor() as cur:
        cur.execute(
            "SELECT username FROM users WHERE expiry_date IS NOT NULL AND expiry_date <= ? AND suspended = 0",
            (today,),
        )
        expired = [r["username"] for r in cur.fetchall()]
    for username in expired:
        try:
            samba_manager.disable_samba_user(username)
            with db_cursor(commit=True) as cur:
                cur.execute("UPDATE users SET suspended = 1 WHERE username = ?", (username,))
            log_action("system", "auto-suspend-expired", username, "Account scaduto sospeso automaticamente")
        except Exception as exc:
            print(f"[expiry-watcher] impossibile sospendere {username}: {exc}")


# --------------------------------------------------------------------------
# Pagine HTML
# --------------------------------------------------------------------------
@app.get("/")
def root(request: Request):
    if get_current_admin(request):
        return RedirectResponse("/dashboard")
    return RedirectResponse("/login")


@app.get("/login")
def login_page(request: Request):
    if get_current_admin(request):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/dashboard")
def dashboard_page(request: Request):
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login")
    return templates.TemplateResponse("dashboard.html", {"request": request, "admin": admin})


@app.get("/permissions/{username}")
def permissions_page(request: Request, username: str):
    admin = get_current_admin(request)
    if not admin:
        return RedirectResponse("/login")
    return templates.TemplateResponse(
        "permissions.html", {"request": request, "admin": admin, "username": username}
    )


# --------------------------------------------------------------------------
# API - Autenticazione
# --------------------------------------------------------------------------
@app.post("/api/login")
def api_login(payload: dict = Body(...)):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        raise HTTPException(400, "Credenziali mancanti.")
    if not authenticate_admin(username, password):
        raise HTTPException(401, "Username o password errati.")
    token = create_session(username)
    resp = JSONResponse({"ok": True})
    set_session_cookie(resp, token)
    log_action(username, "login", username)
    return resp


@app.post("/api/logout")
def api_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        destroy_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE_NAME)
    return resp


@app.post("/api/admin/change-password")
def api_change_admin_password(payload: dict = Body(...), admin: str = Depends(require_admin_api)):
    current = payload.get("current_password") or ""
    new = payload.get("new_password") or ""
    with db_cursor() as cur:
        cur.execute("SELECT password_hash FROM admins WHERE username = ?", (admin,))
        row = cur.fetchone()
    if not row or not verify_password(current, row["password_hash"]):
        raise HTTPException(400, "Password attuale errata.")
    if len(new) < 8:
        raise HTTPException(400, "La nuova password deve avere almeno 8 caratteri.")
    change_admin_password(admin, new)
    log_action(admin, "change-own-password", admin)
    return {"ok": True}


# --------------------------------------------------------------------------
# API - Gestione utenti
# --------------------------------------------------------------------------
@app.get("/api/users")
def api_list_users(admin: str = Depends(require_admin_api)):
    with db_cursor() as cur:
        cur.execute("SELECT username, created_at, expiry_date, suspended, notes FROM users ORDER BY username")
        rows = [dict(r) for r in cur.fetchall()]
    today = date.today().isoformat()
    for r in rows:
        r["expired"] = bool(r["expiry_date"] and r["expiry_date"] <= today)
    return {"users": rows}


@app.post("/api/users")
def api_create_user(payload: dict = Body(...), admin: str = Depends(require_admin_api)):
    username = (payload.get("username") or "").strip().lower()
    password = payload.get("password") or ""
    infinite = bool(payload.get("infinite"))
    expiry_date = None if infinite else (payload.get("expiry_date") or None)

    if not USERNAME_RE.match(username):
        raise HTTPException(400, "Username non valido (minuscolo, 2-32 caratteri, lettere/numeri/-/_).")
    if len(password) < 8:
        raise HTTPException(400, "La password deve avere almeno 8 caratteri.")
    if expiry_date:
        try:
            datetime.strptime(expiry_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "Formato data di scadenza non valido (YYYY-MM-DD).")

    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        if cur.fetchone():
            raise HTTPException(409, "Utente gia' esistente.")

    try:
        samba_manager.create_linux_user(username)
        samba_manager.set_samba_password(username, password, new_user=True)
        if expiry_date:
            samba_manager.set_account_expiry(username, expiry_date)
    except samba_manager.SambaCommandError as exc:
        raise HTTPException(500, f"Errore di sistema durante la creazione utente: {exc}")

    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (username, expiry_date, suspended) VALUES (?, ?, 0)",
            (username, expiry_date),
        )
    log_action(admin, "create-user", username, f"expiry={expiry_date}")
    return {"ok": True, "username": username}


@app.post("/api/users/{username}/suspend")
def api_suspend_user(username: str, admin: str = Depends(require_admin_api)):
    _assert_user_exists(username)
    try:
        samba_manager.disable_samba_user(username)
    except samba_manager.SambaCommandError as exc:
        raise HTTPException(500, str(exc))
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET suspended = 1 WHERE username = ?", (username,))
    log_action(admin, "suspend-user", username)
    return {"ok": True}


@app.post("/api/users/{username}/resume")
def api_resume_user(username: str, admin: str = Depends(require_admin_api)):
    _assert_user_exists(username)
    try:
        samba_manager.enable_samba_user(username)
    except samba_manager.SambaCommandError as exc:
        raise HTTPException(500, str(exc))
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET suspended = 0 WHERE username = ?", (username,))
    log_action(admin, "resume-user", username)
    return {"ok": True}


@app.post("/api/users/{username}/reset-password")
def api_reset_password(username: str, payload: dict = Body(...), admin: str = Depends(require_admin_api)):
    _assert_user_exists(username)
    new_password = payload.get("password") or ""
    if len(new_password) < 8:
        raise HTTPException(400, "La password deve avere almeno 8 caratteri.")
    try:
        samba_manager.reset_password(username, new_password)
    except samba_manager.SambaCommandError as exc:
        raise HTTPException(500, str(exc))
    log_action(admin, "reset-password", username)
    return {"ok": True}


@app.post("/api/users/{username}/expiry")
def api_set_expiry(username: str, payload: dict = Body(...), admin: str = Depends(require_admin_api)):
    _assert_user_exists(username)
    infinite = bool(payload.get("infinite"))
    expiry_date = None if infinite else (payload.get("expiry_date") or None)
    try:
        samba_manager.set_account_expiry(username, expiry_date)
    except samba_manager.SambaCommandError as exc:
        raise HTTPException(500, str(exc))
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET expiry_date = ? WHERE username = ?", (expiry_date, username))
    log_action(admin, "set-expiry", username, f"expiry={expiry_date}")
    return {"ok": True}


@app.delete("/api/users/{username}")
def api_delete_user(username: str, admin: str = Depends(require_admin_api)):
    _assert_user_exists(username)
    try:
        samba_manager.delete_user_completely(username)
    except Exception as exc:
        pass  # procede comunque con la pulizia lato ACL/DB
    acl_manager.remove_all_permissions_for_user(username)
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM users WHERE username = ?", (username,))
    log_action(admin, "delete-user", username)
    return {"ok": True}


def _assert_user_exists(username: str):
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        if not cur.fetchone():
            raise HTTPException(404, "Utente non trovato.")


# --------------------------------------------------------------------------
# API - Albero cartelle (scansione dinamica) e permessi ACL
# --------------------------------------------------------------------------
@app.get("/api/tree")
def api_tree(path: str = "", admin: str = Depends(require_admin_api)):
    try:
        children = acl_manager.list_children(path)
    except acl_manager.AclError as exc:
        raise HTTPException(400, str(exc))
    return {"path": path, "children": children}


@app.get("/api/permissions/{username}")
def api_get_permission(username: str, path: str = "", admin: str = Depends(require_admin_api)):
    _assert_user_exists(username)
    perm = acl_manager.get_effective_permission(username, path)
    return perm


@app.get("/api/permissions/{username}/all")
def api_get_all_permissions(username: str, admin: str = Depends(require_admin_api)):
    _assert_user_exists(username)
    return {"assignments": acl_manager.list_all_permissions_for_user(username)}


@app.post("/api/permissions/{username}")
def api_set_permission(username: str, payload: dict = Body(...), admin: str = Depends(require_admin_api)):
    _assert_user_exists(username)
    path = payload.get("path", "")
    read = bool(payload.get("read"))
    write = bool(payload.get("write"))
    delete = bool(payload.get("delete"))
    recursive = payload.get("recursive", True)
    try:
        result = acl_manager.apply_permissions(username, path, read, write, delete, recursive=recursive)
    except acl_manager.AclError as exc:
        raise HTTPException(400, str(exc))
    log_action(admin, "set-permission", username, f"path={path} r={read} w={write} d={delete} recursive={recursive}")
    return result


# --------------------------------------------------------------------------
# API - Configurazione Samba (fix force user / valid users)
# --------------------------------------------------------------------------
@app.get("/api/system/smbconf-status")
def api_smbconf_status(admin: str = Depends(require_admin_api)):
    status = smbconf_manager.get_current_status()
    status["zfs_warning"] = acl_manager.check_zfs_acl_support()
    status["samba_group"] = SAMBA_GROUP
    return status


@app.post("/api/system/patch-smbconf")
def api_patch_smbconf(admin: str = Depends(require_admin_api)):
    try:
        result = smbconf_manager.patch_smb_conf()
    except smbconf_manager.SmbConfError as exc:
        raise HTTPException(500, str(exc))
    log_action(admin, "patch-smbconf", "smb.conf", str(result))
    return {"ok": True, **result}


# --------------------------------------------------------------------------
# API - Audit log
# --------------------------------------------------------------------------
@app.get("/api/audit")
def api_audit(limit: int = 20, admin: str = Depends(require_admin_api)):
    limit = max(1, min(limit, 200))
    with db_cursor() as cur:
        cur.execute(
            "SELECT timestamp, admin_username, action, target, details FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return {"entries": rows}
