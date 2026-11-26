"""Outgoing mail: drafts, approval gating, scheduled send and delivery reporting.

Providers:
* `smtp`  — implemented and used for all sends.
* `gmail_api` — configuration is detected, but full-mailbox sync is NOT
  implemented. It is reported as unavailable instead of showing a fake inbox.

Nothing is ever sent by the model directly: `draft()` creates a draft, the
approval service calls `send_approved()` exactly once.
"""
from __future__ import annotations

import base64
import json
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app import models as m
from app.core.config import settings
from app.core.security import random_idempotency_key
from app.services import activity

READY, DISABLED, NOT_CONFIGURED = "ready", "disabled", "not_configured"


class MailError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #
class SMTPProvider:
    name = "smtp"

    def available(self) -> tuple[bool, str]:
        blocked = _master_switch("SMTP sending")
        if blocked:
            return blocked
        if not (settings.smtp_username and settings.smtp_password):
            return False, "SMTP credentials are not configured (SMTP_USERNAME / SMTP_PASSWORD app password)."
        return True, ""

    def send(self, msg: EmailMessage) -> str:  # returns provider message id
        if not msg["From"]:
            msg["From"] = settings.smtp_from or settings.smtp_username
        context = ssl.create_default_context()
        use_ssl = settings.smtp_use_ssl or settings.smtp_port == 465
        if use_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                  context=context, timeout=25) as s:
                if settings.smtp_username:
                    s.login(settings.smtp_username, settings.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=25) as s:
                if settings.smtp_use_tls:
                    s.starttls(context=context)
                if settings.smtp_username:
                    s.login(settings.smtp_username, settings.smtp_password)
                s.send_message(msg)
        return msg.get("Message-ID", "")


