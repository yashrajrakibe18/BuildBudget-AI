"""Suppliers, material prices, procurement and the cross-project module views."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models as m
from app.ai import tools as ai_tools
from app.api import serialize
from app.api.deps import current_user, require
from app.api.schemas import PriceIn, SupplierIn
from app.core import permissions as P
from app.database import get_db
from app.services import procurement

router = APIRouter()


# --------------------------------------------------------------------------- #
# suppliers
# --------------------------------------------------------------------------- #
@router.get("/suppliers")
def list_suppliers(q: str = "", category: str = "", include_inactive: bool = False,
                   user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    query = db.query(m.Supplier).filter(m.Supplier.owner_id == user.id)
    if not include_inactive:
        query = query.filter(m.Supplier.active.is_(True))
    rows = [s for s in query.order_by(m.Supplier.name).all() if (s.name or "").strip()]
    if q:
        needle = q.lower()
        rows = [s for s in rows if needle in s.name.lower() or needle in (s.location or "").lower()
                or needle in (s.category or "").lower()]
    if category:
        rows = [s for s in rows if (s.category or "").lower() == category.lower()]
    price_counts = dict(db.query(m.MaterialPrice.supplier_id, func.count(m.MaterialPrice.id))
                        .filter(m.MaterialPrice.owner_id == user.id)
                        .group_by(m.MaterialPrice.supplier_id).all())
    return [{**serialize.supplier(s), "quotation_count": price_counts.get(s.id, 0)} for s in rows]


@router.post("/suppliers", status_code=201)
def add_supplier(body: SupplierIn, user: m.User = Depends(require("supplier.write")),
                 db: Session = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(422, "Supplier name is required")
    clash = (db.query(m.Supplier)
             .filter_by(owner_id=user.id, name=body.name.strip()).first())
    if clash:
        raise HTTPException(409, f"A supplier named '{body.name.strip()}' already exists")
    supplier = m.Supplier(owner_id=user.id, created_at=m.now(), **body.model_dump())
    db.add(supplier)
    db.commit()
    return serialize.supplier(supplier)


@router.put("/suppliers/{sid}")
def update_supplier(sid: int, body: SupplierIn, user: m.User = Depends(require("supplier.write")),
                    db: Session = Depends(get_db)):
    supplier = db.query(m.Supplier).filter_by(id=sid, owner_id=user.id).first()
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    for key, value in body.model_dump().items():
        setattr(supplier, key, value)
    db.commit()
    return serialize.supplier(supplier)


@router.delete("/suppliers/{sid}")
def delete_supplier(sid: int, user: m.User = Depends(require("supplier.write")),
                    db: Session = Depends(get_db)):
    supplier = db.query(m.Supplier).filter_by(id=sid, owner_id=user.id).first()
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    in_use = db.query(m.PurchaseOrder).filter_by(supplier_id=sid).count()
    if in_use:
        supplier.active = False
        db.commit()
        return {"ok": True, "deactivated": True,
                "message": "Supplier has purchase orders, so it was deactivated instead of deleted."}
    db.query(m.MaterialPrice).filter_by(owner_id=user.id, supplier_id=sid).delete()
    db.delete(supplier)
    db.commit()
    return {"ok": True}


# NOTE: this must stay above "/suppliers/{sid}" or "compare" is parsed as an id.
@router.get("/suppliers/compare")
def compare(material: str, quantity: float = Query(gt=0),
            user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = ai_tools.latest_prices(db, user.id, material)
    if not rows:
        raise HTTPException(404, "No stored quotations for this material yet. Add a supplier quotation first.")
    return procurement.compare_quotes(ai_tools.quotes_as_dicts(rows), quantity)


@router.get("/suppliers/{sid}")
def supplier_profile(sid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    supplier = db.query(m.Supplier).filter_by(id=sid, owner_id=user.id).first()
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    quotes = (db.query(m.MaterialPrice).filter_by(owner_id=user.id, supplier_id=sid)
              .order_by(m.MaterialPrice.quotation_date.desc()).limit(50).all())
    pos = db.query(m.PurchaseOrder).filter_by(supplier_id=sid).all()
    delivered = [p for p in pos if p.received_date and p.expected_date]
    on_time = [p for p in delivered if p.received_date <= p.expected_date]
    return {
        "supplier": serialize.supplier(supplier),
        "quotations": [serialize.price(r) for r in quotes],
        "materials": sorted({r.material.name for r in quotes}),
        "purchase_orders": [procurement.serialize_po(p) for p in pos],
        "performance": {
            "orders": len(pos), "delivered": len(delivered),
            "on_time_pct": round(100 * len(on_time) / len(delivered), 1) if delivered else None,
            "note": ("No deliveries recorded yet — reliability cannot be scored."
                     if not delivered else "Computed from recorded purchase order deliveries."),
        },
        "is_demo": supplier.is_demo,
    }


# --------------------------------------------------------------------------- #
# material prices
# --------------------------------------------------------------------------- #
def _price_row(db: Session, user: m.User, body: PriceIn) -> m.MaterialPrice:
    material = db.query(m.Material).filter_by(name=body.material_name.strip(),
                                              category=body.category).first()
    if not material:
        material = m.Material(name=body.material_name.strip(), category=body.category, unit=body.unit)
        db.add(material)
        db.flush()
    if body.supplier_id:
        supplier = db.get(m.Supplier, body.supplier_id)
        if not supplier or supplier.owner_id != user.id:
            raise HTTPException(422, "Unknown supplier")
    row = m.MaterialPrice(owner_id=user.id, material_id=material.id, supplier_id=body.supplier_id,
                          brand=body.brand, unit_price=body.unit_price, tax_pct=body.tax_pct,
                          delivery_charge=body.delivery_charge, moq=body.moq,
                          valid_until=body.valid_until, source_type=body.source_type)
    db.add(row)
    return row


@router.get("/material-prices")
def list_prices(q: str = "", supplier_id: int | None = None, source: str = "",
                limit: int = Query(200, ge=1, le=500),
                user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    query = db.query(m.MaterialPrice).join(m.Material).filter(m.MaterialPrice.owner_id == user.id)
    if q:
        query = query.filter(m.Material.name.ilike(f"%{q}%"))
    if supplier_id:
        query = query.filter(m.MaterialPrice.supplier_id == supplier_id)
    if source:
        query = query.filter(m.MaterialPrice.source_type == source)
    rows = query.order_by(m.MaterialPrice.quotation_date.desc()).limit(limit).all()
    return [serialize.price(r) for r in rows]


@router.post("/material-prices", status_code=201)
def add_price(body: PriceIn, user: m.User = Depends(require("supplier.write")),
              db: Session = Depends(get_db)):
    row = _price_row(db, user, body)
    db.commit()
    return {"ok": True, "id": row.id}


@router.delete("/material-prices/{pid}")
def delete_price(pid: int, user: m.User = Depends(require("supplier.write")),
                 db: Session = Depends(get_db)):
    row = db.query(m.MaterialPrice).filter_by(id=pid, owner_id=user.id).first()
    if not row:
        raise HTTPException(404, "Price not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/material-prices/history")
def price_history(material: str, user: m.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    rows = ai_tools.latest_prices(db, user.id, material)
    points = [{"date": r.quotation_date, "unit_price": float(r.unit_price),
               "supplier": r.supplier.name if r.supplier else "Unspecified",
               "source_type": r.source_type} for r in rows]
    points.reverse()
    return {"material": material, "points": points,
            "note": "Only prices you or your suppliers recorded. Demonstration points are synthetic."}


@router.post("/material-prices/import-csv", status_code=201)
async def import_prices(file: UploadFile = File(...),
                        user: m.User = Depends(require("supplier.write")),
                        db: Session = Depends(get_db)):
    import csv
    import io
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(raw)))
    imported, errors = 0, []
    for index, row in enumerate(rows, 2):
        try:
            _price_row(db, user, PriceIn(
                material_name=row["material_name"], category=row.get("category") or "Other",
                unit=row["unit"], unit_price=float(row["unit_price"]),
                tax_pct=float(row.get("tax_pct") or 18),
                delivery_charge=float(row.get("delivery_charge") or 0),
                moq=float(row.get("moq") or 1),
                valid_until=date.fromisoformat(row["valid_until"]) if row.get("valid_until") else None,
                source_type="supplier_quotation"))
            imported += 1
        except HTTPException as exc:
            errors.append(f"Row {index}: {exc.detail}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Row {index}: {exc}")
    db.commit()
    return {"imported": imported, "errors": errors,
            "message": f"{imported} quotation row(s) imported."}


@router.post("/material-prices/import/preview")
async def preview_import(file: UploadFile = File(...), user: m.User = Depends(current_user),
                         db: Session = Depends(get_db)):
    import csv
    import io
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    required = {"material_name", "unit", "unit_price"}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise HTTPException(422, f"CSV is missing required column(s): {', '.join(sorted(missing))}")
    rows, errors, duplicates = [], [], 0
    for index, row in enumerate(reader, 2):
        try:
            price = float(row["unit_price"])
            if price < 0:
                raise ValueError("unit price cannot be negative")
            existing = None
            if row.get("supplier_id"):
                existing = (db.query(m.MaterialPrice)
                            .filter_by(owner_id=user.id, supplier_id=int(row["supplier_id"]),
                                       material_id=db.query(m.Material.id)
                                       .filter_by(name=row["material_name"]).scalar()).first())
            if existing:
                duplicates += 1
            rows.append({"row": index, "material_name": row["material_name"],
                         "unit": row["unit"], "unit_price": price,
                         "category": row.get("category") or "Other",
                         "possible_duplicate": bool(existing)})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Row {index}: {exc}")
    return {"rows": rows[:500], "errors": errors, "duplicates": duplicates,
            "valid": len(rows), "note": "Preview only — nothing has been saved yet."}


@router.get("/procurement/requirement")
def requirement(required: float, buffer: float = 0, available: float = 0, incoming: float = 0,
                user: m.User = Depends(current_user)):
    try:
        qty = procurement.purchase_requirement(required, buffer, available, incoming)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"purchase_quantity": qty,
            "formula": "max(0, required + buffer − available − incoming)"}


# --------------------------------------------------------------------------- #
# cross-project module views
# --------------------------------------------------------------------------- #
def _projects(db: Session, user: m.User):
    query = db.query(m.Project)
    if P.effective_role(user.role) != "admin":
        query = query.filter_by(owner_id=user.id)
    return query.order_by(m.Project.id.desc()).all()


@router.get("/modules/{name}")
def module_view(name: str, project_id: int | None = None, q: str = "",
                user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    projects = _projects(db, user)
    if project_id:
        projects = [p for p in projects if p.id == project_id]
    ids = [p.id for p in projects]
    names = {p.id: p.name for p in projects}
    from app.services import budget as budget_svc

    if name == "budgets":
        rows = []
        for project in projects:
            s = budget_svc.summary(db, project)
            rows.append({"project_id": project.id, "project": project.name,
                         "status": s["status"], "approved_budget": s["approved_budget"],
                         "estimated_cost": s["estimated_cost"],
                         "actual_expenses": s["actual_expenses"],
                         "remaining_budget": s["remaining_budget"],
                         "utilization_pct": s["utilization_pct"]})
        return {"module": name, "rows": rows, "kpis": [
            {"label": "Approved budget", "value": round(sum(r["approved_budget"] for r in rows), 2), "money": True},
            {"label": "Actual expenses", "value": round(sum(r["actual_expenses"] for r in rows), 2), "money": True},
            {"label": "Remaining", "value": round(sum(r["remaining_budget"] for r in rows), 2), "money": True},
            {"label": "Over budget", "value": sum(1 for r in rows if r["status"] == "over_budget")},
        ]}

    if name == "boq":
        rows = []
        for project in projects:
            rev = (db.query(func.max(m.BOQItem.revision)).filter_by(project_id=project.id).scalar() or 0)
            if not rev:
                continue
            items = db.query(m.BOQItem).filter_by(project_id=project.id, revision=rev).all()
            rows.append({"project_id": project.id, "project": project.name, "revision": rev,
                         "items": len(items), "approved": all(i.approval_status == "approved" for i in items),
                         "total": round(sum(float(i.total or 0) for i in items), 2)})
        return {"module": name, "rows": rows, "kpis": [
            {"label": "Projects with a BOQ", "value": len(rows)},
            {"label": "Items priced", "value": sum(r["items"] for r in rows)},
            {"label": "Combined value", "value": round(sum(r["total"] for r in rows), 2), "money": True},
        ]}

    if name == "inventory":
        rows = []
        for item in db.query(m.InventoryItem).filter(m.InventoryItem.project_id.in_(ids or [-1])).all():
            if q and q.lower() not in item.material_name.lower():
                continue
            rows.append({**serialize.inventory_item(item), "project": names.get(item.project_id, "")})
        return {"module": name, "rows": rows, "kpis": [
            {"label": "Materials tracked", "value": len(rows)},
            {"label": "Below reorder level", "value": sum(1 for r in rows if r["low"])},
            {"label": "Projects with stock", "value": len({r["project"] for r in rows})},
        ]}

    if name == "schedule":
        from app.services import scheduling
        rows = []
        for project in projects:
            tasks = db.query(m.Task).filter_by(project_id=project.id).all()
            plan = scheduling.calendar_plan(
                [{"id": t.id, "name": t.name, "duration": t.duration_days,
                  "deps": [d.depends_on_id for d in t.deps], "start_date": t.start_date,
                  "progress": t.progress, "priority": t.priority, "assignee": t.assignee,
                  "milestone": t.milestone} for t in tasks], project.start_date)
            rows.append({"project_id": project.id, "project": project.name,
                         "tasks": len(tasks), "planned_finish": plan.get("project_finish"),
                         "working_days": plan.get("total_duration_days"),
                         "overdue": len(plan.get("overdue", [])),
                         "progress": round(sum(t.progress for t in tasks) / len(tasks), 1) if tasks else 0})
        return {"module": name, "rows": rows, "kpis": [
            {"label": "Projects scheduled", "value": sum(1 for r in rows if r["tasks"])},
            {"label": "Overdue tasks", "value": sum(r["overdue"] for r in rows)},
            {"label": "Average progress",
             "value": round(sum(r["progress"] for r in rows) / len(rows), 1) if rows else 0},
        ]}

    if name == "procurement":
        pos = (db.query(m.PurchaseOrder).filter(m.PurchaseOrder.project_id.in_(ids or [-1]))
               .order_by(m.PurchaseOrder.id.desc()).all())
        rows = [{**procurement.serialize_po(po), "project": names.get(po.project_id, "")} for po in pos]
        return {"module": name, "rows": rows, "kpis": [
            {"label": "Purchase orders", "value": len(rows)},
            {"label": "Draft", "value": sum(1 for r in rows if r["status"] == "draft")},
            {"label": "Delivered", "value": sum(1 for r in rows if r["status"] == "received")},
            {"label": "Committed value", "value": round(sum(r["total"] for r in rows), 2), "money": True},
        ]}

    if name == "labour":
        from app.services import labour as labour_svc
        rows = []
        for project in projects:
            s = labour_svc.summary(db, project.id)
            rows.append({"project_id": project.id, "project": project.name,
                         "entries": len(s["entries"]), "worker_days": s["worker_days"],
                         "total_cost": s["total_cost"],
                         "categories": len(s["by_category"])})
        return {"module": name, "rows": rows, "kpis": [
            {"label": "Labour cost recorded", "value": round(sum(r["total_cost"] for r in rows), 2), "money": True},
            {"label": "Worker-days", "value": round(sum(r["worker_days"] for r in rows), 1)},
            {"label": "Projects with labour", "value": sum(1 for r in rows if r["entries"])},
        ]}

    raise HTTPException(404, f"Unknown module '{name}'")
