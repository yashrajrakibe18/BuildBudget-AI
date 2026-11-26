"""Labour management: agreed rates, actual attendance and cost roll-up."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app import models as m
from app.core import permissions as P
from app.services import activity

D = Decimal


def cost(workers: int, days: float, rate: float, hours_per_day: float = 8.0,
         rate_type: str = "per_day") -> Decimal:
    if workers <= 0:
        raise ValueError("Number of workers must be at least 1")
    if days <= 0:
        raise ValueError("Days must be greater than zero")
    if rate < 0:
        raise ValueError("Rate cannot be negative")
    if rate_type == "per_hour":
        return (D(str(rate)) * D(str(workers)) * D(str(days)) * D(str(hours_per_day))).quantize(D("0.01"))
    if rate_type == "per_sqft":
        return (D(str(rate)) * D(str(days))).quantize(D("0.01"))
    return (D(str(rate)) * D(str(workers)) * D(str(days))).quantize(D("0.01"))


def add_entry(db: Session, user: m.User, project: m.Project, *, category: str, workers: int,
              days: float, rate: float, contractor: str = "", rate_type: str = "per_day",
              hours_per_day: float = 8.0, work_date: date | None = None,
              note: str = "") -> m.LabourEntry:
    P.assert_can(user, "labour.write")
    total_rate = cost(workers, days, rate, hours_per_day, rate_type)
    entry = m.LabourEntry(project_id=project.id, category=category, contractor=contractor,
                          workers=workers, days=days, hours_per_day=hours_per_day,
                          rate=D(str(rate)), rate_type=rate_type,
                          work_date=work_date or date.today(), note=note, created_by=user.id)
    db.add(entry)
    activity.log(db, user_id=user.id, project_id=project.id, action="labour_logged",
                 entity="labour", summary=f"{category}: {workers} worker(s) x {days} day(s) = {total_rate}")
    db.commit()
    return entry


def summary(db: Session, project_id: int, rates: dict[str, float] | None = None) -> dict:
    entries = (db.query(m.LabourEntry).filter_by(project_id=project_id)
               .order_by(m.LabourEntry.work_date.desc()).all())
    total = sum(cost(e.workers, e.days, float(e.rate), e.hours_per_day, e.rate_type) for e in entries)
    by_category: dict[str, dict] = {}
    by_contractor: dict[str, float] = {}
    for e in entries:
        c = cost(e.workers, e.days, float(e.rate), e.hours_per_day, e.rate_type)
        bucket = by_category.setdefault(e.category, {"cost": 0.0, "worker_days": 0.0})
        bucket["cost"] += float(c)
        bucket["worker_days"] += e.workers * e.days
        if e.contractor:
            by_contractor[e.contractor] = by_contractor.get(e.contractor, 0.0) + float(c)
    return {
        "entries": [{
            "id": e.id, "category": e.category, "contractor": e.contractor,
            "workers": e.workers, "days": e.days, "hours_per_day": e.hours_per_day,
            "rate": float(e.rate), "rate_type": e.rate_type, "work_date": e.work_date,
            "note": e.note,
            "total": float(cost(e.workers, e.days, float(e.rate), e.hours_per_day, e.rate_type)),
        } for e in entries],
        "total_cost": round(float(total), 2),
        "worker_days": round(sum(e.workers * e.days for e in entries), 2),
        "by_category": [{"category": k, **{kk: round(vv, 2) for kk, vv in v.items()}}
                        for k, v in sorted(by_category.items(), key=lambda kv: -kv[1]["cost"])],
        "by_contractor": [{"contractor": k, "cost": round(v, 2)}
                          for k, v in sorted(by_contractor.items(), key=lambda kv: -kv[1])],
        "note": "Only labour entries you record are included. Rates are the ones you entered or approved.",
    }
