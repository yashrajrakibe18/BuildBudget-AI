"""Project workspace API: projects, rooms, estimates, BOQ, budget, inventory,
schedule, labour, purchase orders and report downloads."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.ai import tools as ai_tools
from app.api import serialize
from app.api.deps import current_user, owned_project, require
from app.api.schemas import (
    BoqFromEstimate,
    BoqItemIn,
    EstimateIn,
    ExpenseIn,
    ExpensePatch,
    InventoryIn,
    InventoryTxnIn,
    LabourEntryIn,
    LabourRateIn,
    POIn,
    ProjectIn,
    ProjectPatch,
    RoomIn,
    ScenarioIn,
    TaskIn,
    TaskPatch,
)
from app.core import permissions as P
from app.core.config import settings
from app.database import get_db
from app.services import activity, analytics, estimation, procurement, reporting, scheduling
from app.services import inventory as inventory_svc
from app.services import labour as labour_svc
from app.services import measurements as M

router = APIRouter()

D = Decimal


def money(x) -> float:
    return float(Decimal(str(x)).quantize(D("0.01")))


def latest_rev(db: Session, project_id: int) -> int:
    return db.query(func.max(m.BOQItem.revision)).filter_by(project_id=project_id).scalar() or 1


def _boq_math(item: m.BOQItem) -> None:
    qty, rate = D(str(item.quantity)), D(str(item.unit_rate))
    material = qty * rate
    subtotal = material + D(str(item.labour_cost or 0)) + D(str(item.transport_cost or 0))
    discounted = subtotal * (1 - D(str(item.discount_pct or 0)) / 100)
    item.material_cost = material.quantize(D("0.01"))
    item.total = (discounted * (1 + D(str(item.tax_pct or 0)) / 100)).quantize(D("0.01"))


# --------------------------------------------------------------------------- #
# projects
# --------------------------------------------------------------------------- #
@router.get("/projects")
def list_projects(include_archived: bool = False, status: str = "", q: str = "",
                  user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    query = db.query(m.Project)
    if P.effective_role(user.role) != "admin":
        query = query.filter_by(owner_id=user.id)
    if not include_archived:
        query = query.filter(m.Project.archived.is_(False))
    if status:
        query = query.filter(m.Project.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter((m.Project.name.ilike(like)) | (m.Project.location.ilike(like)))
    out = []
    for p in query.order_by(m.Project.id.desc()).all():
        from app.services import budget as budget_svc
        s = budget_svc.summary(db, p)
        tasks = db.query(m.Task).filter_by(project_id=p.id).all()
        progress = round(sum(t.progress for t in tasks) / len(tasks), 1) if tasks else 0
        row = {**serialize.project(p), **s, "progress": progress}
        row["budget_status"] = s["status"]
        row["status"] = p.status
        out.append(row)
    return out


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, user: m.User = Depends(require("project.create")),
                   db: Session = Depends(get_db)):
    project = m.Project(owner_id=user.id, currency=settings.currency, **body.model_dump())
    db.add(project)
    db.flush()
    activity.log(db, user_id=user.id, action="project_created", project_id=project.id,
                 entity="project", entity_id=project.id, summary=project.name)
    db.commit()
    return serialize.project(project)


@router.get("/projects/{pid}")
def get_project(pid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize.project(owned_project(db, user, pid))


@router.put("/projects/{pid}")
def update_project(pid: int, body: ProjectPatch, user: m.User = Depends(require("project.edit")),
                   db: Session = Depends(get_db)):
    project = owned_project(db, user, pid)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in changes.items():
        setattr(project, key, value)
    project.updated_at = m.now()
    activity.log(db, user_id=user.id, action="project_updated", project_id=pid,
                 entity="project", entity_id=pid,
                 summary=", ".join(k.replace("_", " ") for k in changes))
    db.commit()
    return serialize.project(project)


@router.post("/projects/{pid}/archive")
def archive_project(pid: int, user: m.User = Depends(require("project.archive")),
                    db: Session = Depends(get_db)):
    project = owned_project(db, user, pid)
    project.archived = True
    activity.log(db, user_id=user.id, action="project_archived", project_id=pid,
                 entity="project", entity_id=pid, summary=project.name)
    db.commit()
    return {"ok": True, "archived": True}


@router.post("/projects/{pid}/restore")
def restore_project(pid: int, user: m.User = Depends(require("project.archive")),
                    db: Session = Depends(get_db)):
    project = owned_project(db, user, pid)
    project.archived = False
    activity.log(db, user_id=user.id, action="project_restored", project_id=pid,
                 entity="project", entity_id=pid, summary=project.name)
    db.commit()
    return {"ok": True, "archived": False}


@router.delete("/projects/{pid}")
def delete_project(pid: int, user: m.User = Depends(require("project.delete")),
                   db: Session = Depends(get_db)):
    project = owned_project(db, user, pid)
    for model in (m.BOQItem, m.Expense, m.Task, m.InventoryItem, m.PurchaseOrder, m.Room,
                  m.Estimation, m.LabourEntry):
        for row in db.query(model).filter_by(project_id=pid).all():
            if isinstance(row, m.InventoryItem):
                db.query(m.InventoryTxn).filter_by(item_id=row.id).delete()
            if isinstance(row, m.Task):
                db.query(m.TaskDep).filter((m.TaskDep.task_id == row.id)
                                           | (m.TaskDep.depends_on_id == row.id)).delete()
            db.delete(row)
    db.query(m.Conversation).filter_by(project_id=pid).update({"project_id": None})
    db.delete(project)
    activity.log(db, user_id=user.id, action="project_deleted", entity="project", entity_id=pid,
                 summary=project.name)
    db.commit()
    return {"ok": True}


@router.get("/projects/{pid}/overview")
def project_overview(pid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services import budget as budget_svc
    project = owned_project(db, user, pid)
    summary = budget_svc.summary(db, project)
    health = analytics.project_health(db, project)
    tasks = db.query(m.Task).filter_by(project_id=pid).all()
    plan = scheduling.calendar_plan(
        [{"id": t.id, "name": t.name, "duration": t.duration_days,
          "deps": [d.depends_on_id for d in t.deps], "start_date": t.start_date,
          "progress": t.progress, "priority": t.priority, "assignee": t.assignee,
          "milestone": t.milestone} for t in tasks], project.start_date)
    items = db.query(m.BOQItem).filter_by(project_id=pid, revision=latest_rev(db, pid)).all()
    expenses = db.query(m.Expense).filter_by(project_id=pid).order_by(m.Expense.expense_date.desc()).all()
    inventory = db.query(m.InventoryItem).filter_by(project_id=pid).all()
    low = [i for i in inventory if i.reorder_level > 0 and i.available <= i.reorder_level]
    approvals_count = db.query(m.ApprovalRequest).filter_by(project_id=pid, status="pending").count()
    docs = db.query(m.Document).filter_by(project_id=pid, active=True).count()
    recent = (db.query(m.ActivityLog).filter_by(project_id=pid)
              .order_by(m.ActivityLog.id.desc()).limit(8).all())
    return {
        "project": serialize.project(project),
        "budget": summary,
        "health": health,
        "schedule": {"planned_finish": plan.get("project_finish"),
                     "total_duration_days": plan.get("total_duration_days"),
                     "overdue": len(plan.get("overdue", [])), "tasks": len(tasks),
                     "progress": round(sum(t.progress for t in tasks) / len(tasks), 1) if tasks else 0},
        "boq": {"revision": latest_rev(db, pid), "items": len(items),
                "total": round(sum(float(i.total or 0) for i in items), 2),
                "approved": sum(1 for i in items if i.approval_status == "approved")},
        "expenses": {"count": len(expenses),
                     "recent": [serialize.expense(e) for e in expenses[:5]]},
        "inventory": {"items": len(inventory), "low_stock": len(low),
                      "low": [serialize.inventory_item(i) for i in low[:5]]},
        "labour": labour_svc.summary(db, pid),
        "documents": docs,
        "pending_approvals": approvals_count,
        "recent_activity": [{"action": r.action, "summary": r.summary, "when": r.created_at}
                            for r in recent],
        "insights": _project_insights(summary, health, plan),
    }


def _project_insights(summary: dict, health: dict, plan: dict) -> list[dict]:
    out = [{"tone": "info" if health["band"] == "healthy" else "warning",
            "title": f"Project health {health['score']}/100",
            "detail": "; ".join(f"{label} ({delta:+d})" if delta else label
                                for label, delta in health["factors"]) or "No negative factors."}]
    if summary["utilization_pct"] is not None and summary["utilization_pct"] >= 90:
        out.append({"tone": "critical", "title": f"{summary['utilization_pct']}% of budget used",
                    "detail": "Review upcoming commitments before approving more spend."})
    if plan.get("overdue"):
        out.append({"tone": "critical", "title": f"{len(plan['overdue'])} overdue task(s)",
                    "detail": "Update progress or reschedule the affected activities."})
    return out


@router.get("/projects/{pid}/activity")
def project_activity(pid: int, limit: int = Query(30, ge=1, le=200),
                     user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    rows = (db.query(m.ActivityLog).filter_by(project_id=pid)
            .order_by(m.ActivityLog.id.desc()).limit(limit).all())
    names = {u.id: u.name for u in db.query(m.User).all()}
    return [{"id": r.id, "action": r.action, "summary": r.summary,
             "user": names.get(r.user_id, "System"), "when": r.created_at} for r in rows]


# --------------------------------------------------------------------------- #
# rooms and estimation scenarios
# --------------------------------------------------------------------------- #
@router.get("/projects/{pid}/rooms")
def list_rooms(pid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    out = []
    for room in db.query(m.Room).filter_by(project_id=pid).order_by(m.Room.id).all():
        openings = json.loads(room.openings_json or "[]")
        geometry = M.room_geometry(room.length, room.width, room.height, room.unit, openings)
        out.append({"id": room.id, "name": room.name, "length": room.length, "width": room.width,
                    "height": room.height, "unit": room.unit, "openings": openings,
                    "notes": room.notes, "geometry": geometry})
    return out


@router.post("/projects/{pid}/rooms", status_code=201)
def add_room(pid: int, body: RoomIn, user: m.User = Depends(require("project.edit")),
             db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    try:
        M.room_geometry(body.length, body.width, body.height, body.unit, body.openings)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    room = m.Room(project_id=pid, name=body.name, length=body.length, width=body.width,
                  height=body.height, unit=body.unit,
                  openings_json=json.dumps(body.openings), notes=body.notes)
    db.add(room)
    activity.log(db, user_id=user.id, action="room_added", project_id=pid, entity="room",
                 summary=f"{body.name}: {body.length}×{body.width}×{body.height} {body.unit}")
    db.commit()
    return {"id": room.id}


@router.delete("/projects/{pid}/rooms/{rid}")
def delete_room(pid: int, rid: int, user: m.User = Depends(require("project.edit")),
                db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    room = db.query(m.Room).filter_by(id=rid, project_id=pid).first()
    if not room:
        raise HTTPException(404, "Room not found")
    db.delete(room)
    db.commit()
    return {"ok": True}


@router.get("/measurements/convert")
def convert(value: float, from_unit: str, to_unit: str, user: m.User = Depends(current_user)):
    try:
        return {"result": M.convert(value, from_unit, to_unit), "unit": M.norm_unit(to_unit)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/estimates/calculate")
def calculate(body: EstimateIn, user: m.User = Depends(current_user)):
    try:
        return estimation.run(body.kind, body.params)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/estimates/kinds")
def estimate_kinds():
    return {"kinds": sorted(estimation.KINDS)}


@router.post("/estimates/room-geometry")
def room_geometry(body: dict, user: m.User = Depends(current_user)):
    try:
        return M.room_geometry(body["length"], body["width"], body["height"],
                               body.get("unit", "ft"), body.get("openings"))
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/projects/{pid}/estimations", status_code=201)
def save_scenario(pid: int, body: ScenarioIn, user: m.User = Depends(require("project.edit")),
                  db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    try:
        result = estimation.run(body.kind, body.params)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    total = 0.0
    if body.unit_rate is not None:
        total = body.unit_rate * float(result["final_quantity"])
    row = m.Estimation(project_id=pid, created_by=user.id, name=body.name, kind=body.kind,
                       params_json=json.dumps(body.params), result_json=json.dumps(result),
                       total_estimate=total)
    db.add(row)
    db.commit()
    return {"id": row.id, "total": total}


@router.get("/projects/{pid}/estimations")
def list_scenarios(pid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    out = []
    for row in db.query(m.Estimation).filter_by(project_id=pid).order_by(m.Estimation.id.desc()).all():
        out.append({"id": row.id, "name": row.name, "kind": row.kind,
                    "params": json.loads(row.params_json or "{}"),
                    "result": json.loads(row.result_json or "{}"),
                    "total": float(row.total_estimate or 0), "created_at": row.created_at})
    return out


@router.delete("/projects/{pid}/estimations/{eid}")
def delete_scenario(pid: int, eid: int, user: m.User = Depends(require("project.edit")),
                    db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    row = db.query(m.Estimation).filter_by(id=eid, project_id=pid).first()
    if not row:
        raise HTTPException(404, "Scenario not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# BOQ
# --------------------------------------------------------------------------- #
@router.get("/projects/{pid}/boq")
def get_boq(pid: int, revision: int | None = None, user: m.User = Depends(current_user),
            db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    rev = revision or latest_rev(db, pid)
    items = (db.query(m.BOQItem).filter_by(project_id=pid, revision=rev)
             .order_by(m.BOQItem.item_no).all())
    revisions = [r for (r,) in db.query(m.BOQItem.revision).filter_by(project_id=pid)
                 .distinct().order_by(m.BOQItem.revision).all()]
    total = sum(float(i.total or 0) for i in items)
    approved = all(i.approval_status == "approved" for i in items) if items else False
    return {"revision": rev, "revisions": revisions,
            "items": [serialize.boq_item(i) for i in items], "total": round(total, 2),
            "approved": approved,
            "category_totals": _category_totals(items)}


def _category_totals(items) -> list[dict]:
    buckets: dict[str, float] = {}
    for i in items:
        buckets[i.category or "Uncategorised"] = buckets.get(i.category or "Uncategorised", 0) + float(i.total or 0)
    return [{"category": k, "total": round(v, 2)}
            for k, v in sorted(buckets.items(), key=lambda kv: -kv[1])]


@router.post("/projects/{pid}/boq/from-estimate", status_code=201)
def boq_from_estimate(pid: int, body: BoqFromEstimate,
                      user: m.User = Depends(require("boq.write")), db: Session = Depends(get_db)):
    project = owned_project(db, user, pid)
    try:
        est = estimation.run(body.kind, body.params)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    rate, tax, source = body.unit_rate, body.tax_pct, "user_entered"
    if rate is None:
        prices = ai_tools.latest_prices(db, user.id, body.material_name)
        if not prices:
            raise HTTPException(
                422, "No stored price for this material. Enter a unit rate, or add a supplier "
                     "quotation first — BuildBudget AI never invents a price.")
        top = prices[0]
        rate = float(top.unit_price)
        tax = top.tax_pct if tax is None else tax
        source = top.source_type
    tax = 0.0 if tax is None else tax
    rev = latest_rev(db, pid)
    item_no = (db.query(func.max(m.BOQItem.item_no)).filter_by(project_id=pid, revision=rev)
               .scalar() or 0) + 1
    item = m.BOQItem(project_id=pid, revision=rev, item_no=item_no, category=body.category,
                     description=est["item"], unit=est["unit"], quantity=float(est["final_quantity"]),
                     unit_rate=rate, labour_cost=body.labour_cost,
                     transport_cost=body.transport_cost, discount_pct=body.discount_pct,
                     tax_pct=tax, rate_source=source, source_reference=est["source_reference"],
                     assumptions=f"{est['formula']} | " + "; ".join(est["assumptions"]))
    _boq_math(item)
    db.add(item)
    activity.log(db, user_id=user.id, action="boq_item_added", project_id=pid, entity="boq",
                 summary=f"{item.description} ({item.quantity:g} {item.unit})")
    db.commit()
    from app.services import budget as budget_svc
    return {"item": serialize.boq_item(item), "estimate": est,
            "budget": budget_svc.summary(db, project)}


@router.post("/projects/{pid}/boq/items", status_code=201)
def add_boq_item(pid: int, body: BoqItemIn, user: m.User = Depends(require("boq.write")),
                 db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    rev = latest_rev(db, pid)
    item_no = (db.query(func.max(m.BOQItem.item_no)).filter_by(project_id=pid, revision=rev)
               .scalar() or 0) + 1
    item = m.BOQItem(project_id=pid, revision=rev, item_no=item_no, **body.model_dump())
    _boq_math(item)
    db.add(item)
    activity.log(db, user_id=user.id, action="boq_item_added", project_id=pid, entity="boq",
                 summary=body.description)
    db.commit()
    return serialize.boq_item(item)


@router.put("/projects/{pid}/boq/{iid}")
def update_boq_item(pid: int, iid: int, body: BoqItemIn,
                    user: m.User = Depends(require("boq.write")), db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    item = db.query(m.BOQItem).filter_by(id=iid, project_id=pid).first()
    if not item:
        raise HTTPException(404, "BOQ item not found")
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    _boq_math(item)
    if item.approval_status == "approved":
        item.approval_status = "draft"   # a changed item needs fresh approval
    activity.log(db, user_id=user.id, action="boq_item_updated", project_id=pid, entity="boq",
                 entity_id=item.id, summary=item.description)
    db.commit()
    return serialize.boq_item(item)


@router.post("/projects/{pid}/boq/{iid}/duplicate", status_code=201)
def duplicate_boq_item(pid: int, iid: int, user: m.User = Depends(require("boq.write")),
                       db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    item = db.query(m.BOQItem).filter_by(id=iid, project_id=pid).first()
    if not item:
        raise HTTPException(404, "BOQ item not found")
    rev = item.revision
    item_no = (db.query(func.max(m.BOQItem.item_no)).filter_by(project_id=pid, revision=rev)
               .scalar() or 0) + 1
    clone = m.BOQItem(project_id=pid, revision=rev, item_no=item_no, category=item.category,
                      description=f"{item.description} (copy)", unit=item.unit,
                      quantity=item.quantity, unit_rate=item.unit_rate,
                      labour_cost=item.labour_cost, transport_cost=item.transport_cost,
                      discount_pct=item.discount_pct, wastage_pct=item.wastage_pct,
                      tax_pct=item.tax_pct, rate_source=item.rate_source,
                      source_reference=item.source_reference, assumptions=item.assumptions,
                      price_valid_until=item.price_valid_until, approval_status="draft")
    _boq_math(clone)
    db.add(clone)
    db.commit()
    return serialize.boq_item(clone)


@router.delete("/projects/{pid}/boq/{iid}")
def delete_boq_item(pid: int, iid: int, user: m.User = Depends(require("boq.write")),
                    db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    item = db.query(m.BOQItem).filter_by(id=iid, project_id=pid).first()
    if not item:
        raise HTTPException(404, "BOQ item not found")
    activity.log(db, user_id=user.id, action="boq_item_deleted", project_id=pid, entity="boq",
                 entity_id=iid, summary=item.description)
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/projects/{pid}/boq/revisions", status_code=201)
def new_revision(pid: int, user: m.User = Depends(require("boq.write")),
                 db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    rev = latest_rev(db, pid)
    for item in db.query(m.BOQItem).filter_by(project_id=pid, revision=rev).all():
        data = {c.name: getattr(item, c.name) for c in item.__table__.columns if c.name != "id"}
        data.update(revision=rev + 1, approval_status="draft")
        db.add(m.BOQItem(**data))
    activity.log(db, user_id=user.id, action="boq_revision_created", project_id=pid, entity="boq",
                 summary=f"Revision {rev + 1}")
    db.commit()
    return {"revision": rev + 1}


@router.post("/projects/{pid}/boq/approve")
def approve_boq(pid: int, user: m.User = Depends(require("boq.write")),
                db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    rev = latest_rev(db, pid)
    db.query(m.BOQItem).filter_by(project_id=pid, revision=rev).update({"approval_status": "approved"})
    activity.log(db, user_id=user.id, action="boq_approved", project_id=pid, entity="boq",
                 summary=f"Revision {rev} approved")
    db.commit()
    return {"ok": True, "revision": rev}


# --------------------------------------------------------------------------- #
# budget and expenses
# --------------------------------------------------------------------------- #
@router.get("/projects/{pid}/budget")
def budget(pid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services import budget as budget_svc
    project = owned_project(db, user, pid)
    summary = budget_svc.summary(db, project)
    labour = labour_svc.summary(db, pid)
    summary["labour_cost_recorded"] = labour["total_cost"]
    summary["committed_cost"] = summary["estimated_cost"]
    summary["alerts"] = _budget_alerts(summary)
    return summary


def _budget_alerts(summary: dict) -> list[dict]:
    util = summary["utilization_pct"]
    if util is None:
        return [{"level": "info", "message": "No approved budget set for this project."}]
    out = []
    for threshold in (100, 90, 75):
        if util >= threshold:
            out.append({"level": "critical" if threshold >= 100 else "warning",
                        "message": f"Budget utilisation has passed {threshold}%."})
            break
    return out


@router.get("/projects/{pid}/expenses")
def expenses(pid: int, category: str = "", q: str = "", user: m.User = Depends(current_user),
             db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    query = db.query(m.Expense).filter_by(project_id=pid)
    if category:
        query = query.filter(m.Expense.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter((m.Expense.description.ilike(like)) | (m.Expense.vendor.ilike(like))
                             | (m.Expense.invoice_no.ilike(like)))
    rows = query.order_by(m.Expense.expense_date.desc(), m.Expense.id.desc()).all()
    return [serialize.expense(e) for e in rows]


@router.post("/projects/{pid}/expenses", status_code=201)
def add_expense(pid: int, body: ExpenseIn, user: m.User = Depends(require("expense.write")),
                db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    expense = m.Expense(project_id=pid, created_by=user.id, category=body.category,
                        description=body.description, amount=body.amount, vendor=body.vendor,
                        invoice_no=(body.invoice_no or "").strip() or None,
                        expense_date=body.expense_date or date.today(),
                        payment_status=body.payment_status, receipt_name=body.receipt_name,
                        created_at=m.now())
    db.add(expense)
    try:
        db.flush()
        activity.log(db, user_id=user.id, action="expense_recorded", project_id=pid,
                     entity="expense", entity_id=expense.id,
                     summary=f"{body.category} {body.amount:,.2f}")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That invoice number is already recorded for this vendor") from None
    return {"id": expense.id, "expense": serialize.expense(expense)}


@router.put("/projects/{pid}/expenses/{eid}")
def update_expense(pid: int, eid: int, body: ExpensePatch,
                   user: m.User = Depends(require("expense.write")), db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    expense = db.query(m.Expense).filter_by(id=eid, project_id=pid).first()
    if not expense:
        raise HTTPException(404, "Expense not found")
    for key, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(expense, key, value)
    activity.log(db, user_id=user.id, action="expense_updated", project_id=pid, entity="expense",
                 entity_id=eid, summary=f"{expense.category} {float(expense.amount):,.2f}")
    db.commit()
    return serialize.expense(expense)


@router.delete("/projects/{pid}/expenses/{eid}")
def delete_expense(pid: int, eid: int, user: m.User = Depends(require("expense.write")),
                   db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    expense = db.query(m.Expense).filter_by(id=eid, project_id=pid).first()
    if not expense:
        raise HTTPException(404, "Expense not found")
    activity.log(db, user_id=user.id, action="expense_deleted", project_id=pid, entity="expense",
                 entity_id=eid, summary=f"{expense.category} {float(expense.amount):,.2f}")
    db.delete(expense)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# inventory
# --------------------------------------------------------------------------- #
@router.get("/projects/{pid}/inventory")
def inventory(pid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    return [serialize.inventory_item(i) for i in db.query(m.InventoryItem).filter_by(project_id=pid)]


@router.post("/projects/{pid}/inventory", status_code=201)
def add_inventory(pid: int, body: InventoryIn, user: m.User = Depends(require("inventory.write")),
                  db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    item = m.InventoryItem(project_id=pid, **body.model_dump())
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That material is already tracked in this project") from None
    if body.available:
        db.add(m.InventoryTxn(item_id=item.id, kind="received", quantity=body.available,
                              note="Opening stock", created_by=user.id))
    activity.log(db, user_id=user.id, action="inventory_created", project_id=pid,
                 entity="inventory", entity_id=item.id, summary=body.material_name)
    db.commit()
    return serialize.inventory_item(item)


@router.get("/projects/{pid}/inventory/{iid}/transactions")
def inventory_txns(pid: int, iid: int, user: m.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    item = db.query(m.InventoryItem).filter_by(id=iid, project_id=pid).first()
    if not item:
        raise HTTPException(404, "Inventory item not found")
    rows = (db.query(m.InventoryTxn).filter_by(item_id=iid)
            .order_by(m.InventoryTxn.id.desc()).limit(100).all())
    return [{"id": r.id, "kind": r.kind, "quantity": r.quantity, "note": r.note,
             "when": r.created_at} for r in rows]


@router.post("/projects/{pid}/inventory/{iid}/transactions", status_code=201)
def inventory_transaction(pid: int, iid: int, body: InventoryTxnIn,
                          user: m.User = Depends(require("inventory.write")),
                          db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    item = db.query(m.InventoryItem).filter_by(id=iid, project_id=pid).first()
    if not item:
        raise HTTPException(404, "Inventory item not found")
    try:
        inventory_svc.apply_txn(db, item, body.kind, body.quantity, body.note, user.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"available": item.available, "item": serialize.inventory_item(item)}


# --------------------------------------------------------------------------- #
# schedule
# --------------------------------------------------------------------------- #
def _plan(db: Session, project: m.Project) -> dict:
    tasks = db.query(m.Task).filter_by(project_id=project.id).all()
    return scheduling.calendar_plan(
        [{"id": t.id, "name": t.name, "duration": t.duration_days,
          "deps": [d.depends_on_id for d in t.deps], "start_date": t.start_date,
          "progress": t.progress, "priority": t.priority, "assignee": t.assignee,
          "milestone": t.milestone} for t in tasks], project.start_date)


@router.get("/projects/{pid}/tasks")
def tasks(pid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    project = owned_project(db, user, pid)
    rows = db.query(m.Task).filter_by(project_id=pid).order_by(m.Task.id).all()
    plan = _plan(db, project)
    try:
        cpm = scheduling.critical_path(
            [{"id": t.id, "duration": t.duration_days, "deps": [d.depends_on_id for d in t.deps],
              "name": t.name} for t in rows])
    except ValueError as exc:
        cpm = {"error": str(exc), "total_duration_days": 0, "critical_path": []}
    variance = scheduling.schedule_variance(plan["rows"]) if plan["rows"] else {}
    return {"tasks": [serialize.task(t) for t in rows], "plan": plan, "cpm": cpm,
            "variance": variance}


def _validate_deps(db: Session, pid: int, deps: list[int], exclude: int | None = None) -> None:
    if not deps:
        return
    found = {t.id for t in db.query(m.Task).filter(m.Task.project_id == pid,
                                                   m.Task.id.in_(deps)).all()}
    missing = [d for d in deps if d not in found]
    if missing:
        raise HTTPException(422, f"Dependency task(s) not in this project: {missing}")
    if exclude and exclude in deps:
        raise HTTPException(422, "A task cannot depend on itself")


@router.post("/projects/{pid}/tasks", status_code=201)
def add_task(pid: int, body: TaskIn, user: m.User = Depends(require("schedule.write")),
             db: Session = Depends(get_db)):
    project = owned_project(db, user, pid)
    _validate_deps(db, pid, body.depends_on)
    task = m.Task(project_id=pid, name=body.name, duration_days=body.duration_days,
                  start_date=body.start_date, progress=body.progress, priority=body.priority,
                  assignee=body.assignee, milestone=body.milestone, notes=body.notes)
    db.add(task)
    db.flush()
    for dep in body.depends_on:
        db.add(m.TaskDep(task_id=task.id, depends_on_id=dep))
    db.flush()
    try:
        _plan(db, project)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    activity.log(db, user_id=user.id, action="task_created", project_id=pid, entity="task",
                 entity_id=task.id, summary=body.name)
    db.commit()
    return {"id": task.id, "task": serialize.task(task)}


@router.put("/projects/{pid}/tasks/{tid}")
def update_task(pid: int, tid: int, body: TaskPatch,
                user: m.User = Depends(require("schedule.write")), db: Session = Depends(get_db)):
    project = owned_project(db, user, pid)
    task = db.query(m.Task).filter_by(id=tid, project_id=pid).first()
    if not task:
        raise HTTPException(404, "Task not found")
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    deps = data.pop("depends_on", None)
    for key, value in data.items():
        setattr(task, key, value)
    if deps is not None:
        _validate_deps(db, pid, deps, exclude=tid)
        db.query(m.TaskDep).filter_by(task_id=tid).delete()
        for dep in deps:
            db.add(m.TaskDep(task_id=tid, depends_on_id=dep))
    db.flush()
    try:
        _plan(db, project)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    activity.log(db, user_id=user.id, action="task_updated", project_id=pid, entity="task",
                 entity_id=tid, summary=task.name)
    db.commit()
    return serialize.task(task)


@router.put("/projects/{pid}/tasks/{tid}/progress")
def task_progress(pid: int, tid: int, progress: float = Query(ge=0, le=100),
                  user: m.User = Depends(require("schedule.write")), db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    task = db.query(m.Task).filter_by(id=tid, project_id=pid).first()
    if not task:
        raise HTTPException(404, "Task not found")
    task.progress = progress
    task.actual_completion = date.today() if progress >= 100 else None
    db.commit()
    return {"ok": True, "progress": task.progress}


@router.delete("/projects/{pid}/tasks/{tid}")
def delete_task(pid: int, tid: int, user: m.User = Depends(require("schedule.write")),
                db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    task = db.query(m.Task).filter_by(id=tid, project_id=pid).first()
    if not task:
        raise HTTPException(404, "Task not found")
    db.query(m.TaskDep).filter((m.TaskDep.task_id == tid) | (m.TaskDep.depends_on_id == tid)).delete()
    db.delete(task)
    db.commit()
    return {"ok": True}


@router.get("/projects/{pid}/weather")
def project_weather(pid: int, days: int = Query(3, ge=1, le=7),
                    user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services import weather
    project = owned_project(db, user, pid)
    if project.latitude is None or project.longitude is None:
        raise HTTPException(422, "Add latitude and longitude to this project to see a forecast")
    return weather.forecast(project.latitude, project.longitude, days)


# --------------------------------------------------------------------------- #
# labour
# --------------------------------------------------------------------------- #
@router.get("/labour/rates")
def labour_rates(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(m.LabourRate).filter_by(owner_id=user.id).order_by(m.LabourRate.category).all()
    return [{"id": r.id, "category": r.category, "rate": float(r.rate),
             "rate_type": r.rate_type, "source_type": r.source_type} for r in rows]


@router.post("/labour/rates", status_code=201)
def add_labour_rate(body: LabourRateIn, user: m.User = Depends(require("labour.write")),
                    db: Session = Depends(get_db)):
    row = m.LabourRate(owner_id=user.id, category=body.category, rate=body.rate,
                       rate_type=body.rate_type, source_type="user_entered")
    db.add(row)
    db.commit()
    return {"id": row.id}


@router.get("/projects/{pid}/labour")
def project_labour(pid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    return labour_svc.summary(db, pid)


@router.post("/projects/{pid}/labour", status_code=201)
def add_labour_entry(pid: int, body: LabourEntryIn, user: m.User = Depends(require("labour.write")),
                     db: Session = Depends(get_db)):
    project = owned_project(db, user, pid)
    try:
        entry = labour_svc.add_entry(db, user, project, category=body.category,
                                     workers=body.workers, days=body.days, rate=body.rate,
                                     contractor=body.contractor, rate_type=body.rate_type,
                                     hours_per_day=body.hours_per_day,
                                     work_date=body.work_date, note=body.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"id": entry.id}


@router.delete("/projects/{pid}/labour/{eid}")
def delete_labour_entry(pid: int, eid: int, user: m.User = Depends(require("labour.write")),
                        db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    entry = db.query(m.LabourEntry).filter_by(id=eid, project_id=pid).first()
    if not entry:
        raise HTTPException(404, "Labour entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# purchase orders
# --------------------------------------------------------------------------- #
@router.get("/projects/{pid}/purchase-orders")
def purchase_orders(pid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    rows = db.query(m.PurchaseOrder).filter_by(project_id=pid).order_by(m.PurchaseOrder.id.desc())
    return [procurement.serialize_po(po) for po in rows]


@router.post("/projects/{pid}/purchase-orders", status_code=201)
def create_purchase_order(pid: int, body: POIn,
                          user: m.User = Depends(require("supplier.write")),
                          db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    if body.supplier_id:
        supplier = db.get(m.Supplier, body.supplier_id)
        if not supplier or supplier.owner_id != user.id:
            raise HTTPException(422, "Unknown supplier")
    try:
        po = procurement.create_po(db, pid, user.id, body.items, supplier_id=body.supplier_id,
                                   expected_date=body.expected_date, notes=body.notes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return procurement.serialize_po(po)


@router.post("/projects/{pid}/purchase-orders/{poid}/receive")
def receive_purchase_order(pid: int, poid: int,
                           user: m.User = Depends(require("supplier.write")),
                           db: Session = Depends(get_db)):
    owned_project(db, user, pid)
    po = db.query(m.PurchaseOrder).filter_by(id=poid, project_id=pid).first()
    if not po:
        raise HTTPException(404, "Purchase order not found")
    try:
        procurement.receive(db, po, user.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return procurement.serialize_po(po)


@router.get("/projects/{pid}/purchase-orders/{poid}/pdf")
def purchase_order_pdf(pid: int, poid: int, user: m.User = Depends(current_user),
                       db: Session = Depends(get_db)):
    project = owned_project(db, user, pid)
    po = db.query(m.PurchaseOrder).filter_by(id=poid, project_id=pid).first()
    if not po:
        raise HTTPException(404, "Purchase order not found")
    data = procurement.serialize_po(po)
    header = ["Material", "Unit", "Quantity", "Unit price", "Line total"]
    rows = [[i["material"], i["unit"], f"{i['quantity']:g}", reporting.money(i["unit_price"]),
             reporting.money(i["line_total"])] for i in data["items"]]
    pdf = reporting.table_pdf(
        f"Purchase order {data['number']}", f"{project.name} · supplier: {data['supplier']}",
        header, rows,
        [f"<b>Total: {reporting.money(data['total'])}</b>", "Draft order — not a tax invoice.",
         "Delivery is subject to supplier confirmation."])
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{data["number"]}.pdf"'})


# --------------------------------------------------------------------------- #
# reports
# --------------------------------------------------------------------------- #
@router.get("/projects/{pid}/reports/{name}.{fmt}")
def project_report(pid: int, name: str, fmt: str, user: m.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    from app.services import budget as budget_svc
    project = owned_project(db, user, pid)
    rev = latest_rev(db, pid)
    items = (db.query(m.BOQItem).filter_by(project_id=pid, revision=rev)
             .order_by(m.BOQItem.item_no).all())
    exps = db.query(m.Expense).filter_by(project_id=pid).order_by(m.Expense.expense_date).all()
    summary = budget_svc.summary(db, project)
    plan = _plan(db, project)
    labour = labour_svc.summary(db, pid)
    inventory_rows = [{"material": i.material_name, "available": i.available, "unit": i.unit,
                       "reserved": i.reserved, "reorder_level": i.reorder_level,
                       "location": i.location,
                       "low": i.reorder_level > 0 and i.available <= i.reorder_level}
                      for i in db.query(m.InventoryItem).filter_by(project_id=pid)]
    monthly: dict[str, float] = {}
    for e in exps:
        key = e.expense_date.strftime("%Y-%m")
        monthly[key] = monthly.get(key, 0) + float(e.amount)

    builders = {
        ("boq", "pdf"): lambda: reporting.boq_pdf(project.name, items, summary),
        ("estimate", "pdf"): lambda: reporting.boq_pdf(project.name, items, summary),
        ("boq", "xlsx"): lambda: reporting.boq_xlsx(project.name, items),
        ("boq", "csv"): lambda: reporting.boq_csv(items),
        ("boq", "docx"): lambda: reporting.boq_docx(project.name, items),
        ("expenses", "xlsx"): lambda: reporting.expenses_xlsx(project.name, exps),
        ("expenses", "csv"): lambda: reporting.expenses_csv(exps),
        ("budget", "pdf"): lambda: reporting.budget_pdf(project, summary, exps, items),
        ("inventory", "pdf"): lambda: reporting.inventory_pdf(project.name, inventory_rows),
        ("inventory", "xlsx"): lambda: reporting.inventory_xlsx(project.name, inventory_rows),
        ("progress", "pdf"): lambda: reporting.progress_pdf(
            project, summary, plan, [f"Budget utilisation {summary['utilization_pct']}%"]
            if summary["utilization_pct"] is not None else ["No budget set"]),
        ("summary", "pdf"): lambda: reporting.project_summary_pdf(
            project, summary, items, exps, plan, labour,
            ["Preliminary planning document."]),
        ("summary", "xlsx"): lambda: reporting.summary_xlsx(project.name, summary, items, exps, monthly),
        ("comparison", "pdf"): lambda: reporting.supplier_pdf("Stored quotations", 0, []),
    }
    key = (name, fmt)
    if key not in builders:
        raise HTTPException(404, "Unknown report. Available: " +
                            ", ".join(f"{a}.{b}" for a, b in sorted(builders)))
    media = {"pdf": "application/pdf", "csv": "text/csv", "docx":
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(fmt, "application/octet-stream")
    filename = f"{name}_{project.id}.{fmt}"
    activity.log(db, user_id=user.id, action="report_generated", project_id=pid,
                 entity="report", summary=f"{name}.{fmt}")
    db.commit()
    return Response(builders[key](), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
