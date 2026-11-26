"""APScheduler jobs. Deterministic database work only — the LLM is never called here.

Run exactly ONE scheduler process (scripts/run_scheduler.py). Multiple web workers
must not each start a scheduler, which is why SCHEDULER_IN_APP stays false in production.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.database import SessionLocal, init_db
from app.services import mail, notifications

log = logging.getLogger("scheduler")


def _run_checks() -> int:
    db = SessionLocal()
    try:
        created = notifications.check_budgets(db) + notifications.check_inventory(db)
        from app.services import automation
        created += automation.run_due(db)
        log.info("alert checks -> %d notification(s)", len(created))
        return len(created)
    finally:
        db.close()


def _send_due_mail() -> int:
    db = SessionLocal()
    try:
        sent = mail.send_due(db)
        if sent:
            log.info("scheduled mail -> %d sent", len(sent))
        return len(sent)
    finally:
        db.close()


def _overdue() -> int:
    db = SessionLocal()
    try:
        return len(notifications.check_overdue_tasks(db))
    finally:
        db.close()


def job_summary() -> list[dict]:
    return [
        {"id": "budget_checks", "description": "Budget, stock and automation checks",
         "interval_minutes": settings.check_interval_min},
        {"id": "mail_due", "description": "Send scheduled email that is due", "interval_minutes": 5},
        {"id": "overdue_tasks", "description": "Daily overdue task alerts",
         "at": settings.daily_summary_time},
    ]


def start() -> BackgroundScheduler:
    init_db()
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(_run_checks, "interval", minutes=settings.check_interval_min,
                      id="budget_checks", coalesce=True, max_instances=1, replace_existing=True)
    scheduler.add_job(_send_due_mail, "interval", minutes=5, id="mail_due", coalesce=True,
                      max_instances=1, replace_existing=True)
    hour, minute = settings.daily_summary_time.split(":")
    scheduler.add_job(_overdue, CronTrigger(hour=int(hour), minute=int(minute),
                                           timezone=settings.timezone),
                      id="overdue_tasks", coalesce=True, max_instances=1, replace_existing=True)
    scheduler.start()
    log.info("Scheduler started (tz=%s, email_enabled=%s, interval=%s min)",
             settings.timezone, settings.email_enabled, settings.check_interval_min)
    return scheduler


def once() -> dict:
    """Run one full cycle immediately (scripts and tests)."""
    return {"notifications": _run_checks(), "mail_sent": _send_due_mail(), "overdue": _overdue()}