class GmailAPIProvider:
    """Send-only Gmail API provider using OAuth 2.0 refresh tokens.

    Full mailbox synchronisation is still not implemented; only outgoing send
    is supported, so the application never pretends to have an inbox.
    """

    name = "gmail_api"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

    def available(self) -> tuple[bool, str]:
        blocked = _master_switch("Gmail API sending")
        if blocked:
            return blocked
        if not (settings.gmail_client_id and settings.gmail_client_secret and settings.gmail_refresh_token):
            return False, ("Gmail API is not configured. Set GMAIL_CLIENT_ID, "
                           "GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN. "
                           "Mailbox synchronisation is not implemented.")
        return True, "Gmail API sending is configured. Mailbox synchronisation is not implemented."

    def _access_token(self) -> str:
        try:
            resp = httpx.post(self.TOKEN_URL, data={
                "client_id": settings.gmail_client_id,
                "client_secret": settings.gmail_client_secret,
                "refresh_token": settings.gmail_refresh_token,
                "grant_type": "refresh_token",
            }, timeout=20)
            resp.raise_for_status()
            token = resp.json().get("access_token")
            if not token:
                raise MailError("Gmail did not return an access token.")
            return token
        except httpx.HTTPError as exc:
            raise MailError(f"Gmail OAuth token refresh failed: {type(exc).__name__}: {exc}"[:300]) from exc

    def send(self, msg: EmailMessage) -> str:
        token = self._access_token()
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii").rstrip("=")
        try:
            resp = httpx.post(self.SEND_URL, headers={"Authorization": f"Bearer {token}"},
                              json={"raw": raw}, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            detail = ""
            if getattr(exc, "response", None) is not None:
                try:
                    detail = exc.response.text[:300]
                except Exception:  # noqa: BLE001
                    detail = ""
            raise MailError(f"Gmail API rejected the message: {type(exc).__name__}: {exc} {detail}".strip()[:500]) from exc
        return resp.json().get("id", msg.get("Message-ID", ""))


class LocalOutboxProvider:
    """Development provider that captures mail to a local folder instead of delivering it."""

    name = "local"

    def available(self) -> tuple[bool, str]:
        blocked = _master_switch("local capture")
        if blocked:
            return blocked
        return True, ("Local capture mode: emails are written to the local outbox and are "
                      "NOT delivered to any recipient. Use SMTP or Gmail API for real delivery.")

    def send(self, msg: EmailMessage) -> str:
        outbox = Path(".run") / "mailbox"
        outbox.mkdir(parents=True, exist_ok=True)
        message_id = msg.get("Message-ID") or make_msgid(domain="buildbudget.local")
        if not msg.get("Message-ID"):
            msg["Message-ID"] = message_id
        filename = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_{random_idempotency_key('mail')}.eml"
        (outbox / filename).write_bytes(msg.as_bytes())
        return message_id


def _master_switch(action: str) -> tuple[bool, str] | None:
    """EMAIL_ENABLED is the master switch for every provider, capture included."""
    if settings.email_enabled:
        return None
    return False, (f"Email sending is disabled (EMAIL_ENABLED=false), so {action} is not available. "
                   "The draft is saved safely. Set EMAIL_ENABLED=true to enable the configured provider.")


def get_provider():
    provider = (settings.mail_provider or "smtp").lower()
    if provider == "gmail_api":
        return GmailAPIProvider()
    if provider in ("local", "outbox", "capture"):
        return LocalOutboxProvider()
    return SMTPProvider()


def provider_status() -> dict:
    p = get_provider()
    ok, why = p.available()
    return {
        "provider": p.name,
        "state": READY if ok else (DISABLED if not settings.email_enabled else NOT_CONFIGURED),
        "message": why,
        "from_address": settings.smtp_from or settings.smtp_username,
        "inbox_sync": False,
        "gmail_oauth": settings.mail_status()["gmail_oauth_configured"],
    }


def test_connection() -> dict:
    """Provider connection test (no email is sent)."""
    provider = get_provider()
    if isinstance(provider, LocalOutboxProvider):
        return {"ok": True, "message": provider.available()[1]}
    if isinstance(provider, GmailAPIProvider):
        ok, why = provider.available()
        if not ok:
            return {"ok": False, "message": why}
        try:
            token = provider._access_token()
            return {"ok": True, "message": f"Gmail API OAuth token refresh succeeded ({token[:8]}…)."}
        except MailError as exc:
            return {"ok": False, "message": str(exc)}
    ok, why = SMTPProvider().available()
    if not ok:
        return {"ok": False, "message": why}
    try:
        use_ssl = settings.smtp_use_ssl or settings.smtp_port == 465
        if use_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                  context=ssl.create_default_context(), timeout=15) as s:
                if settings.smtp_username:
                    s.login(settings.smtp_username, settings.smtp_password)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
                if settings.smtp_use_tls:
                    s.starttls(context=ssl.create_default_context())
                if settings.smtp_username:
                    s.login(settings.smtp_username, settings.smtp_password)
        return {"ok": True, "message": f"Connected to {settings.smtp_host}:{settings.smtp_port} and authenticated."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"SMTP connection failed: {type(exc).__name__}: {exc}"[:300]}


# --------------------------------------------------------------------------- #
# drafts
# --------------------------------------------------------------------------- #
def draft(db: Session, user: m.User, *, to: str, subject: str, body: str,
          cc: str = "", bcc: str = "", project_id: int | None = None,
          supplier_id: int | None = None, attachments: list[dict] | None = None,
          existing: m.EmailDraft | None = None) -> m.EmailDraft:
    d = existing or m.EmailDraft(user_id=user.id, idempotency_key=random_idempotency_key("mail"))
    d.to_addr = (to or "").strip()
    d.cc_addr = (cc or "").strip()
    d.bcc_addr = (bcc or "").strip()
    d.subject = (subject or "").strip()
    d.body_text = body or ""
    d.project_id = project_id
    d.supplier_id = supplier_id
    d.attachments_json = json.dumps(attachments or [])
    d.provider = settings.mail_provider
    d.status = "draft"
    d.updated_at = m.now()
    if existing is None:
        db.add(d)
    db.commit()
    return d


