"""API serializers — one place that decides what a resource looks like over HTTP."""
from __future__ import annotations

import json
from decimal import Decimal

from app import models as m
from app.core import permissions as P
from app.core.labels import NOTIFICATION_KINDS, PROJECT_STATUS, PROJECT_TYPES, label


def num(value) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def project(p: m.Project) -> dict:
    return {
        "id": p.id, "name": p.name, "project_type": p.project_type,
        "project_type_label": label(PROJECT_TYPES, p.project_type, "Custom Project"),
        "location": p.location, "latitude": p.latitude, "longitude": p.longitude,
        "contractor": p.contractor, "manager_name": p.manager_name,
        "manager_email": p.manager_email, "start_date": p.start_date, "end_date": p.end_date,
        "budget": num(p.budget), "currency": p.currency, "description": p.description,
        "assumptions": p.assumptions, "status": p.status,
        "status_label": label(PROJECT_STATUS, p.status), "archived": p.archived,
        "is_demo": p.is_demo, "created_at": p.created_at, "updated_at": p.updated_at,
        "has_coordinates": p.latitude is not None and p.longitude is not None,
    }


def boq_item(i: m.BOQItem) -> dict:
    return {
        "id": i.id, "item_no": i.item_no, "revision": i.revision, "category": i.category,
        "description": i.description, "unit": i.unit, "quantity": i.quantity,
        "unit_rate": num(i.unit_rate), "material_cost": num(i.material_cost),
        "labour_cost": num(i.labour_cost), "transport_cost": num(i.transport_cost),
        "discount_pct": i.discount_pct, "wastage_pct": i.wastage_pct, "tax_pct": i.tax_pct,
        "total": num(i.total), "rate_source": i.rate_source,
        "source_reference": i.source_reference, "assumptions": i.assumptions,
        "approval_status": i.approval_status,
        "price_valid_until": i.price_valid_until,
    }


def expense(e: m.Expense) -> dict:
    return {
        "id": e.id, "category": e.category, "description": e.description,
        "amount": num(e.amount), "date": e.expense_date, "vendor": e.vendor,
        "invoice_no": e.invoice_no, "payment_status": e.payment_status,
        "receipt_name": e.receipt_name, "approval_status": e.approval_status,
    }


def inventory_item(i: m.InventoryItem) -> dict:
    return {
        "id": i.id, "material_name": i.material_name, "unit": i.unit,
        "available": i.available, "reserved": i.reserved, "incoming": i.incoming,
        "damaged": i.damaged, "reorder_level": i.reorder_level, "location": i.location,
        "low": i.reorder_level > 0 and i.available <= i.reorder_level,
        "usable": max(0.0, (i.available or 0) - (i.reserved or 0)),
    }


def supplier(s: m.Supplier) -> dict:
    return {
        "id": s.id, "name": s.name, "email": s.email, "phone": s.phone,
        "location": s.location, "category": s.category, "tax_id": s.tax_id,
        "notes": s.notes, "lead_time_days": s.lead_time_days,
        "payment_terms": s.payment_terms, "reliability": s.reliability,
        "active": s.active, "is_demo": s.is_demo,
    }


def price(r: m.MaterialPrice) -> dict:
    return {
        "id": r.id, "material": r.material.name, "material_id": r.material_id,
        "category": r.material.category, "unit": r.material.unit,
        "supplier": r.supplier.name if r.supplier else None, "supplier_id": r.supplier_id,
        "brand": r.brand, "unit_price": num(r.unit_price), "tax_pct": r.tax_pct,
        "delivery_charge": num(r.delivery_charge), "moq": r.moq,
        "quotation_date": r.quotation_date, "valid_until": r.valid_until,
        "source_type": r.source_type, "available": r.available,
    }


def task(t: m.Task) -> dict:
    return {
        "id": t.id, "name": t.name, "duration_days": t.duration_days,
        "start_date": t.start_date, "progress": t.progress,
        "priority": t.priority, "assignee": t.assignee, "milestone": t.milestone,
        "notes": t.notes, "depends_on": [d.depends_on_id for d in t.deps],
        "actual_completion": t.actual_completion,
    }


def document(d: m.Document) -> dict:
    return {
        "id": d.id, "name": d.name, "category": d.category, "version": d.version,
        "project_id": d.project_id, "source": d.source, "source_url": d.source_url,
        "published_on": d.published_on, "location_scope": d.location_scope,
        "pages": d.page_count, "chunks": d.chunk_count, "size_bytes": d.size_bytes,
        "index_status": d.index_status, "uploaded_at": d.created_at,
    }


def notification(n: m.Notification) -> dict:
    return {
        "id": n.id, "kind": n.kind, "kind_label": label(NOTIFICATION_KINDS, n.kind),
        "category": n.category, "priority": n.priority, "subject": n.subject,
        "body": n.body, "status": n.status, "attempts": n.attempts, "error": n.error,
        "project_id": n.project_id, "link": n.link, "read": n.read_at is not None,
        "archived": n.archived, "created_at": n.created_at, "sent_at": n.sent_at,
    }


def user(u: m.User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": u.name, "role": u.role,
        "role_label": P.role_label(u.role), "theme": u.theme, "units": u.units,
        "currency": u.currency, "timezone": u.timezone, "notify_email": u.notify_email,
        "capabilities": sorted(P.capabilities(u.role)),
    }


def safe_json(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
