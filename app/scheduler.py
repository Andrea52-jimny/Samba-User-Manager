"""
Job in background che controlla periodicamente gli utenti con una data di
scadenza account impostata e sospende automaticamente (Samba + DB) quelli
scaduti, senza intervento manuale dell'amministratore.
"""
import datetime
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import EXPIRY_CHECK_INTERVAL_MINUTES
from app.database import db_cursor
from app.system_users import suspend_samba_user
from app.shell import SystemCommandError

logger = logging.getLogger("samba_manager.scheduler")


def check_and_suspend_expired_accounts() -> None:
    today = datetime.date.today().isoformat()
    with db_cursor() as cur:
        cur.execute(
            """SELECT username FROM managed_users
               WHERE is_suspended = 0
                 AND expiry_date IS NOT NULL
                 AND expiry_date <= ?""",
            (today,),
        )
        expired = [row["username"] for row in cur.fetchall()]

    for username in expired:
        try:
            suspend_samba_user(username)
            with db_cursor() as cur:
                cur.execute(
                    "UPDATE managed_users SET is_suspended = 1, suspended_at = datetime('now') WHERE username = ?",
                    (username,),
                )
            logger.info("Account '%s' sospeso automaticamente per scadenza.", username)
        except SystemCommandError as exc:
            logger.error("Impossibile sospendere '%s' alla scadenza: %s", username, exc)


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        check_and_suspend_expired_accounts,
        "interval",
        minutes=EXPIRY_CHECK_INTERVAL_MINUTES,
        id="expiry_check",
        next_run_time=datetime.datetime.utcnow(),  # esegue subito un primo controllo
    )
    scheduler.start()
    return scheduler
