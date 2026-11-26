"""Email, approval, notification and automation tools.

The assistant can prepare mail and reports, but it can never send an external
email on its own: `draft_*` tools create a draft, `request_email_approval` creates
the approval, and only the human decision calls the provider.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app import models as m
from app.ai.tools_core import ToolContext, ToolRegistry
from app.services import approvals, automation, mail, notifications

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


class Empty(BaseModel):
    pass


class ApprovalStatusIn(BaseModel):
    approval_id: int


class TextIn(BaseModel):
    text: str = Field(description="Pasted quotation text, one line per material")


class DraftIn(BaseModel):
    to: str = Field(description="Recipient email address (never invent one)")
    subject: str
    body: str
    cc: str = ""
    bcc: str = ""
    project_id: Optional[int] = None
    attachments: list[str] = []


class ProjectMailIn(BaseModel):
    purpose: str = Field(description="What the email is for, e.g. budget warning")
    subject: str
    body: str
    to: Optional[str] = Field(None, description="Override recipient; omit to use the project manager")


class DraftRefIn(BaseModel):
    draft_id: int


class ScheduleMailIn(BaseModel):
    draft_id: int
    when: str = Field(description="ISO date-time, e.g. 2026-05-01T09:00")


class SearchMailIn(BaseModel):
    query: str = ""
    folder: str = "sent"


class ReportIn(BaseModel):
    draft_id: int
    report_type: str = Field(description="boq | budget | inventory | progress | excel")
    project_id: Optional[int] = None


class RfqItem(BaseModel):
    material: str
    quantity: float = Field(gt=0)
    unit: str = ""


class RfqIn(BaseModel):
    supplier_id: int
    items: list[RfqItem] = Field(min_length=1)


class AutomationIn(BaseModel):
    name: str
    trigger: str
    project_id: Optional[int] = None
    threshold: Optional[float] = None
    recipients: str = ""
    schedule: str = ""
    require_approval: bool = True


class NotificationIn(BaseModel):
    subject: str
    body: str
    project_id: Optional[int] = None
    priority: str = "normal"


class ApprovalIn(BaseModel):
    draft_id: Optional[int] = None
    note: str = ""


def _valid(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip()))


def register(reg: ToolRegistry) -> None:
    ctx: ToolContext = reg.ctx
    db = ctx.db
    user = ctx.user

    def _draft_out(d: m.EmailDraft, extra: str = "") -> dict:
        return {"draft_id": d.id, "status": d.status, "to": d.to_addr, "cc": d.cc_addr,
                "bcc": d.bcc_addr, "subject": d.subject, "body": d.body_text,
                "attachments": mail.attachments_for(d),
                "provider": d.provider,
                "message": (f"Draft #{d.id} saved. It is NOT sent yet — ask the user to approve it." + extra),
                "summary": f"Email draft #{d.id} prepared"}

    def draft_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "",
                    project_id: Optional[int] = None, attachments: list[str] = ()) -> dict:  # type: ignore[assignment]
        if not _valid(to):
            return {"status": "needs_recipient",
                    "message": "I need a valid recipient email address before I can draft this. "
                               "Ask the user for it — I will not guess an address.",
                    "summary": "Recipient needed"}
        proj_id = project_id or ctx.project_id
        d = mail.draft(db, user, to=to, subject=subject, body=body, cc=cc, bcc=bcc,
                       project_id=proj_id,
                       attachments=[{"name": a, "path": a} for a in attachments])
        return _draft_out(d)

    def draft_project_email(purpose: str, subject: str, body: str,
                            to: Optional[str] = None) -> dict:
        p = ctx.try_project()
        recipient = (to or (p.manager_email if p else "") or "").strip()
        if not recipient:
            return {"status": "needs_recipient",
                    "message": ("I do not have a recipient email for this project. "
                                "Add a project manager email, or tell me the address to use."),
                    "summary": "No project contact email"}
        if not _valid(recipient):
            return {"status": "needs_recipient",
                    "message": f"'{recipient}' is not a valid email address. Please provide a correct one.",
                    "summary": "Invalid recipient"}
        d = mail.draft(db, user, to=recipient, subject=subject, body=body,
                       project_id=p.id if p else None)
        return _draft_out(d, f" Recipient taken from the project contact for '{p.name}'." if p else "")

    def draft_reply(draft_id: int) -> dict:
        d = db.get(m.EmailDraft, draft_id)
        if not d or d.user_id != user.id:
            return {"status": "not_found", "message": "That email was not found.",
                    "summary": "Email not found"}
        return {"status": "ready",
                "original": {"to": d.to_addr, "subject": d.subject, "body": d.body_text},
                "instruction": ("Write a reply with subject 'Re: " + d.subject + "' and create it "
                                "with draft_email, keeping the same recipient."),
                "summary": "Reply context loaded"}

    def request_approval(draft_id: int) -> dict:
        d = db.get(m.EmailDraft, draft_id)
        if not d or d.user_id != user.id:
            return {"status": "not_found", "message": "Draft not found.", "summary": "Draft not found"}
        if d.status == "sent":
            return {"status": "already_sent", "message": "This email was already sent.",
                    "summary": "Already sent"}
        a = approvals.create(db, user, action="send_email", payload={"draft_id": d.id},
                             project_id=d.project_id,
                             title=f"Send email to {d.to_addr or 'no recipient'}",
                             summary=f"Subject: {d.subject}. The email is sent only if you approve.",
                             conversation_id=ctx.conversation_id)
        d.approval_id = a.id
        d.status = "pending_approval"
        db.commit()
        provider = mail.provider_status()
        note = "" if provider["state"] == "ready" else f" Note: {provider['message']}"
        return {"status": "approval_required", "approval_id": a.id, "draft_id": d.id,
                "provider": provider,
                "message": (f"Approval #{a.id} created for this email. It will be sent to "
                            f"{d.to_addr} only after you approve.{note}"),
                "summary": f"Email approval #{a.id} created"}

    def send_approved(draft_id: int) -> dict:
        d = db.get(m.EmailDraft, draft_id)
        if not d or d.user_id != user.id:
            return {"status": "not_found", "message": "Draft not found.", "summary": "Draft not found"}
        if d.sent_at:
            return {"status": "sent", "sent_at": d.sent_at, "message": "This email was already sent.",
                    "summary": "Already sent"}
        a = db.get(m.ApprovalRequest, d.approval_id) if d.approval_id else None
        if not a or a.status != "approved":
            return {"status": "approval_required",
                    "message": ("This email has no approved approval request. Create one with "
                                "request_email_approval; it cannot be sent from the chat directly."),
                    "summary": "Approval required before sending"}
        if a.executed_at:
            return {"status": "sent", "message": "Already executed.", "summary": "Already executed"}
        try:
            r = approvals.execute_approved(db, a, user)
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "message": str(exc), "summary": "Send failed"}
        return {"status": "sent", "result": r, "message": f"Email sent to {d.to_addr}.",
                "summary": f"Email sent to {d.to_addr}"}

    def schedule_mail(draft_id: int, when: str) -> dict:
        d = db.get(m.EmailDraft, draft_id)
        if not d or d.user_id != user.id:
            return {"status": "not_found", "message": "Draft not found.", "summary": "Draft not found"}
        try:
            dt = datetime.fromisoformat(when)
        except ValueError:
            return {"status": "invalid", "message": "Use an ISO date-time such as 2026-05-01T09:00.",
                    "summary": "Invalid schedule time"}
        try:
            mail.schedule(db, d, dt)
        except ValueError as exc:
            return {"status": "invalid", "message": str(exc), "summary": "Invalid schedule time"}
        return {"status": "scheduled", "scheduled_at": d.scheduled_at,
                "message": f"Scheduled for {dt:%d %b %Y %H:%M}. The scheduler process sends it.",
                "summary": "Email scheduled"}

    def search_mail(query: str = "", folder: str = "sent") -> dict:
        folders = {"sent", "drafts", "scheduled", "failed", "pending_approval"}
        folder = folder if folder in folders else "sent"
        rows = mail.folder(db, user.id, folder, q=query)
        return {"folder": folder, "count": len(rows),
                "messages": [{"id": r["id"], "to": r["to"], "subject": r["subject"],
                              "status": r["status"], "sent_at": r["sent_at"],
                              "scheduled_at": r["scheduled_at"]} for r in rows],
                "note": ("Only mail composed in BuildBudget AI is searchable. Inbox sync requires "
                         "Gmail API OAuth, which is not configured."),
                "summary": f"{len(rows)} message(s) in {folder.replace('_', ' ')}"}

    def read_mail(draft_id: int) -> dict:
        d = db.get(m.EmailDraft, draft_id)
        if not d or d.user_id != user.id:
            return {"status": "not_found", "message": "Email not found.", "summary": "Email not found"}
        return {"id": d.id, "to": d.to_addr, "cc": d.cc_addr, "subject": d.subject,
                "body": d.body_text, "status": d.status, "sent_at": d.sent_at,
                "error": d.error, "attachments": mail.attachments_for(d),
                "summary": f"Read email: {d.subject}"}

    def summarize_mail(draft_id: int) -> dict:
        d = db.get(m.EmailDraft, draft_id)
        if not d or d.user_id != user.id:
            return {"status": "not_found", "message": "Email not found.", "summary": "Email not found"}
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", d.body_text or "") if s.strip()]
        summary = " ".join(sentences[:3])[:400] or "The message body is empty."
        return {"id": d.id, "subject": d.subject, "summary_text": summary,
                "sentences": len(sentences), "status": d.status,
                "note": "Extractive summary (first sentences). No model summarisation is applied here.",
                "summary": summary[:200]}

    def attach_report(draft_id: int, report_type: str, project_id: Optional[int] = None) -> dict:
        from app.ai.tools_ops import _save, project_pack
        from app.services import reporting
        d = db.get(m.EmailDraft, draft_id)
        if not d or d.user_id != user.id:
            return {"status": "not_found", "message": "Draft not found.", "summary": "Draft not found"}
        p = db.get(m.Project, project_id or d.project_id or ctx.project_id or 0)
        if not p or (p.owner_id != user.id and user.role != "admin"):
            return {"status": "no_project", "message": "Choose a project to attach a report.",
                    "summary": "Project required"}
        summary, items, exps, plan, lab = project_pack(db, p)
        mapping = {
            "boq": ("pdf", lambda: reporting.boq_pdf(p.name, items, summary)),
            "budget": ("pdf", lambda: reporting.budget_pdf(p, summary, exps, items)),
            "inventory": ("pdf", lambda: reporting.inventory_pdf(
                p.name, [{"material": i.material_name, "available": i.available, "unit": i.unit,
                          "reserved": i.reserved, "reorder_level": i.reorder_level,
                          "location": i.location,
                          "low": i.reorder_level > 0 and i.available <= i.reorder_level}
                         for i in db.query(m.InventoryItem).filter_by(project_id=p.id)])),
            "progress": ("pdf", lambda: reporting.progress_pdf(
                p, summary, plan, ["Generated for email attachment."])),
            "excel": ("xlsx", lambda: reporting.summary_xlsx(p.name, summary, items, exps, {})),
        }
        key = (report_type or "").lower()
        if key not in mapping:
            return {"status": "invalid", "message": f"report_type must be one of {sorted(mapping)}",
                    "summary": "Unknown report type"}
        ext, builder = mapping[key]
        saved = _save(builder(), ext, f"{key} report for {p.name}")
        atts = mail.attachments_for(d)
        atts.append({"name": f"{key}_{p.name[:40].replace(' ', '_')}.{ext}",
                     "path": f"reports/generated/{saved['file']}"})
        d.attachments_json = json.dumps(atts)
        db.commit()
        return {"status": "attached", "draft_id": d.id, "attachment": atts[-1],
                "message": f"Attached the {key} report to draft #{d.id}.",
                "summary": f"{key} report attached"}

    def email_status(draft_id: Optional[int] = None) -> dict:
        if draft_id:
            d = db.get(m.EmailDraft, draft_id)
            if not d or d.user_id != user.id:
                return {"status": "not_found", "message": "Draft not found.", "summary": "Not found"}
            return {"id": d.id, "status": d.status, "sent_at": d.sent_at, "error": d.error,
                    "provider": d.provider,
                    "delivery": ("Provider accepted the message at " + str(d.sent_at)
                                 if d.sent_at else "Not delivered"), 
                    "note": "Provider acceptance is not proof of inbox delivery.",
                    "summary": f"Email status: {d.status}"}
        return {"provider": mail.provider_status(), "counts": mail.counts(db, user.id),
                "summary": "Mail provider status"}

    def rfq(supplier_id: int, items: list[RfqItem]) -> dict:
        s = db.get(m.Supplier, supplier_id)
        if not s or s.owner_id != user.id:
            return {"status": "not_found", "message": "Supplier not found.", "summary": "Supplier not found"}
        if not s.email or not _valid(s.email):
            return {"status": "needs_recipient",
                    "message": f"Supplier '{s.name}' has no valid email address on file.",
                    "summary": "Supplier email missing"}
        p = ctx.try_project()
        subject, body = mail.render_template("rfq", {
            "supplier_name": s.name, "project": p.name if p else "an upcoming project",
            "items": [{"material": i.material, "quantity": i.quantity, "unit": i.unit} for i in items],
            "location": p.location if p else "", "sender_name": user.name,
        })
        d = mail.draft(db, user, to=s.email, subject=subject, body=body,
                       project_id=p.id if p else None, supplier_id=s.id)
        return _draft_out(d, " Quantities come from your BOQ and estimator results.")

    def create_automation(name: str, trigger: str, project_id: Optional[int] = None,
                          threshold: Optional[float] = None, recipients: str = "",
                          schedule: str = "", require_approval: bool = True) -> dict:
        if trigger not in automation.SUPPORTED:
            return {"status": "invalid",
                    "message": f"Unsupported trigger. Use one of: {', '.join(sorted(automation.SUPPORTED))}",
                    "summary": "Unsupported trigger"}
        a = approvals.create(
            db, user, action="create_automation",
            payload={"name": name, "trigger": trigger, "threshold": threshold,
                     "recipients": recipients, "schedule": schedule,
                     "require_approval": require_approval, "template": "project_summary",
                     "timezone": user.timezone},
            project_id=project_id or ctx.project_id,
            title=f"Enable automation: {name}",
            summary=(f"Trigger: {trigger.replace('_', ' ')}. Recipients: {recipients or 'in-app only'}. "
                     f"Approval required before any email: {'yes' if require_approval else 'no'}."),
            conversation_id=ctx.conversation_id)
        return {"status": "approval_required", "approval_id": a.id,
                "message": f"Approval #{a.id} created. The rule starts only after you approve.",
                "summary": f"Automation approval #{a.id} created"}

    def list_rules() -> dict:
        rules = db.query(m.AutomationRule).filter_by(user_id=user.id).all()
        return {"count": len(rules), "rules": [automation.serialize(r) for r in rules],
                "summary": f"{len(rules)} automation rule(s)"}

    def pending_approvals() -> dict:
        rows = approvals.pending_for(db, user)
        return {"count": len(rows), "approvals": [approvals.serialize(a) for a in rows],
                "summary": f"{len(rows)} approval(s) waiting"}

    def approval_status(approval_id: int) -> dict:
        a = db.get(m.ApprovalRequest, approval_id)
        if not a or a.user_id != user.id:
            return {"status": "not_found", "message": "Approval not found.", "summary": "Not found"}
        return {**approvals.serialize(a), "summary": f"Approval #{a.id}: {a.status}"}

    def create_approval(draft_id: Optional[int] = None, note: str = "") -> dict:
        if draft_id:
            return request_approval(draft_id)
        return {"status": "needs_input",
                "message": "Tell me what should be approved (for example an email draft).",
                "summary": "Nothing to approve"}

    def notification_history() -> dict:
        rows = notifications.list_for(db, user.id, limit=30)
        return {"count": len(rows), "notifications": [notifications.serialize(n) for n in rows],
                "summary": f"{len(rows)} notification(s)"}

    def create_notification(subject: str, body: str, project_id: Optional[int] = None,
                            priority: str = "normal") -> dict:
        n = notifications.create_inapp(db, user.id, subject=subject, body=body, kind="system",
                                       project_id=project_id or ctx.project_id, priority=priority,
                                       link="/notifications")
        return {"id": n.id, "status": "recorded",
                "message": "Notification added to the Notification Centre.",
                "summary": f"Notification created: {subject}"}

    def extract_quotation(text: str) -> dict:
        """Parse a pasted quotation table. Nothing is stored; the user must confirm."""
        rows, errors = [], []
        for idx, line in enumerate((text or "").splitlines(), 1):
            if not line.strip():
                continue
            parts = [p.strip() for p in re.split(r"[,\t|]", line)]
            if len(parts) < 3:
                errors.append(f"line {idx}: expected material, unit, unit price")
                continue
            try:
                price = float(re.sub(r"[^0-9.]", "", parts[2]))
            except ValueError:
                errors.append(f"line {idx}: unit price is not a number")
                continue
            rows.append({"material": parts[0], "unit": parts[1], "unit_price": price,
                         "tax_pct": 18.0, "note": "Tax percentage not in the text — confirm it"})
        if not rows:
            return {"status": "unparsed", "errors": errors,
                    "message": ("I could not read a quotation table from that text. Paste lines like "
                                "'Cement OPC, bag, 390'. Nothing has been saved."),
                    "summary": "Quotation not parsed"}
        return {"status": "needs_confirmation", "rows": rows, "errors": errors,
                "message": ("These rows are a draft parsed from your text and are NOT saved. "
                            "Confirm with the user, then add them as supplier quotations."),
                "summary": f"{len(rows)} quotation line(s) parsed (not saved)"}

    reg.add("draft_email", "Create an email draft. Never sends; recipient must be valid.", DraftIn,
            draft_email, write=True, capability="mail.send")
    reg.add("draft_project_email", "Draft an email to the project's manager contact.", ProjectMailIn,
            draft_project_email, write=True, capability="mail.send")
    reg.add("draft_email_reply", "Load an existing email so you can write a reply draft.", DraftRefIn,
            draft_reply)
    reg.add("request_email_approval", "Create the approval request required to send a draft.",
            DraftRefIn, request_approval, write=True, capability="mail.send")
    reg.add("send_approved_email", "Send a draft that already has an approved approval request.",
            DraftRefIn, send_approved, write=True, capability="mail.send")
    reg.add("schedule_email", "Schedule an email draft for later delivery.", ScheduleMailIn,
            schedule_mail, write=True, capability="mail.send")
    reg.add("search_emails", "Search mail composed in BuildBudget AI (no inbox sync).", SearchMailIn,
            search_mail)
    reg.add("read_email", "Read one email draft or sent message.", DraftRefIn, read_mail)
    reg.add("summarize_email", "Extractive summary of an email body.", DraftRefIn, summarize_mail)
    reg.add("attach_project_report", "Generate a report and attach it to an email draft.", ReportIn,
            attach_report, write=True, capability="mail.send")
    reg.add("get_email_status", "Delivery state of one draft, or provider status.", Empty,
            email_status)
    reg.add("draft_supplier_rfq", "Draft a request for quotation to a supplier.", RfqIn, rfq,
            write=True, capability="mail.send")
    reg.add("create_email_automation", "Propose an automation rule (needs approval).", AutomationIn,
            create_automation, write=True, capability="automation.manage")
    reg.add("list_automation_rules", "List automation rules and their last runs.", Empty, list_rules)
    reg.add("list_pending_approvals", "Approvals waiting for the user.", Empty, pending_approvals)
    reg.add("get_approval_status", "Status of one approval request.", ApprovalStatusIn,
            approval_status)
    reg.add("get_notification_history", "Recent notifications for the user.", Empty, notification_history)
    reg.add("create_notification", "Record an in-app notification.", NotificationIn, create_notification)
    reg.add("extract_supplier_quotation", "Parse a pasted supplier quotation (never saves it).",
            TextIn, extract_quotation)
