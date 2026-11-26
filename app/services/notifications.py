"""In-app notifications + optional email alerts, with de-duplication.

Works with or without email configured: every alert is always recorded in-app.
Alert keys make repeated checks idempotent, so the same unchanged condition is
never reported twice.
"""
from __future__ import annotations

import smtplib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app import models as m
from app.core.config import settings
from app.services import budget as budget_svc

MAX_ATTEMPTS = 3

KIND_CATEGORY = {
    "budget": "finance", "inventory": "materials", "deadline": "schedule",
    "quotation": "procurement", "approval": "approvals", "report": "reports",
    "email": "communication", "email_failed": "communication", "weather": "schedule",
    "automation": "automation", "test": "system", "system": "system",
}
KIND_PRIORITY = {"budget": "high", "email_failed": "high", "approval": "high",
                 "deadline": "high", "inventory": "normal", "quotation": "normal",
                 "weather": "normal", "test": "low", "system": "low"}


def _smtp_send(msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
        if settings.smtp_use_tls:
            s.starttls()
        if settings.smtp_username:
            s.login(settings.smtp_username, settings.smtp_password)
        s.send_message(msg)


transport = _smtp_send  # replaceable in tests


def send(db: Session, *, recipient: str, subject: str, body: str, alert_key: str, kind: str,
         project_id: int | None = None, owner_id: int | None = None, force: bool = False,
         link: str = "", priority: str | None = None) -> m.Notification:
    n = db.query(m.Notification).filter_by(alert_key=alert_key).first()
    if n and not force:
        if n.status == "sent":
            return n                                   # duplicate prevention
        if n.status == "disabled" and not settings.email_enabled:
            return n
        if n.attempts >= MAX_ATTEMPTS:
            return n
    if not n:
        n = m.Notification(alert_key=alert_key, kind=kind, category=KIND_CATEGORY.get(kind, "system"),
                           priority=priority or KIND_PRIORITY.get(kind, "normal"),
                           subject=subject, body=body, recipient=recipient,
                           project_id=project_id, owner_id=owner_id, link=link)
        db.add(n)
    if not settings.email_enabled:
        n.status, n.error = "disabled", "Email delivery is off — recorded in-app only"
    elif not recipient:
        n.status, n.error = "failed", "No recipient configured"
    else:
        n.attempts = (n.attempts or 0) + 1
        try:
            msg = EmailMessage()
            msg["Subject"], msg["To"] = subject, recipient
            msg["From"] = settings.smtp_from or settings.smtp_username
            msg.set_content(body)
            transport(msg)
            n.status, n.error = "sent", ""
            n.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
        except Exception as e:  # noqa: BLE001
            n.status, n.error = "failed", str(e)[:500]
    db.commit()
    return n


def _inr(x) -> str:
    x = int(Decimal(str(x)))
    digits = str(abs(x))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    else:
        s = digits
    return ("-" if x < 0 else "") + "₹" + s


def check_budgets(db: Session) -> list[m.Notification]:
    created = []
    for p in db.query(m.Project).filter(m.Project.status != "completed", m.Project.archived.is_(False)).all():
        s = budget_svc.summary(db, p)
        if s["utilization_pct"] is None:
            continue
        crossed = [t for t in settings.budget_thresholds if s["utilization_pct"] >= t]
        if not crossed:
            continue
        t = max(crossed)
        owner = db.get(m.User, p.owner_id)
        body = (f"Hello,\n\nYour construction project has reached {t}% of its approved budget.\n\n"
                f"Project: {p.name}\nApproved budget: {_inr(s['approved_budget'])}\n"
                f"Actual expenses: {_inr(s['actual_expenses'])}\nRemaining budget: {_inr(s['remaining_budget'])}\n\n"
                "Please review your project estimate and pending expenses.\n\nRegards,\nBuildBudget AI")
        created.append(send(db, recipient=settings.notification_email or (owner.email if owner else ""),
                            subject=f"BuildBudget AI — {p.name} has used {t}% of its budget", body=body,
                            alert_key=f"budget:{p.id}:{t}", kind="budget", project_id=p.id,
                            owner_id=p.owner_id, link=f"/projects/{p.id}?tab=budget",
                            priority="urgent" if t >= 100 else "high"))
    return created


def check_inventory(db: Session, today: date | None = None) -> list[m.Notification]:
    today = today or date.today()
    out = []
    for p in db.query(m.Project).filter(m.Project.status != "completed", m.Project.archived.is_(False)).all():
        low = [i for i in db.query(m.InventoryItem).filter_by(project_id=p.id)
               if i.reorder_level > 0 and i.available <= i.reorder_level]
        if not low:
            continue
        lines = "\n".join(f"{i.material_name}: available {i.available:g} {i.unit}, reorder level {i.reorder_level:g}"
                          for i in low)
        owner = db.get(m.User, p.owner_id)
        body = (f"Hello,\n\nThe following materials for '{p.name}' are at or below reorder level:\n\n{lines}\n\n"
                "Please review the draft purchase recommendation.\nNo supplier order has been placed automatically.\n\n"
                "Regards,\nBuildBudget AI")
        out.append(send(db, recipient=settings.notification_email or (owner.email if owner else ""),
                        subject=f"BuildBudget AI — {len(low)} material(s) need reordering for {p.name}",
                        body=body, alert_key=f"stock:{p.id}:{today}", kind="inventory",
                        project_id=p.id, owner_id=p.owner_id,
                        link=f"/projects/{p.id}?tab=inventory"))
    return out


def check_overdue_tasks(db: Session, today: date | None = None) -> list[m.Notification]:
    today = today or date.today()
    out = []
    for t in db.query(m.Task).filter(m.Task.start_date.isnot(None), m.Task.progress < 100):
        end = t.start_date + timedelta(days=t.duration_days)
        if end < today:
            p = db.get(m.Project, t.project_id)
            if not p:
                continue
            owner = db.get(m.User, p.owner_id)
            out.append(send(db, recipient=settings.notification_email or (owner.email if owner else ""),
                            subject=f"BuildBudget AI — '{t.name}' is overdue",
                            body=(f"Task '{t.name}' in project '{p.name}' was planned to finish by {end} "
                                  f"and is {t.progress:g}% complete.\n\nUpdate the task or its dates.\n\n"
                                  "Regards,\nBuildBudget AI"),
                            alert_key=f"overdue:{t.id}:{today}", kind="deadline",
                            project_id=p.id, owner_id=p.owner_id,
                            link=f"/projects/{p.id}?tab=schedule"))
    return out


def run_all(db: Session) -> list[m.Notification]:
    from app.services import automation
    created = check_budgets(db) + check_inventory(db) + check_overdue_tasks(db)
    created += automation.run_due(db)
    return created


# --------------------------------------------------------------------------- #
# inbox operations
# --------------------------------------------------------------------------- #
def list_for(db: Session, owner_id: int, *, unread_only: bool = False, kind: str | None = None,
             project_id: int | None = None, include_archived: bool = False,
             limit: int = 100) -> list[m.Notification]:
    q = db.query(m.Notification).filter(m.Notification.owner_id == owner_id)
    if not include_archived:
        q = q.filter(m.Notification.archived.is_(False))
    if unread_only:
        q = q.filter(m.Notification.read_at.is_(None))
    if kind:
        q = q.filter(m.Notification.kind == kind)
    if project_id:
        q = q.filter(m.Notification.project_id == project_id)
    return q.order_by(m.Notification.id.desc()).limit(limit).all()


def unread_count(db: Session, owner_id: int) -> int:
    return (db.query(m.Notification)
            .filter(m.Notification.owner_id == owner_id, m.Notification.read_at.is_(None),
                    m.Notification.archived.is_(False)).count())


def mark_read(db: Session, owner_id: int, ids: list[int] | None = None) -> int:
    q = db.query(m.Notification).filter(m.Notification.owner_id == owner_id,
                                        m.Notification.read_at.is_(None))
    if ids:
        q = q.filter(m.Notification.id.in_(ids))
    n = q.update({"read_at": m.now()}, synchronize_session=False)
    db.commit()
    return n


def archive(db: Session, owner_id: int, notification_id: int) -> None:
    n = db.query(m.Notification).filter_by(id=notification_id, owner_id=owner_id).first()
    if not n:
        raise ValueError("Notification not found")
    n.archived = True
    db.commit()


def create_inapp(db: Session, owner_id: int, *, subject: str, body: str, kind: str = "system",
                 project_id: int | None = None, link: str = "", priority: str | None = None,
                 key: str | None = None) -> m.Notification:
    """An in-app notification that never leaves the application."""
    key = key or f"inapp:{owner_id}:{kind}:{m.now().isoformat()}"
    return send(db, recipient="", subject=subject, body=body, alert_key=key, kind=kind,
                project_id=project_id, owner_id=owner_id, link=link, priority=priority)


def serialize(n: m.Notification) -> dict:
    return {
        "id": n.id, "kind": n.kind, "category": n.category, "priority": n.priority,
        "subject": n.subject, "body": n.body, "status": n.status, "attempts": n.attempts,
        "error": n.error, "project_id": n.project_id, "link": n.link,
        "read": n.read_at is not None, "read_at": n.read_at, "archived": n.archived,
        "created_at": n.created_at, "sent_at": n.sent_at,
    }
