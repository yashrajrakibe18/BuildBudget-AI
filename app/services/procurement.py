"""Purchase requirements, supplier comparison and purchase orders (Decimal money)."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app import models as m
from app.services import activity

Q = Decimal("0.01")


def purchase_requirement(required: float, buffer: float = 0.0, usable_available: float = 0.0,
                         confirmed_incoming: float = 0.0) -> float:
    for n, v in (("required", required), ("buffer", buffer), ("available", usable_available),
                 ("incoming", confirmed_incoming)):
        if v < 0:
            raise ValueError(f"{n} must be >= 0")
    return max(0.0, required + buffer - usable_available - confirmed_incoming)


def delivered_cost(unit_price, tax_pct, delivery_charge, moq, quantity) -> dict:
    qty = float(quantity)
    if qty <= 0:
        raise ValueError("quantity must be > 0")
    buy_qty = max(qty, float(moq or 0))
    base = Decimal(str(unit_price)) * Decimal(str(buy_qty))
    tax = base * Decimal(str(tax_pct)) / 100
    total = (base + tax + Decimal(str(delivery_charge or 0))).quantize(Q, ROUND_HALF_UP)
    return {"buy_quantity": buy_qty, "base": float(base.quantize(Q)), "tax": float(tax.quantize(Q)),
            "delivery": float(Decimal(str(delivery_charge or 0))), "total": float(total),
            "effective_unit_cost": float((total / Decimal(str(buy_qty))).quantize(Decimal("0.0001")))}


def compare_quotes(quotes: list[dict], quantity: float, today: date | None = None) -> list[dict]:
    """quotes: unit_price, tax_pct, delivery_charge, moq, valid_until, available, supplier, source_type."""
    today = today or date.today()
    rows = []
    for q in quotes:
        c = delivered_cost(q["unit_price"], q["tax_pct"], q["delivery_charge"], q["moq"], quantity)
        vu = q.get("valid_until")
        if isinstance(vu, str):
            try:
                vu = date.fromisoformat(vu)
            except ValueError:
                vu = None
        expired = bool(vu and vu < today)
        rows.append({**c, "supplier": q.get("supplier"), "supplier_id": q.get("supplier_id"),
                     "unit_price": float(q["unit_price"]), "tax_pct": q.get("tax_pct"),
                     "moq": q.get("moq"), "source_type": q.get("source_type"),
                     "valid_until": vu.isoformat() if vu else None,
                     "expired": expired, "available": q.get("available", True),
                     "lead_time_days": q.get("lead_time_days"),
                     "is_demo": q.get("source_type") == "demonstration"})
    rows.sort(key=lambda r: (r["expired"], not r["available"], r["total"]))
    best = rows[0]["total"] if rows else 0
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        if i == 1:
            r["recommendation"] = "Lowest total delivered cost among valid quotations."
        else:
            extra = r["total"] - best
            reasons = []
            if r["expired"]:
                reasons.append("quotation has expired")
            if not r["available"]:
                reasons.append("marked unavailable")
            if extra > 0:
                reasons.append(f"costs {extra:,.0f} more delivered")
            r["recommendation"] = ", ".join(reasons) or "Alternative option."
    return rows


def create_po(db: Session, project_id: int, user_id: int, items: list[dict], *,
              supplier_id: int | None = None, expected_date: date | None = None,
              notes: str = "") -> m.PurchaseOrder:
    if not items:
        raise ValueError("A purchase order needs at least one item")
    po = m.PurchaseOrder(project_id=project_id, supplier_id=supplier_id, status="draft",
                         created_by=user_id, expected_date=expected_date, notes=notes[:500],
                         total=Decimal("0"))
    total = Decimal("0")
    for it in items:
        qty = float(it.get("quantity") or 0)
        price = float(it.get("unit_price") or 0)
        if qty <= 0:
            raise ValueError("Every purchase order line needs a positive quantity")
        if price < 0:
            raise ValueError("Unit price cannot be negative")
        line = (Decimal(str(price)) * Decimal(str(qty))).quantize(Q)
        total += line
        po.items.append(m.POItem(material_name=it["material_name"], unit=it.get("unit", ""),
                                 quantity=qty, unit_price=Decimal(str(price)), line_total=line))
    po.total = total.quantize(Q)
    db.add(po)
    db.flush()
    po.number = f"PO-{po.id:05d}"
    activity.log(db, user_id=user_id, project_id=project_id, action="purchase_order_created",
                 entity="purchase_order", entity_id=po.id, summary=f"{po.number} draft for {total:,.2f}")
    db.commit()
    return po


def receive(db: Session, po: m.PurchaseOrder, user_id: int, received_on: date | None = None,
            note: str = "") -> m.PurchaseOrder:
    if po.status in ("received", "cancelled"):
        raise ValueError(f"Purchase order is already {po.status}")
    po.status = "received"
    po.received_date = received_on or date.today()
    for item in po.items:
        item.received_qty = item.quantity
    activity.log(db, user_id=user_id, project_id=po.project_id, action="purchase_order_received",
                 entity="purchase_order", entity_id=po.id,
                 summary=f"{po.number} received {po.received_date} {note}".strip())
    db.commit()
    return po


def serialize_po(po: m.PurchaseOrder) -> dict:
    return {
        "id": po.id, "number": po.number or f"PO-{po.id:05d}", "project_id": po.project_id,
        "supplier": po.supplier.name if po.supplier else "No supplier selected",
        "supplier_id": po.supplier_id, "status": po.status, "total": float(po.total or 0),
        "expected_date": po.expected_date, "received_date": po.received_date,
        "created_at": po.created_at, "notes": po.notes,
        "delivery_late": bool(po.expected_date and not po.received_date and po.expected_date < date.today()),
        "items": [{"material": i.material_name, "unit": i.unit, "quantity": i.quantity,
                   "unit_price": float(i.unit_price), "line_total": float(i.line_total),
                   "received": i.received_qty} for i in po.items],
    }