def update(db: Session, d: m.EmailDraft, **fields) -> m.EmailDraft:
    for key in ("to_addr", "cc_addr", "bcc_addr", "subject", "body_text"):
        if key in fields and fields[key] is not None:
            setattr(d, key, fields[key])
    if "attachments" in fields and fields["attachments"] is not None:
        d.attachments_json = json.dumps(fields["attachments"])
    d.updated_at = m.now()
    db.commit()
    return d


def schedule(db: Session, d: m.EmailDraft, when: datetime) -> m.EmailDraft:
    if when <= m.now():
        raise ValueError("Scheduled time must be in the future")
    d.scheduled_at = when
    d.status = "scheduled"
    db.commit()
    return d


def attachments_for(d: m.EmailDraft) -> list[dict]:
    try:
        return json.loads(d.attachments_json or "[]")
    except json.JSONDecodeError:
        return []


def _build_message(d: m.EmailDraft) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = d.subject
    msg["To"] = d.to_addr
    if d.cc_addr:
        msg["Cc"] = d.cc_addr
    if d.bcc_addr:
        msg["Bcc"] = d.bcc_addr
    msg["From"] = settings.smtp_from or settings.smtp_username
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to
    msg["Message-ID"] = make_msgid(domain="buildbudget.local")
    msg["X-BuildBudget-Draft"] = str(d.id)
    msg.set_content(d.body_text or "")
    for att in attachments_for(d):
        path = att.get("path")
        if not path:
            continue
        try:
            with open(path, "rb") as fh:
                msg.add_attachment(fh.read(), maintype="application", subtype="octet-stream",
                                   filename=att.get("name") or "attachment")
        except OSError:
            continue
    return msg


def send_approved(db: Session, d: m.EmailDraft) -> m.EmailDraft:
    """Send exactly once. Raises MailError with a human-readable reason."""
    if d.sent_at is not None:
        return d                                     # idempotent: already delivered
    if d.status in ("sent", "sending"):
        return d
    if not d.to_addr:
        raise MailError("This draft has no recipient. Add one before sending.")
    provider = get_provider()
    ok, why = provider.available()
    if not ok:
        d.status, d.error = "failed", why
        db.commit()
        raise MailError(why)
    d.status = "sending"
    db.commit()
    try:
        message_id = provider.send(_build_message(d))
    except Exception as exc:  # noqa: BLE001
        d.status = "failed"
        d.error = f"{type(exc).__name__}: {exc}"[:500]
        db.commit()
        activity.log(db, user_id=d.user_id, action="email_failed", project_id=d.project_id,
                     entity="email", entity_id=d.id, summary=d.subject)
        db.commit()
        raise MailError(f"The email provider rejected the message: {d.error}") from exc
    d.status = "sent"
    d.sent_at = m.now()
    d.message_id = message_id or ""
    d.error = ""
    activity.log(db, user_id=d.user_id, action="email_sent", project_id=d.project_id,
                 entity="email", entity_id=d.id, summary=f"Sent to {d.to_addr}: {d.subject}")
    db.commit()
    return d


def send_due(db: Session, now: datetime | None = None) -> list[m.EmailDraft]:
    now = now or m.now()
    due = (db.query(m.EmailDraft)
           .filter(m.EmailDraft.status == "scheduled", m.EmailDraft.scheduled_at <= now).all())
    sent = []
    for d in due:
        try:
            sent.append(send_approved(db, d))
        except MailError:
            continue
    return sent


