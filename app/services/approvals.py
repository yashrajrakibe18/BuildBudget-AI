"""Human-in-the-loop approvals.

Approval state is always read from the database. Nothing sensitive executes until
an authorised human approves it, and an approved action executes exactly once
(`executed_at` is the idempotency guard).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.core import permissions as P
from app.services import activity, mail

TTL_HOURS = 72


class ApprovalError(RuntimeError):
    pass


def _dumps(obj) -> str:
    return json.dumps(obj, default=str)


def create(db: Session, user: m.User, *, action: str, payload: dict, project_id: int | None = None,
           title: str = "", summary: str = "", before: dict | None = None,
           conversation_id: int | None = None) -> m.ApprovalRequest:
    a = m.ApprovalRequest(
        user_id=user.id, project_id=project_id, conversation_id=conversation_id,
        action=action, title=(title or action.replace("_", " ").title())[:200],
        summary=summary[:2000], payload=_dumps(payload), before_state=_dumps(before or {}),
        status="pending", expires_at=m.now() + timedelta(hours=TTL_HOURS),
    )
    db.add(a)
    activity.log(db, user_id=user.id, action="approval_requested", project_id=project_id,
                 entity="approval", summary=a.title)
    db.commit()
    return a


def pending_for(db: Session, user: m.User, project_id: int | None = None):
    q = db.query(m.ApprovalRequest).filter(m.ApprovalRequest.status == "pending",
                                           m.ApprovalRequest.user_id == user.id)
    if project_id:
        q = q.filter(m.ApprovalRequest.project_id == project_id)
    return q.order_by(m.ApprovalRequest.id.desc()).all()


def decide(db: Session, approval: m.ApprovalRequest, actor: m.User, approve: bool) -> dict:
    if approval.user_id != actor.id and P.effective_role(actor.role) != "admin":
        raise ApprovalError("This approval request belongs to another user")
    if not P.can(actor, "approval.decide"):
        raise ApprovalError("Your role cannot decide approvals")
    if approval.status != "pending":
        raise ApprovalError(f"This request was already {approval.status}")
    if approval.expires_at and approval.expires_at < m.now():
        approval.status = "expired"
        db.commit()
        raise ApprovalError("This approval request has expired; ask the assistant to create a new one")

    approval.decided_at = m.now()
    if not approve:
        approval.status = "rejected"
        activity.log(db, user_id=actor.id, action="approval_rejected", project_id=approval.project_id,
                     entity="approval", entity_id=approval.id, summary=approval.title)
        db.commit()
        return {"status": "rejected", "approval_id": approval.id, "message": "Rejected — nothing was executed."}

    # Reserve the decision first so a double-click cannot execute twice.
    approval.status = "approved"
    db.commit()

    if approval.executed_at is not None:
        return {"status": "approved", "approval_id": approval.id, "message": "Already executed earlier."}

    try:
        result = _execute(db, approval, actor)
        approval.executed_at = m.now()
        approval.execution_error = ""
        activity.log(db, user_id=actor.id, action="approval_executed", project_id=approval.project_id,
                     entity="approval", entity_id=approval.id, summary=result.get("message", ""))
        db.commit()
        return {"status": "approved", "approval_id": approval.id, "executed": True, **result}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        approval = db.get(m.ApprovalRequest, approval.id)
        approval.execution_error = f"{type(exc).__name__}: {exc}"[:500]
        db.commit()
        return {"status": "approved", "approval_id": approval.id, "executed": False,
                "message": f"Approved, but execution failed: {approval.execution_error}"}


def _payload(approval: m.ApprovalRequest) -> dict:
    try:
        return json.loads(approval.payload or "{}")
    except json.JSONDecodeError:
        return {}


def _execute(db: Session, a: m.ApprovalRequest, actor: m.User) -> dict:
    p = _payload(a)
    if a.action == "record_expense":
        e = m.Expense(project_id=a.project_id, created_by=actor.id, category=p["category"],
                      amount=Decimal(str(p["amount"])), description=p.get("description", ""),
                      vendor=p.get("vendor", ""), invoice_no=p.get("invoice_no") or None,
                      expense_date=p.get("expense_date") or None, created_at=m.now())
        db.add(e)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ApprovalError("A duplicate invoice already exists for this vendor — nothing was recorded") from None
        return {"message": f"Expense of {p['amount']} recorded", "entity_id": e.id}

    if a.action == "create_project":
        proj = m.Project(owner_id=actor.id, currency=p.get("currency", "INR"),
                         status=p.get("status", "planning"), **{k: v for k, v in p.items()
                         if k not in ("currency", "status", "id", "owner_id")})
        db.add(proj)
        db.commit()
        return {"message": f"Project '{proj.name}' created", "entity_id": proj.id}

    if a.action == "update_project":
        proj = db.get(m.Project, a.project_id)
        if not proj:
            raise ApprovalError("Project no longer exists")
        for k, v in p.items():
            if hasattr(proj, k) and k not in ("id", "owner_id"):
                setattr(proj, k, v)
        proj.updated_at = m.now()
        db.commit()
        return {"message": f"Project '{proj.name}' updated"}

    if a.action == "approve_boq":
        from sqlalchemy import func
        rev = p.get("revision") or db.query(func.max(m.BOQItem.revision)).filter_by(
            project_id=a.project_id).scalar() or 1
        n = db.query(m.BOQItem).filter_by(project_id=a.project_id, revision=rev).update(
            {"approval_status": "approved"})
        db.commit()
        return {"message": f"BOQ revision {rev} approved ({n} items)"}

    if a.action == "create_purchase_order":
        from app.services import procurement
        po = procurement.create_po(db, a.project_id, actor.id, p.get("items", []),
                                   supplier_id=p.get("supplier_id"),
                                   expected_date=p.get("expected_date"), notes=p.get("notes", ""))
        return {"message": f"Draft purchase order #{po.id} created", "entity_id": po.id}

    if a.action == "add_boq_items":
        from sqlalchemy import func
        project = db.get(m.Project, a.project_id)
        if not project:
            raise ApprovalError("Project no longer exists")
        rev = db.query(func.max(m.BOQItem.revision)).filter_by(project_id=project.id).scalar() or 1
        next_no = (db.query(func.max(m.BOQItem.item_no)).filter_by(
            project_id=project.id, revision=rev).scalar() or 0) + 1
        added = 0
        for line in p.get("lines", []):
            qty = float(line["quantity"])
            rate = float(line["unit_rate"])
            mat = Decimal(str(rate)) * Decimal(str(qty))
            total = (mat + Decimal(str(line.get("labour_cost") or 0)))
            db.add(m.BOQItem(
                project_id=project.id, revision=rev, item_no=next_no, category=line.get("category", ""),
                description=line.get("description") or line.get("material_name", "Item"),
                unit=line.get("unit", ""), quantity=qty, unit_rate=rate, material_cost=mat,
                labour_cost=line.get("labour_cost") or 0, total=total,
                rate_source=line.get("rate_source", "user_entered"),
                assumptions=(line.get("formula", "") + " | " + line.get("assumptions", ""))[:2000],
            ))
            next_no += 1
            added += 1
        db.commit()
        return {"message": f"{added} BOQ item(s) added to revision {rev}"}

    if a.action == "create_task":
        t = m.Task(project_id=a.project_id, name=p["name"], duration_days=int(p["duration"]),
                   start_date=date.fromisoformat(p["start_date"]) if p.get("start_date") else None,
                   priority=p.get("priority", "normal"), assignee=p.get("assignee", ""),
                   milestone=bool(p.get("milestone", False)), notes=p.get("notes", ""))
        db.add(t)
        db.flush()
        for dep in p.get("depends_on", []):
            db.add(m.TaskDep(task_id=t.id, depends_on_id=dep))
        db.commit()
        return {"message": f"Task '{t.name}' created", "entity_id": t.id}

    if a.action == "stock_adjustment":
        from app.services import inventory
        item = db.get(m.InventoryItem, p["item_id"])
        if not item or item.project_id != a.project_id:
            raise ApprovalError("Inventory item not found")
        inventory.apply_txn(db, item, p["kind"], float(p["quantity"]), p.get("note", ""), actor.id)
        return {"message": f"Stock {p['kind']} of {p['quantity']} {item.unit} applied"}

    if a.action == "send_email":
        d = db.get(m.EmailDraft, p["draft_id"])
        if not d or d.user_id != a.user_id:
            raise ApprovalError("Email draft not found")
        d.approval_id = a.id
        mail.send_approved(db, d)
        return {"message": f"Email sent to {d.to_addr}", "entity_id": d.id}

    if a.action == "create_automation":
        rule = m.AutomationRule(user_id=actor.id, project_id=a.project_id, enabled=True,
                                require_approval=bool(p.get("require_approval", True)),
                                **{k: v for k, v in p.items()
                                   if k in ("name", "trigger", "threshold", "recipients", "template",
                                            "schedule", "timezone")})
        db.add(rule)
        db.commit()
        return {"message": f"Automation '{rule.name}' enabled", "entity_id": rule.id}

    raise ApprovalError(f"Unsupported approval action '{a.action}'")


def execute_approved(db: Session, a: m.ApprovalRequest, actor: m.User) -> dict:
    """Retry an approval that was approved but failed to execute."""
    if a.status != "approved":
        raise ApprovalError("Only approved requests can be executed")
    if a.executed_at is not None:
        raise ApprovalError("This request already executed")
    result = _execute(db, a, actor)
    a.executed_at = m.now()
    a.execution_error = ""
    db.commit()
    return result


def serialize(a: m.ApprovalRequest) -> dict:
    return {
        "id": a.id,
        "action": a.action,
        "title": a.title or a.action.replace("_", " ").title(),
        "summary": a.summary,
        "payload": _payload(a),
        "before": json.loads(a.before_state or "{}"),
        "status": a.status,
        "project_id": a.project_id,
        "conversation_id": a.conversation_id,
        "created_at": a.created_at,
        "decided_at": a.decided_at,
        "expires_at": a.expires_at,
        "executed_at": a.executed_at,
        "execution_error": a.execution_error,
    }
