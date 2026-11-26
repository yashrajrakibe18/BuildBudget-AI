"""AI-written email drafts for the Mail Centre.

The model only chooses the wording. Every number in the message comes from the
database, the recipient is typed by the person (never invented here), and nothing is
sent: the result fills the normal compose form, which still needs a human approval.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app import models as m
from app.ai.llm import availability, get_chat_model
from app.services import budget as budget_svc
from app.services import inventory as inventory_svc

TONES = ("professional", "friendly", "firm", "concise", "follow_up")

PURPOSE_LIMIT = 1200


class MailAiError(RuntimeError):
    """Raised when the assistant cannot write the mail (not configured, bad reply)."""


_SYSTEM = (
    "You write plain-text emails for a construction project team.\n"
    "Rules you must follow:\n"
    "1. Use ONLY the facts given in FACTS for any number, name, date or status. Never invent a "
    "price, quantity, supplier, deadline, commitment or promise.\n"
    "2. Never invent an email address and never write a placeholder such as [Name], [Company] or "
    "<date>. If a detail is missing, word around it.\n"
    "3. Plain text only: no Markdown, no bullets with symbols, no HTML, no signature block with "
    "links. Short paragraphs separated by a blank line.\n"
    "4. Greet with 'Hello,' unless the recipient's name is known. End with 'Regards,' and the "
    "sender's name on the next line.\n"
    "5. 90 to 160 words. State the point in the first sentence and finish with one clear ask "
    "or next step.\n"
    "6. If FACTS show a budget or stock problem, say it plainly without alarming language and "
    "without claiming anything has already been done.\n"
    "Reply with a single JSON object and nothing else: "
    '{"subject": "...", "body": "..."}. Use \\n for line breaks inside body.'
)


def _json_object(text: str) -> dict:
    if not isinstance(text, str):
        text = str(text)
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = fenced.group(1) if fenced else None
    if raw is None:
        match = re.search(r"\{.*\}", text, re.S)
        raw = match.group(0) if match else None
    if raw is None:
        raise MailAiError("The model did not return an email draft. Try again.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MailAiError("The model returned an unreadable draft. Try again.") from exc


def project_facts(db: Session, project: m.Project) -> dict:
    """Verified facts the model is allowed to use. Nothing here is guessed."""
    s = budget_svc.summary(db, project)
    low = inventory_svc.low_stock(db, project_id=project.id, owner_id=project.owner_id)
    tasks = db.query(m.Task).filter_by(project_id=project.id).all()
    open_tasks = [t for t in tasks if t.progress < 100]
    overdue = [t.name for t in open_tasks
               if t.start_date and t.start_date + timedelta(days=t.duration_days) < date.today()]
    return {
        "project": {
            "name": project.name, "type": project.project_type, "status": project.status,
            "location": project.location,
            "start_date": str(project.start_date) if project.start_date else None,
            "end_date": str(project.end_date) if project.end_date else None,
            "manager_name": project.manager_name or None,
        },
        "budget": {
            "approved": s["approved_budget"], "estimated_cost": s["estimated_cost"],
            "spent": s["actual_expenses"], "remaining": s["remaining_budget"],
            "used_pct": s["utilization_pct"], "status": s["status"],
        },
        "low_stock": [{"material": i.material_name, "available": i.available, "unit": i.unit,
                       "reorder_level": i.reorder_level} for i, _ in low[:6]],
        "tasks": {"open": len(open_tasks), "total": len(tasks), "overdue": overdue[:5]},
    }


def compose(db: Session, user: m.User, *, purpose: str, project: Optional[m.Project] = None,
            tone: str = "professional", recipient: str = "", subject_hint: str = "") -> dict:
    """Ask the configured model to word an email from real project facts."""
    brief = (purpose or "").strip()
    if not brief:
        raise MailAiError("Say what the email should be about first.")
    if len(brief) > PURPOSE_LIMIT:
        raise MailAiError(f"Keep the instructions under {PURPOSE_LIMIT} characters.")
    tone = (tone or "professional").lower()
    if tone not in TONES:
        tone = "professional"

    status = availability()
    if not status["available"]:
        raise MailAiError(f"The AI writer is unavailable. {status['reason']}")

    facts: dict = {"sender": {"name": user.name or user.email}}
    if project is not None:
        facts.update(project_facts(db, project))
    if recipient:
        facts["recipient_email"] = recipient.strip()
    if subject_hint:
        facts["requested_subject"] = subject_hint.strip()

    request = (
        f"FACTS (verified, the only numbers you may use):\n{json.dumps(facts, indent=1, default=str)}\n\n"
        f"Write the email in a {tone} tone.\n"
        f"What the email must achieve: {brief}"
    )
    try:
        llm = get_chat_model(temperature=0.4)
        reply = llm.invoke([SystemMessage(content=_SYSTEM), HumanMessage(content=request)])
    except Exception as exc:  # noqa: BLE001 - provider errors must not leak raw text
        raise MailAiError("The AI writer could not be reached just now. Try again.") from exc

    content = reply.content if isinstance(reply.content, str) else str(reply.content)
    data = _json_object(content)
    subject = str(data.get("subject") or "").strip() or (subject_hint or "").strip()
    body = str(data.get("body") or "").strip()
    if not subject:
        raise MailAiError("The model did not propose a subject. Try again or type one yourself.")
    if not body:
        raise MailAiError("The model returned an empty message. Try again.")
    return {"subject": subject[:200], "body": body[:8000], "tone": tone,
            "model": status.get("model"), "provider": status.get("provider"),
            "used_project": project.name if project is not None else None}