def folder(db: Session, user_id: int, name: str, q: str = "", project_id: int | None = None):
    query = db.query(m.EmailDraft).filter(m.EmailDraft.user_id == user_id)
    if name == "drafts":
        query = query.filter(m.EmailDraft.status == "draft")
    elif name == "pending_approval":
        query = query.filter(m.EmailDraft.status == "pending_approval")
    elif name == "scheduled":
        query = query.filter(m.EmailDraft.status == "scheduled")
    elif name == "failed":
        query = query.filter(m.EmailDraft.status == "failed")
    else:
        query = query.filter(m.EmailDraft.status == "sent")
    if project_id:
        query = query.filter(m.EmailDraft.project_id == project_id)
    if q:
        like = f"%{q}%"
        query = query.filter((m.EmailDraft.subject.ilike(like)) | (m.EmailDraft.to_addr.ilike(like))
                             | (m.EmailDraft.body_text.ilike(like)))
    rows = query.order_by(m.EmailDraft.updated_at.desc()).limit(200).all()
    prefix = "Sent" if name == "sent" else "Draft"
    return [{
        "id": d.id, "to": d.to_addr, "cc": d.cc_addr, "bcc": d.bcc_addr,
        "subject": d.subject or f"({prefix} with no subject)", "body": d.body_text,
        "status": d.status, "project_id": d.project_id, "supplier_id": d.supplier_id,
        "attachments": attachments_for(d), "scheduled_at": d.scheduled_at,
        "sent_at": d.sent_at, "error": d.error, "updated_at": d.updated_at,
        "approval_id": d.approval_id, "provider": d.provider,
    } for d in rows]


def counts(db: Session, user_id: int) -> dict:
    out = {}
    for name in ("drafts", "pending_approval", "scheduled", "sent", "failed"):
        status = {"drafts": "draft"}.get(name, name)
        out[name] = db.query(m.EmailDraft).filter_by(user_id=user_id, status=status).count()
    return out


# --------------------------------------------------------------------------- #
# templates
# --------------------------------------------------------------------------- #
def render_template(name: str, ctx: dict) -> tuple[str, str]:
    """Plain-text templates. No HTML email is generated, so nothing to sanitise."""
    project = ctx.get("project", "the project")
    if name == "budget_warning":
        subject = f"Action needed: {project} is at {ctx.get('utilization', '—')}% of budget"
        body = (
            f"Hello {ctx.get('recipient_name') or 'there'},\n\n"
            f"This is a budget status notification for {project}.\n\n"
            f"Approved budget : {ctx.get('budget', '—')}\n"
            f"Actual expenses : {ctx.get('actual', '—')}\n"
            f"Remaining       : {ctx.get('remaining', '—')}\n"
            f"Utilisation     : {ctx.get('utilization', '—')}%\n\n"
            f"{ctx.get('advice', 'Please review open commitments before approving new spend.')}\n\n"
            "Figures come from recorded expenses and the current BOQ revision. "
            "This is a preliminary planning estimate, not an audited statement.\n\n"
            "Regards,\nBuildBudget AI"
        )
        return subject, body
    if name == "rfq":
        lines = "\n".join(f"  - {i['material']}: {i['quantity']} {i['unit']}" for i in ctx.get("items", []))
        subject = f"Request for quotation — {project}"
        body = (
            f"Dear {ctx.get('supplier_name') or 'Sir/Madam'},\n\n"
            f"We are requesting a quotation for the following materials for {project}.\n\n"
            f"{lines or '  (items to be confirmed)'}\n\n"
            f"Please include unit price, applicable tax, delivery charge, minimum order quantity, "
            f"lead time and quotation validity.\n\n"
            f"Delivery location: {ctx.get('location') or 'to be confirmed'}\n\n"
            "Regards,\n" + (ctx.get("sender_name") or "BuildBudget AI")
        )
        return subject, body
    subject = f"Project update — {project}"
    body = (
        f"Hello {ctx.get('recipient_name') or 'there'},\n\n"
        f"Here is the current status of {project}.\n\n"
        f"Status          : {ctx.get('status', '—')}\n"
        f"Progress        : {ctx.get('progress', '—')}%\n"
        f"Budget          : {ctx.get('budget', '—')}\n"
        f"Spent           : {ctx.get('actual', '—')}\n"
        f"Open tasks      : {ctx.get('open_tasks', '—')}\n\n"
        f"{ctx.get('notes', '')}\n\n"
        "Regards,\nBuildBudget AI"
    )
    return subject, body
