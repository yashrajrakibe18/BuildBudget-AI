"""Configurable automation rules (automatic mailing).

A rule is user-configured, persisted and auditable. External email is only ever
sent when the rule explicitly allows it *and* the app has a real mail provider
configured; otherwise the rule records an in-app notification and says why.
Execution is idempotent per (rule, condition window) so repeated scheduler ticks
cannot spam the same alert.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app import models as m
from app.core.config import settings
from app.core.labels import AUTOMATION_TRIGGERS
from app.services import budget as budget_svc
from app.services import mail, notifications

SUPPORTED = set(AUTOMATION_TRIGGERS)


def next_run(rule: m.AutomationRule, now: datetime | None = None) -> datetime | None:
    """Daily/weekly/monthly rules get a real next-run; event rules are checked each tick."""
    now = now or m.now()
    if rule.schedule == "daily":
        hour = int(settings.daily_summary_time.split(":")[0])
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)
    if rule.schedule == "weekly":
        return now + timedelta(days=(7 - now.weekday()) % 7 or 7)
    if rule.schedule == "monthly":
        return now + timedelta(days=28)
    return None


def evaluate(db: Session, rule: m.AutomationRule, today: date | None = None) -> dict | None:
    """Return a condition dict when the rule fires, else None. Never sends email."""
    today = today or date.today()
    projects = ([db.get(m.Project, rule.project_id)] if rule.project_id
                else db.query(m.Project).filter_by(owner_id=rule.user_id, archived=False).all())
    projects = [p for p in projects if p]

    if rule.trigger in ("budget_threshold", "over_budget"):
        threshold = rule.threshold or (100 if rule.trigger == "over_budget" else 90)
        for p in projects:
            s = budget_svc.summary(db, p)
            if s["utilization_pct"] is not None and s["utilization_pct"] >= threshold:
                return {"project": p, "summary": s, "threshold": threshold,
                        "title": f"{p.name} reached {s['utilization_pct']}% of budget",
                        "body": (f"{p.name} has used {s['utilization_pct']}% of its approved budget.\n"
                                 f"Approved: ₹{s['approved_budget']:,.0f}\nActual: ₹{s['actual_expenses']:,.0f}\n"
                                 f"Remaining: ₹{s['remaining_budget']:,.0f}")}
        return None

    if rule.trigger == "low_stock":
        for p in projects:
            low = [i for i in db.query(m.InventoryItem).filter_by(project_id=p.id)
                   if i.reorder_level > 0 and i.available <= i.reorder_level]
            if low:
                lines = "\n".join(f"• {i.material_name}: {i.available:g} {i.unit} left "
                                  f"(reorder at {i.reorder_level:g})" for i in low)
                return {"project": p, "summary": None, "threshold": None,
                        "title": f"{len(low)} material(s) low on stock for {p.name}", "body": lines}
        return None

    if rule.trigger == "overdue_task":
        for p in projects:
            late = [t for t in db.query(m.Task).filter_by(project_id=p.id)
                    if t.start_date and t.progress < 100
                    and t.start_date + timedelta(days=t.duration_days) < today]
            if late:
                lines = "\n".join(f"• {t.name} (planned finish "
                                  f"{(t.start_date + timedelta(days=t.duration_days)):%d %b %Y}, {t.progress:g}% done)"
                                  for t in late)
                return {"project": p, "summary": None, "threshold": None,
                        "title": f"{len(late)} overdue task(s) in {p.name}", "body": lines}
        return None

    if rule.trigger == "quotation_expiring":
        soon = today + timedelta(days=int(rule.threshold or 7))
        rows = (db.query(m.MaterialPrice).join(m.Material)
                .filter(m.MaterialPrice.owner_id == rule.user_id,
                        m.MaterialPrice.valid_until.isnot(None),
                        m.MaterialPrice.valid_until >= today,
                        m.MaterialPrice.valid_until <= soon).all())
        if rows:
            lines = "\n".join(f"• {r.material.name} from {r.supplier.name if r.supplier else 'unknown supplier'} "
                              f"expires {r.valid_until}" for r in rows[:10])
            return {"project": None, "summary": None, "threshold": None,
                    "title": f"{len(rows)} quotation(s) expire within {int(rule.threshold or 7)} days",
                    "body": lines}
        return None

    if rule.trigger in ("daily_summary", "weekly_summary", "monthly_expense_report"):
        if rule.project_id:
            p = projects[0] if projects else None
            if not p:
                return None
            s = budget_svc.summary(db, p)
            return {"project": p, "summary": s, "threshold": None,
                    "title": f"{p.name}: {rule.trigger.replace('_', ' ')}",
                    "body": (f"Status: {p.status}\nApproved budget: ₹{s['approved_budget']:,.0f}\n"
                             f"Actual spend: ₹{s['actual_expenses']:,.0f}\n"
                             f"Remaining: ₹{s['remaining_budget']:,.0f}")}
        return None

    return None


def run_rule(db: Session, rule: m.AutomationRule, today: date | None = None) -> m.AutomationRun | None:
    condition = evaluate(db, rule, today)
    if not condition:
        return None
    window = (today or date.today()).isoformat()
    key = f"auto:{rule.id}:{window}"
    already = db.query(m.Notification).filter_by(alert_key=key).first()
    if already:
        return None

    recipients = rule.recipients or ""
    provider_ok, provider_why = mail.SMTPProvider().available()
    sent = False
    status = "recorded"
    detail = "In-app notification recorded."

    if rule.require_approval:
        # Create an approval request instead of sending; the human decides.
        from app.services import approvals
        draft = mail.draft(db, db.get(m.User, rule.user_id), to=recipients,
                           subject=f"[Automation] {condition['title']}",
                           body=condition["body"] + "\n\n— BuildBudget AI automation",
                           project_id=condition["project"].id if condition["project"] else None)
        a = approvals.create(db, db.get(m.User, rule.user_id), action="send_email",
                             payload={"draft_id": draft.id}, project_id=draft.project_id,
                             title=f"Automation email: {condition['title']}",
                             summary="An automation rule wants to email you. Approve to send.")
        draft.approval_id = a.id
        draft.status = "pending_approval"
        db.commit()
        status, detail = "approval_requested", f"Approval #{a.id} created; nothing sent yet."
    elif recipients and settings.email_enabled and provider_ok:
        draft = mail.draft(db, db.get(m.User, rule.user_id), to=recipients,
                           subject=f"[Automation] {condition['title']}",
                           body=condition["body"] + "\n\n— BuildBudget AI automation",
                           project_id=condition["project"].id if condition["project"] else None)
        try:
            mail.send_approved(db, draft)
            sent = True
            status, detail = "sent", f"Email sent to {recipients}."
        except mail.MailError as exc:
            status, detail = "failed", str(exc)[:250]
    else:
        detail = provider_why or "Email delivery is not configured; the alert is in-app only."

    notifications.send(db, recipient=recipients, subject=condition["title"], body=condition["body"],
                       alert_key=key, kind="automation", owner_id=rule.user_id,
                       project_id=condition["project"].id if condition["project"] else None,
                       link=f"/projects/{condition['project'].id}" if condition["project"] else "/automations",
                       priority="high")
    run = m.AutomationRun(rule_id=rule.id, status=status,
                          detail=detail + (" (email sent)" if sent else ""))
    db.add(run)
    rule.last_run_at = m.now()
    rule.last_result = detail[:300]
    rule.next_run_at = next_run(rule)
    db.commit()
    return run


def run_due(db: Session, today: date | None = None) -> list[m.Notification]:
    runs = []
    for rule in db.query(m.AutomationRule).filter_by(enabled=True).all():
        try:
            run = run_rule(db, rule, today)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            db.add(m.AutomationRun(rule_id=rule.id, status="error", detail=str(exc)[:300]))
            db.commit()
            continue
        if run:
            runs.append(run)
    return runs


def serialize(rule: m.AutomationRule, runs: list[m.AutomationRun] | None = None) -> dict:
    return {
        "id": rule.id, "name": rule.name, "trigger": rule.trigger, "threshold": rule.threshold,
        "recipients": rule.recipients, "template": rule.template, "schedule": rule.schedule,
        "timezone": rule.timezone, "require_approval": rule.require_approval,
        "enabled": rule.enabled, "project_id": rule.project_id,
        "last_run_at": rule.last_run_at, "next_run_at": rule.next_run_at,
        "last_result": rule.last_result,
        "history": [{"id": r.id, "status": r.status, "detail": r.detail,
                     "created_at": r.created_at} for r in (runs or [])],
    }
