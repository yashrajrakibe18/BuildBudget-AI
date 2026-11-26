"""Dashboard, analytics, notifications, mail centre, automation, settings and meta."""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import models as m
from app.ai.tools_ops import REPORT_DIR
from app.api import serialize
from app.api.deps import current_user, owned_project, require
from app.api.schemas import AiMailIn, AutomationIn, DraftIn, DraftPatch, MarkReadIn, ScheduleIn
from app.core import permissions as P
from app.core import ratelimit
from app.core.config import settings
from app.core.labels import AUTOMATION_TRIGGERS, EXPORT_CATEGORIES, all_labels
from app.database import get_db
from app.services import activity, analytics, automation, dashboard, mail, notifications, rag

router = APIRouter()


# --------------------------------------------------------------------------- #
# dashboard + analytics
# --------------------------------------------------------------------------- #
@router.get("/dashboard")
def get_dashboard(project_id: Optional[int] = None, status: str = "", location: str = "",
                  months: int = Query(12, ge=3, le=36), include_archived: bool = False,
                  user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if project_id:
        owned_project(db, user, project_id)
    return dashboard.overview(db, user, project_id=project_id, status=status or None,
                              location=location or None, months=months,
                              include_archived=include_archived)


@router.get("/analytics")
def get_analytics(project_id: Optional[int] = None, months: int = Query(12, ge=3, le=36),
                  user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if project_id:
        owned_project(db, user, project_id)
    projects = dashboard.visible_projects(db, user)
    if project_id:
        projects = [p for p in projects if p.id == project_id]
    series = analytics.expense_series(db, user.id, project_id, months)
    return {
        "expense_series": series,
        "trend": analytics.trend_analysis(series),
        "forecast": analytics.forecast_expenses(series),
        "anomalies": analytics.detect_unusual_expenses(db, user.id, project_id),
        "budget_risk": analytics.budget_risk(db, projects),
        "health": [analytics.project_health(db, p) for p in projects],
        "consumption": analytics.material_consumption(db, user.id, project_id),
        "suppliers": analytics.supplier_performance(db, user.id),
        "method_notes": [
            "Trend: ordinary least squares on monthly recorded expenses.",
            "Forecast: OLS with a held-out tail; MAE/MAPE reported. Needs enough history.",
            "Anomalies: robust z-score (median/MAD) — a statistical flag, not proof of fraud.",
            "Supplier performance: on-time delivery from purchase orders you recorded.",
        ],
    }


# --------------------------------------------------------------------------- #
# notifications
# --------------------------------------------------------------------------- #
@router.get("/notifications")
def list_notifications(unread_only: bool = False, kind: str = "",
                       project_id: Optional[int] = None, include_archived: bool = False,
                       user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = notifications.list_for(db, user.id, unread_only=unread_only, kind=kind or None,
                                  project_id=project_id, include_archived=include_archived)
    projects = {p.id: p.name for p in dashboard.visible_projects(db, user)}
    return {"unread": notifications.unread_count(db, user.id),
            "items": [{**serialize.notification(n), "project": projects.get(n.project_id)}
                      for n in rows]}


@router.post("/notifications/mark-read")
def mark_read(body: MarkReadIn, user: m.User = Depends(current_user),
              db: Session = Depends(get_db)):
    count = notifications.mark_read(db, user.id, body.ids or None)
    return {"ok": True, "updated": count, "unread": notifications.unread_count(db, user.id)}


@router.post("/notifications/{nid}/archive")
def archive_notification(nid: int, user: m.User = Depends(current_user),
                         db: Session = Depends(get_db)):
    try:
        notifications.archive(db, user.id, nid)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    return {"ok": True, "unread": notifications.unread_count(db, user.id)}


@router.get("/notifications/stream")
def notifications_stream(request: Request, user: m.User = Depends(current_user)):
    """Server-Sent Events heartbeat with the live unread count (60s windows)."""
    uid = user.id

    async def stream():
        from app.database import SessionLocal
        session = SessionLocal()
        started = time.time()
        last = None
        try:
            yield "retry: 10000\n\n"
            while time.time() - started < 60:
                if await request.is_disconnected():
                    break
                count = await run_in_threadpool(notifications.unread_count, session, uid)
                if count != last:
                    last = count
                    yield f"data: {json.dumps({'type': 'unread', 'count': count})}\n\n"
                else:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(8)
        finally:
            session.close()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/notifications/run-checks")
def run_checks(user: m.User = Depends(require("notification.manage")),
               db: Session = Depends(get_db)):
    created = notifications.check_budgets(db) + notifications.check_inventory(db) + \
        notifications.check_overdue_tasks(db)
    return {"processed": len(created),
            "items": [serialize.notification(n) for n in created]}


@router.post("/notifications/test-email")
def test_email(user: m.User = Depends(require("notification.manage")),
               db: Session = Depends(get_db)):
    status = mail.provider_status()
    if status["state"] != "ready":
        return {"status": "not_sent", "message": status["message"], "provider": status}
    row = notifications.send(
        db, recipient=settings.notification_email or user.email,
        subject="BuildBudget AI — test email", body="This is a test email from BuildBudget AI.",
        alert_key=f"test:{user.id}:{datetime.utcnow().isoformat()}",
        kind="test", owner_id=user.id, force=True, link="/notifications")
    return {"status": row.status, "error": row.error, "provider": status}


# --------------------------------------------------------------------------- #
# mail centre
# --------------------------------------------------------------------------- #
@router.get("/mail/status")
def mail_status(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return {"provider": mail.provider_status(), "counts": mail.counts(db, user.id),
            "from_address": settings.smtp_from or settings.smtp_username,
            "gmail": {
                "implemented": False,
                "configured": settings.mail_status()["gmail_oauth_configured"],
                "message": ("Gmail API sending is implemented; mailbox synchronisation is not. "
                            "SMTP sending also works with a Gmail App Password."),
            }}


@router.get("/mail")
def list_mail(folder: str = "drafts", q: str = "", project_id: Optional[int] = None,
              user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if folder not in ("drafts", "pending_approval", "scheduled", "sent", "failed"):
        raise HTTPException(422, "Unknown folder")
    return {"folder": folder, "messages": mail.folder(db, user.id, folder, q, project_id),
            "counts": mail.counts(db, user.id)}


@router.get("/mail/{draft_id}")
def get_mail(draft_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    draft = db.get(m.EmailDraft, draft_id)
    if not draft or draft.user_id != user.id:
        raise HTTPException(404, "Email not found")
    return {"id": draft.id, "to": draft.to_addr, "cc": draft.cc_addr, "bcc": draft.bcc_addr,
            "subject": draft.subject, "body": draft.body_text,
            "attachments": mail.attachments_for(draft), "status": draft.status,
            "scheduled_at": draft.scheduled_at, "sent_at": draft.sent_at, "error": draft.error,
            "provider": draft.provider, "project_id": draft.project_id,
            "approval_id": draft.approval_id, "updated_at": draft.updated_at}


@router.post("/mail/drafts", status_code=201)
def create_draft(body: DraftIn, user: m.User = Depends(require("mail.send")),
                 db: Session = Depends(get_db)):
    if body.project_id:
        owned_project(db, user, body.project_id)
    draft = mail.draft(db, user, to=body.to, subject=body.subject, body=body.body, cc=body.cc,
                       bcc=body.bcc, project_id=body.project_id, supplier_id=body.supplier_id)
    return {"id": draft.id, "status": draft.status}


@router.post("/mail/ai-draft")
def ai_mail_draft(body: AiMailIn, user: m.User = Depends(require("mail.send")),
                  db: Session = Depends(get_db)):
    """Write the wording of an email from real project facts. Nothing is saved or sent."""
    from app.services import mail_ai
    body.purpose = body.purpose.strip()
    if not body.purpose:
        raise HTTPException(422, "Say what the email should be about first.")
    if not ratelimit.allow(f"mailai:{user.id}", limit=10, window_seconds=60):
        raise HTTPException(429, "Slow down a little \u2014 too many AI drafts in a minute.")
    project = owned_project(db, user, body.project_id) if body.project_id else None
    try:
        result = mail_ai.compose(db, user, purpose=body.purpose, project=project,
                                 tone=body.tone, recipient=body.recipient,
                                 subject_hint=body.subject_hint)
    except mail_ai.MailAiError as exc:
        raise HTTPException(503, str(exc)) from None
    return {"subject": result["subject"], "body": result["body"], "tone": result["tone"],
            "model": result["model"], "provider": result["provider"],
            "project": result["used_project"],
            "note": ("Written from your saved records. Check it, add the recipient and request "
                     "approval before it can be sent.")}


@router.put("/mail/{draft_id}")
def update_draft(draft_id: int, body: DraftPatch, user: m.User = Depends(require("mail.send")),
                 db: Session = Depends(get_db)):
    draft = db.get(m.EmailDraft, draft_id)
    if not draft or draft.user_id != user.id:
        raise HTTPException(404, "Email not found")
    if draft.status == "sent":
        raise HTTPException(409, "A sent email cannot be edited")
    mail.update(db, draft, **body.model_dump(exclude_unset=True))
    if draft.status == "pending_approval":
        draft.status = "draft"
        db.commit()
    return {"ok": True, "status": draft.status}


@router.delete("/mail/{draft_id}")
def delete_draft(draft_id: int, user: m.User = Depends(require("mail.send")),
                 db: Session = Depends(get_db)):
    draft = db.get(m.EmailDraft, draft_id)
    if not draft or draft.user_id != user.id:
        raise HTTPException(404, "Email not found")
    if draft.status == "sent":
        raise HTTPException(409, "Sent mail cannot be deleted here")
    db.delete(draft)
    db.commit()
    return {"ok": True}


def _mail_ready() -> dict:
    status = mail.provider_status()
    if status["state"] != "ready":
        raise HTTPException(409, status["message"])
    return status


@router.post("/mail/{draft_id}/request-approval")
def request_send_approval(draft_id: int, user: m.User = Depends(require("mail.send")),
                          db: Session = Depends(get_db)):
    from app.services import approvals
    draft = db.get(m.EmailDraft, draft_id)
    if not draft or draft.user_id != user.id:
        raise HTTPException(404, "Email not found")
    if not draft.to_addr.strip():
        raise HTTPException(422, "Add a recipient before sending")
    if draft.sent_at:
        raise HTTPException(409, "This email was already sent")
    _mail_ready()
    row = approvals.create(db, user, action="send_email", payload={"draft_id": draft.id},
                           project_id=draft.project_id,
                           title=f"Send email to {draft.to_addr}",
                           summary=f"Subject: {draft.subject}. Sent only after approval.")
    draft.approval_id, draft.status = row.id, "pending_approval"
    db.commit()
    return {"approval_id": row.id, "status": draft.status,
            "message": "Approval requested. Confirm in the Approval Centre to send."}


@router.post("/mail/{draft_id}/send")
def send_draft(draft_id: int, confirm: bool = False,
               user: m.User = Depends(require("mail.send")), db: Session = Depends(get_db)):
    """The human send action. `confirm=true` means the person clicked Approve & Send."""
    from app.services import approvals
    draft = db.get(m.EmailDraft, draft_id)
    if not draft or draft.user_id != user.id:
        raise HTTPException(404, "Email not found")
    if draft.sent_at:
        return {"status": "sent", "sent_at": draft.sent_at,
                "message": "This email was already sent."}
    if not draft.to_addr.strip():
        raise HTTPException(422, "Add a recipient before sending")
    _mail_ready()
    approval = db.get(m.ApprovalRequest, draft.approval_id) if draft.approval_id else None
    if not approval or approval.status != "pending":
        approval = approvals.create(db, user, action="send_email",
                                    payload={"draft_id": draft.id}, project_id=draft.project_id,
                                    title=f"Send email to {draft.to_addr}",
                                    summary=f"Subject: {draft.subject}")
        draft.approval_id = approval.id
        draft.status = "pending_approval"
        db.commit()
    if not confirm:
        return {"status": "approval_required", "approval_id": approval.id,
                "message": "Approval required before sending.",
                "preview": {"to": draft.to_addr, "subject": draft.subject, "body": draft.body_text}}
    if not P.can(user, "approval.decide"):
        raise HTTPException(403, "Your role cannot approve sending email")
    try:
        result = approvals.decide(db, approval, user, True)
    except approvals.ApprovalError as exc:
        raise HTTPException(409, str(exc)) from None
    if result.get("executed"):
        provider = mail.get_provider()
        if provider.name == "local":
            note = ("Captured in the local outbox (.run/mailbox). This is development capture, "
                    "not delivery to the recipient.")
        elif provider.name == "gmail_api":
            note = ("Accepted by the Gmail API. This is not proof that the recipient read it.")
        else:
            note = "Accepted by the mail provider. This is not proof of inbox delivery."
        return {"status": "sent", "message": f"Email sent to {draft.to_addr}.",
                "delivery_note": note, **result}
    return {"status": "failed", "message": result.get("message"),
            "approval_id": approval.id}


@router.post("/mail/{draft_id}/schedule")
def schedule_draft(draft_id: int, body: ScheduleIn, user: m.User = Depends(require("mail.send")),
                   db: Session = Depends(get_db)):
    draft = db.get(m.EmailDraft, draft_id)
    if not draft or draft.user_id != user.id:
        raise HTTPException(404, "Email not found")
    if not draft.to_addr.strip():
        raise HTTPException(422, "Add a recipient before scheduling")
    _mail_ready()
    try:
        mail.schedule(db, draft, body.when.replace(tzinfo=None))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"ok": True, "scheduled_at": draft.scheduled_at,
            "message": "Scheduled. The scheduler process sends it when due."}


@router.post("/mail/test-connection")
def mail_test(user: m.User = Depends(require("mail.send"))):
    return mail.test_connection()


# --------------------------------------------------------------------------- #
# automation
# --------------------------------------------------------------------------- #
@router.get("/automations")
def list_automations(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rules = db.query(m.AutomationRule).filter_by(user_id=user.id).order_by(m.AutomationRule.id.desc())
    return [{**automation.serialize(r,
                                    db.query(m.AutomationRun).filter_by(rule_id=r.id)
                                    .order_by(m.AutomationRun.id.desc()).limit(5).all()),
             "trigger_label": AUTOMATION_TRIGGERS.get(r.trigger, r.trigger)}
            for r in rules]


@router.get("/automations/triggers")
def automation_triggers():
    return {"triggers": [{"key": k, "label": v} for k, v in AUTOMATION_TRIGGERS.items()]}


@router.post("/automations", status_code=201)
def create_automation(body: AutomationIn, user: m.User = Depends(require("automation.manage")),
                      db: Session = Depends(get_db)):
    if body.trigger not in AUTOMATION_TRIGGERS:
        raise HTTPException(422, f"Unknown trigger. Use one of {sorted(AUTOMATION_TRIGGERS)}")
    if body.project_id:
        owned_project(db, user, body.project_id)
    rule = m.AutomationRule(user_id=user.id, **body.model_dump())
    db.add(rule)
    db.flush()
    rule.next_run_at = automation.next_run(rule)
    activity.log(db, user_id=user.id, action="automation_created",
                 project_id=body.project_id, entity="automation", entity_id=rule.id,
                 summary=rule.name)
    db.commit()
    return automation.serialize(rule)


@router.put("/automations/{rid}")
def update_automation(rid: int, body: AutomationIn,
                      user: m.User = Depends(require("automation.manage")),
                      db: Session = Depends(get_db)):
    rule = db.query(m.AutomationRule).filter_by(id=rid, user_id=user.id).first()
    if not rule:
        raise HTTPException(404, "Automation rule not found")
    for key, value in body.model_dump().items():
        setattr(rule, key, value)
    rule.next_run_at = automation.next_run(rule)
    db.commit()
    return automation.serialize(rule)


@router.delete("/automations/{rid}")
def delete_automation(rid: int, user: m.User = Depends(require("automation.manage")),
                      db: Session = Depends(get_db)):
    rule = db.query(m.AutomationRule).filter_by(id=rid, user_id=user.id).first()
    if not rule:
        raise HTTPException(404, "Automation rule not found")
    db.query(m.AutomationRun).filter_by(rule_id=rid).delete()
    db.delete(rule)
    db.commit()
    return {"ok": True}


@router.post("/automations/{rid}/run")
def run_automation(rid: int, user: m.User = Depends(require("automation.manage")),
                   db: Session = Depends(get_db)):
    rule = db.query(m.AutomationRule).filter_by(id=rid, user_id=user.id).first()
    if not rule:
        raise HTTPException(404, "Automation rule not found")
    run = automation.run_rule(db, rule)
    return {"ran": bool(run), "detail": run.detail if run else
            "Condition not met right now, so nothing was sent.",
            "status": run.status if run else "skipped"}


# --------------------------------------------------------------------------- #
# reports + global search
# --------------------------------------------------------------------------- #
@router.get("/reports/catalog")
def report_catalog(project_id: Optional[int] = None, user: m.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    if project_id:
        owned_project(db, user, project_id)
    return {"reports": [
        {"key": "boq", "label": "Bill of Quantities", "formats": ["pdf", "xlsx", "csv", "docx"],
         "description": "Priced BOQ with rate sources and assumptions."},
        {"key": "budget", "label": "Budget & Expenses", "formats": ["pdf", "xlsx", "csv"],
         "description": "Budget position, category split and expense history."},
        {"key": "inventory", "label": "Inventory", "formats": ["pdf", "xlsx"],
         "description": "Stock on site with reorder flags."},
        {"key": "progress", "label": "Project Progress", "formats": ["pdf"],
         "description": "Schedule, critical path and risks."},
        {"key": "summary", "label": "Complete Project Summary", "formats": ["pdf", "xlsx"],
         "description": "One document covering budget, BOQ, schedule and labour."},
    ], "sources": EXPORT_CATEGORIES}


@router.get("/reports/files/{name}")
def report_file(name: str, user: m.User = Depends(current_user)):
    if not re.fullmatch(r"[a-f0-9]{32}\.(pdf|xlsx|csv|docx)", name):
        raise HTTPException(404, "Report not found")
    path = (REPORT_DIR / name).resolve()
    if not str(path).startswith(str(REPORT_DIR.resolve())) or not path.exists():
        raise HTTPException(404, "Report not found")
    media = {"pdf": "application/pdf", "csv": "text/csv", "docx":
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    return FileResponse(path, media_type=media.get(path.suffix.lstrip("."), "application/octet-stream"),
                        filename=f"buildbudget-report{path.suffix}")


@router.get("/search")
def global_search(q: str = Query(min_length=2), user: m.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    like = f"%{q}%"
    project_rows = (db.query(m.Project)
                    .filter(m.Project.owner_id == user.id, m.Project.name.ilike(like))
                    .limit(6).all())
    supplier_rows = (db.query(m.Supplier)
                     .filter(m.Supplier.owner_id == user.id, m.Supplier.name.ilike(like))
                     .limit(4).all())
    doc_rows = (db.query(m.Document)
                .filter(m.Document.owner_id == user.id, m.Document.name.ilike(like),
                        m.Document.active.is_(True)).limit(4).all())
    material_rows = (db.query(m.Material.name, m.Material.category)
                     .filter(m.Material.name.ilike(like)).limit(4).all())
    return {
        "query": q,
        "projects": [{"id": p.id, "name": p.name} for p in project_rows],
        "suppliers": [{"id": s.id, "name": s.name} for s in supplier_rows],
        "documents": [{"id": d.id, "name": d.name} for d in doc_rows],
        "materials": [{"name": n, "category": c} for n, c in material_rows],
    }


# --------------------------------------------------------------------------- #
# settings + meta
# --------------------------------------------------------------------------- #
@router.get("/settings/integrations")
def integrations(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.ai.llm import availability
    scheduler_jobs = []
    try:
        from app.workers import scheduler as sched
        scheduler_jobs = sched.job_summary()
    except Exception:  # noqa: BLE001
        scheduler_jobs = []
    return {
        "ai": availability(),
        "mail": mail.provider_status(),
        "weather": {"provider": "Open-Meteo", "configured": True, "requires_key": False,
                    "note": "Advisory forecast only, not a site-safety determination."},
        "retrieval": rag.stats(db, user.id),
        "scheduler": {"enabled": settings.scheduler_enabled,
                      "in_app": settings.scheduler_in_app,
                      "interval_minutes": settings.check_interval_min,
                      "jobs": scheduler_jobs,
                      "note": ("Run one scheduler process (scripts/run_scheduler.py) in production. "
                               "A sleeping free host cannot guarantee timely alerts.")},
        "database": {"url_scheme": settings.database_url.split(":", 1)[0],
                     "backup_advice": "Back up the SQLite file or use pg_dump for PostgreSQL before upgrades."},
        "demo_mode": settings.demo_mode,
        "version": settings.version,
        "environment": settings.app_env,
    }


@router.post("/settings/test/llm")
def test_llm(user: m.User = Depends(require("settings.manage"))):
    from app.ai.llm import availability, get_chat_model
    status = availability()
    if not status["available"]:
        return {"ok": False, "message": status["reason"]}
    try:
        started = time.time()
        model = get_chat_model()
        reply = model.invoke("Reply with the single word OK.")
        text = reply.content if isinstance(reply.content, str) else str(reply.content)
        return {"ok": True, "message": f"{status['provider']} / {status['model']} responded in "
                                      f"{int((time.time() - started) * 1000)} ms",
                "sample": text[:80]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Provider error: {type(exc).__name__}: {exc}"[:300]}


@router.get("/meta/labels")
def meta_labels():
    return all_labels()


@router.get("/meta")
def meta(user: m.User = Depends(current_user)):
    return {"labels": all_labels(), "version": settings.version, "environment": settings.app_env,
            "currency": settings.currency, "currency_symbol": settings.currency_symbol,
            "timezone": settings.timezone, "units": settings.units,
            "demo_mode": settings.demo_mode,
            "user": serialize.user(user)}


@router.get("/activity")
def activity_log(project_id: Optional[int] = None, action: str = "",
                 limit: int = Query(100, ge=1, le=500), user: m.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    query = db.query(m.ActivityLog)
    if P.effective_role(user.role) != "admin":
        owned_ids = [p.id for p in dashboard.visible_projects(db, user)]
        query = query.filter((m.ActivityLog.user_id == user.id)
                             | (m.ActivityLog.project_id.in_(owned_ids or [-1])))
    if project_id:
        owned_project(db, user, project_id)
        query = query.filter(m.ActivityLog.project_id == project_id)
    if action:
        query = query.filter(m.ActivityLog.action == action)
    rows = query.order_by(m.ActivityLog.id.desc()).limit(limit).all()
    names = {u.id: u.name for u in db.query(m.User).all()}
    projects = {p.id: p.name for p in db.query(m.Project).all()}
    return [{"id": r.id, "action": r.action, "entity": r.entity, "entity_id": r.entity_id,
             "summary": r.summary, "user": names.get(r.user_id, "System"),
             "project": projects.get(r.project_id), "when": r.created_at} for r in rows]
