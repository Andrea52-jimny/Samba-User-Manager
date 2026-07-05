"""
Entry point della Web App (FastAPI).

Avvio (vedi anche install.sh e samba-manager.service):
    uvicorn app.main:app --host 0.0.0.0 --port 8000
Deve girare come root (o con i privilegi sudo necessari) perché esegue
useradd/userdel/smbpasswd/setfacl/testparm sul sistema del container.
"""
import datetime
import logging

from fastapi import FastAPI, Depends, HTTPException, Response, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import SESSION_COOKIE_NAME, SESSION_DURATION_HOURS, SHARE_ROOT, SESSION_COOKIE_SECURE
from app.database import init_db, db_cursor
from app.models import (
    LoginRequest, CreateUserRequest, ResetPasswordRequest, SetPermissionRequest,
)
from app.security import (
    authenticate_admin, create_session, destroy_session, require_login,
    get_session_admin,
)
from app.system_users import (
    create_system_and_samba_user, reset_samba_password, suspend_samba_user,
    reactivate_samba_user, delete_system_and_samba_user, ensure_samba_group_exists,
    validate_username,
)
from app.acl_manager import (
    list_children, get_user_permission, apply_permission, remove_permission,
    purge_user_acl_everywhere, PathSecurityError,
)
from app.smb_conf_manager import fix_dati_section, is_force_user_active
from app.shell import SystemCommandError
from app.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("samba_manager")

app = FastAPI(title="Samba Permission Manager")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def on_startup():
    init_db()
    try:
        ensure_samba_group_exists()
    except Exception as exc:  # non bloccante: l'admin potrà comunque loggarsi
        logger.warning("Impossibile verificare/creare il gruppo Samba: %s", exc)
    start_scheduler()


# ---------------------------------------------------------------------------
# Pagine HTML
# ---------------------------------------------------------------------------

@app.get("/login")
def login_page(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if get_session_admin(token):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html")


@app.get("/")
def dashboard_page(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    admin = get_session_admin(token)
    if not admin:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "dashboard.html", {"admin": admin})


@app.get("/permissions/{username}")
def permissions_page(request: Request, username: str):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    admin = get_session_admin(token)
    if not admin:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request, "permissions.html", {"admin": admin, "username": username}
    )


# ---------------------------------------------------------------------------
# API - Autenticazione
# ---------------------------------------------------------------------------

@app.post("/api/login")
def api_login(payload: LoginRequest, response: Response):
    if not authenticate_admin(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    token = create_session(payload.username)
    response.set_cookie(
        SESSION_COOKIE_NAME, token,
        httponly=True, samesite="lax", secure=SESSION_COOKIE_SECURE,
        max_age=SESSION_DURATION_HOURS * 3600,
    )
    return {"ok": True}


@app.post("/api/logout")
def api_logout(response: Response, request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        destroy_session(token)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


# ---------------------------------------------------------------------------
# API - Gestione utenti
# ---------------------------------------------------------------------------

@app.get("/api/users")
def api_list_users(admin: str = Depends(require_login)):
    with db_cursor() as cur:
        cur.execute(
            "SELECT username, expiry_date, is_suspended, created_at FROM managed_users ORDER BY username"
        )
        rows = [dict(r) for r in cur.fetchall()]
    return {"users": rows}


@app.post("/api/users")
def api_create_user(payload: CreateUserRequest, admin: str = Depends(require_login)):
    try:
        validate_username(payload.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    expiry = None if payload.no_expiry else payload.expiry_date
    if expiry:
        try:
            datetime.date.fromisoformat(expiry)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato data scadenza non valido (YYYY-MM-DD)")

    try:
        create_system_and_samba_user(payload.username, payload.password)
    except SystemCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO managed_users (username, expiry_date, is_suspended) VALUES (?, ?, 0)",
            (payload.username, expiry),
        )
    return {"ok": True, "username": payload.username}


@app.post("/api/users/{username}/suspend")
def api_toggle_suspend(username: str, admin: str = Depends(require_login)):
    with db_cursor() as cur:
        cur.execute("SELECT is_suspended FROM managed_users WHERE username = ?", (username,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    try:
        if row["is_suspended"]:
            reactivate_samba_user(username)
            new_state = 0
        else:
            suspend_samba_user(username)
            new_state = 1
    except SystemCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with db_cursor() as cur:
        cur.execute(
            "UPDATE managed_users SET is_suspended = ?, suspended_at = CASE WHEN ? = 1 THEN datetime('now') ELSE NULL END WHERE username = ?",
            (new_state, new_state, username),
        )
    return {"ok": True, "is_suspended": bool(new_state)}


@app.post("/api/users/{username}/reset-password")
def api_reset_password(username: str, payload: ResetPasswordRequest, admin: str = Depends(require_login)):
    try:
        reset_samba_password(username, payload.new_password)
    except SystemCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.delete("/api/users/{username}")
def api_delete_user(username: str, admin: str = Depends(require_login)):
    try:
        delete_system_and_samba_user(username)
        purge_user_acl_everywhere(username)
    except SystemCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with db_cursor() as cur:
        cur.execute("DELETE FROM managed_users WHERE username = ?", (username,))
        cur.execute("DELETE FROM permissions WHERE username = ?", (username,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# API - Albero cartelle e permessi ACL
# ---------------------------------------------------------------------------

@app.get("/api/tree")
def api_tree(path: str = "", admin: str = Depends(require_login)):
    try:
        nodes = list_children(path)
    except PathSecurityError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SystemCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "share_root": SHARE_ROOT,
        "nodes": [
            {"name": n.name, "rel_path": n.rel_path, "has_children": n.has_children}
            for n in nodes
        ],
    }


@app.get("/api/permissions")
def api_get_permission(username: str, path: str = "", admin: str = Depends(require_login)):
    try:
        validate_username(username)
        perm = get_user_permission(username, path)
    except (PathSecurityError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return perm


@app.post("/api/permissions")
def api_set_permission(payload: SetPermissionRequest, admin: str = Depends(require_login)):
    try:
        validate_username(payload.username)
        if payload.read or payload.write or payload.delete:
            apply_permission(
                payload.username, payload.path,
                payload.read, payload.write, payload.delete,
                recursive=payload.recursive,
            )
        else:
            remove_permission(payload.username, payload.path, recursive=payload.recursive)
    except (PathSecurityError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SystemCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO permissions (username, path, can_read, can_write, can_delete, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(username, path) DO UPDATE SET
                 can_read=excluded.can_read, can_write=excluded.can_write,
                 can_delete=excluded.can_delete, updated_at=datetime('now')""",
            (payload.username, payload.path, int(payload.read), int(payload.write), int(payload.delete)),
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# API - Fix configurazione Samba (force user)
# ---------------------------------------------------------------------------

@app.get("/api/smb-status")
def api_smb_status(admin: str = Depends(require_login)):
    return {"force_user_active": is_force_user_active()}


@app.post("/api/smb-fix")
def api_smb_fix(admin: str = Depends(require_login)):
    try:
        backup_path = fix_dati_section()
    except SystemCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "backup": backup_path}
