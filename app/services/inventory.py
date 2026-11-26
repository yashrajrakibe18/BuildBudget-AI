"""Inventory transactions with validation (never negative stock)."""
from sqlalchemy.orm import Session

from app import models as m
from app.services import activity

KINDS = {"received", "consumed", "damaged", "wasted", "returned", "adjust"}
POSITIVE = {"received"}
NEGATIVE = {"consumed", "damaged", "wasted", "returned"}


def apply_txn(db: Session, item: m.InventoryItem, kind: str, quantity: float,
              note: str = "", user_id: int | None = None) -> m.InventoryTxn:
    if kind not in KINDS:
        raise ValueError(f"Unknown transaction type '{kind}'. Allowed: {sorted(KINDS)}")
    if quantity is None or quantity <= 0:
        raise ValueError("Quantity must be greater than zero")
    if kind in POSITIVE:
        item.available += quantity
    elif kind in NEGATIVE:
        if item.available - quantity < 0:
            raise ValueError(
                f"Cannot {kind} {quantity:g} {item.unit}: only {item.available:g} available"
            )
        item.available -= quantity
        if kind == "damaged":
            item.damaged = (item.damaged or 0) + quantity
    else:  # adjust: set an absolute counted quantity
        if item.available - quantity < 0:
            raise ValueError("Adjustment would make stock negative")
        delta = quantity - item.available
        item.available = quantity
        quantity = abs(delta)
    txn = m.InventoryTxn(item_id=item.id, kind=kind, quantity=quantity, note=note[:300],
                         created_by=user_id)
    db.add(txn)
    activity.log(db, user_id=user_id, project_id=item.project_id, action=f"stock_{kind}",
                 entity="inventory", entity_id=item.id,
                 summary=f"{kind.title()} {quantity:g} {item.unit} of {item.material_name}")
    db.commit()
    return txn


def low_stock(db: Session, project_id: int | None = None, owner_id: int | None = None):
    q = db.query(m.InventoryItem, m.Project).join(m.Project, m.InventoryItem.project_id == m.Project.id)
    if project_id:
        q = q.filter(m.InventoryItem.project_id == project_id)
    if owner_id:
        q = q.filter(m.Project.owner_id == owner_id)
    return [(i, p) for i, p in q.all() if i.reorder_level > 0 and i.available <= i.reorder_level]


def reorder_quantity(item: m.InventoryItem, target_multiple: float = 2.0) -> float:
    """Simple, explainable rule: refill to `target_multiple` x reorder level."""
    if item.reorder_level <= 0:
        return 0.0
    target = item.reorder_level * max(1.0, target_multiple)
    needed = target - (item.available or 0) - (item.incoming or 0)
    return round(max(0.0, needed), 3)
