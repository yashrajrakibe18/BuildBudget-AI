"""Data-science features on real project records (NumPy; no fabricated output).

Techniques and their honest limits:
* trend        — ordinary least squares on monthly totals (needs >= 3 months)
* forecast     — OLS with a held-out tail for MAE/MAPE (needs >= forecast_min_months)
* anomalies    — robust z-score using median and MAD (a justified, explainable
                 alternative to Isolation Forest on small samples)
* health/risk  — transparent weighted rules, not a black box
When history is too short every function returns `sufficient: False` and the UI
prints "Insufficient data for reliable forecasting" instead of a made-up number.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import median

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models as m
from app.core.config import settings
from app.services import budget as budget_svc


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_range(end: date, count: int) -> list[str]:
    out = []
    y, mo = end.year, end.month
    for _ in range(count):
        out.append(f"{y:04d}-{mo:02d}")
        mo -= 1
        if mo == 0:
            mo, y = 12, y - 1
    return list(reversed(out))


def expense_series(db: Session, owner_id: int, project_id: int | None = None,
                   months: int = 12, today: date | None = None) -> list[dict]:
    today = today or date.today()
    start = date(today.year - 2, 1, 1)
    q = (db.query(m.Expense.expense_date, m.Expense.amount, m.Expense.category)
         .join(m.Project, m.Expense.project_id == m.Project.id)
         .filter(m.Project.owner_id == owner_id, m.Expense.expense_date >= start))
    if project_id:
        q = q.filter(m.Expense.project_id == project_id)
    buckets: dict[str, float] = {k: 0.0 for k in _month_range(today, months)}
    cat_buckets: dict[str, dict[str, float]] = {}
    for d, amount, cat in q.all():
        key = _month_key(d)
        if key in buckets:
            buckets[key] += float(amount)
            cat_buckets.setdefault(key, {})
            cat_buckets[key][cat] = cat_buckets[key].get(cat, 0.0) + float(amount)
    return [{"month": k, "total": round(v, 2), "by_category": cat_buckets.get(k, {})}
            for k, v in sorted(buckets.items())]


def trend_analysis(series: list[dict]) -> dict:
    values = [r["total"] for r in series if r["total"] > 0]
    if len(values) < 3:
        return {"sufficient": False,
                "message": "Insufficient data for a reliable trend (at least 3 months with expenses are needed)."}
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum()) or 1.0
    r2 = 1 - ss_res / ss_tot
    direction = "rising" if slope > 0 else "falling" if slope < 0 else "flat"
    return {
        "sufficient": True,
        "months_used": len(values),
        "slope_per_month": round(float(slope), 2),
        "average": round(float(y.mean()), 2),
        "latest": round(float(y[-1]), 2),
        "direction": direction,
        "r_squared": round(r2, 3),
        "message": f"Spending is {direction} by about {abs(float(slope)):,.0f} per month "
                   f"(R² {r2:.2f}, {len(values)} months).",
        "limitation": "Linear fit on recorded expenses only; a few large invoices can dominate the slope.",
    }


def forecast_expenses(series: list[dict], horizon: int = 3) -> dict:
    values = [r["total"] for r in series if r["total"] > 0]
    minimum = max(4, settings.forecast_min_months)
    if len(values) < minimum:
        return {"sufficient": False,
                "message": f"Insufficient data for reliable forecasting "
                           f"({len(values)} of {minimum} months with expenses)."}
    y = np.array(values, dtype=float)
    holdout = min(3, len(values) // 3)
    train, test = y[:-holdout], y[-holdout:]
    xtr = np.arange(len(train), dtype=float)
    if len(train) >= 2:
        slope, intercept = np.polyfit(xtr, train, 1)
    else:
        slope, intercept = 0.0, float(train.mean())
    xte = np.arange(len(train), len(train) + len(test), dtype=float)
    pred_test = slope * xte + intercept
    mae = float(np.mean(np.abs(test - pred_test)))
    mape = float(np.mean(np.abs((test - pred_test) / np.where(test == 0, 1, test)))) * 100
    full_x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(full_x, y, 1)
    fx = np.arange(len(y), len(y) + horizon, dtype=float)
    forecast = [max(0.0, float(v)) for v in (slope * fx + intercept)]
    return {
        "sufficient": True,
        "method": "ordinary least squares on monthly totals with a held-out tail",
        "forecast": [round(v, 2) for v in forecast],
        "expected_total": round(sum(forecast), 2),
        "validation": {"holdout_months": holdout, "mae": round(mae, 2), "mape_pct": round(mape, 1)},
        "message": f"Next {horizon} months ≈ {sum(forecast):,.0f} total "
                   f"(holdout MAE {mae:,.0f}, MAPE {mape:.0f}%).",
        "limitation": ("Small samples and lumpy construction spending make this indicative only. "
                       "Treat it as a planning signal, not a commitment."),
    }


def detect_unusual_expenses(db: Session, owner_id: int, project_id: int | None = None,
                            threshold: float | None = None) -> dict:
    threshold = threshold or settings.anomaly_z_threshold
    q = (db.query(m.Expense, m.Project.name)
         .join(m.Project, m.Expense.project_id == m.Project.id)
         .filter(m.Project.owner_id == owner_id))
    if project_id:
        q = q.filter(m.Expense.project_id == project_id)
    rows = [(e, name) for e, name in q.all()]
    if len(rows) < 5:
        return {"sufficient": False,
                "message": "Insufficient data: at least 5 recorded expenses are needed to detect anomalies.",
                "anomalies": []}
    amounts = np.array([float(e.amount) for e, _ in rows])
    med = float(median(amounts))
    mad = float(median(np.abs(amounts - med)))
    scale = mad * 1.4826 if mad > 0 else float(amounts.std(ddof=0)) or 1.0
    out = []
    for (e, project_name) in rows:
        z = (float(e.amount) - med) / scale
        if abs(z) >= threshold:
            out.append({
                "expense_id": e.id, "project": project_name, "category": e.category,
                "amount": float(e.amount), "date": e.expense_date.isoformat(),
                "vendor": e.vendor, "score": round(z, 2),
                "reason": f"{abs(z):.1f} robust deviations from the median expense ({med:,.0f})",
            })
    out.sort(key=lambda r: -abs(r["score"]))
    return {"sufficient": True, "method": "robust z-score (median/MAD)",
            "threshold": threshold, "median_expense": round(med, 2),
            "anomalies": out[:20],
            "message": (f"{len(out)} expense(s) flagged from {len(rows)} records."
                        if out else "No unusual expenses detected."),
            "limitation": "Statistical outlier ≠ fraud. Large legitimate invoices can be flagged; review before acting."}


def budget_risk(db: Session, projects: list[m.Project], today: date | None = None) -> list[dict]:
    today = today or date.today()
    out = []
    for p in projects:
        s = budget_svc.summary(db, p)
        budget = s["approved_budget"]
        actual = s["actual_expenses"]
        if budget <= 0:
            out.append({"project_id": p.id, "project": p.name, "risk": "unknown",
                        "message": "No approved budget set, so overrun risk cannot be assessed."})
            continue
        start = p.start_date or (today - timedelta(days=30))
        end = p.end_date or (start + timedelta(days=90))
        total_days = max(1, (end - start).days)
        elapsed = max(1, min(total_days, (today - start).days))
        burn = actual / elapsed
        projected = burn * total_days
        ratio = projected / budget if budget else 0
        risk = "high" if ratio > 1.15 else "medium" if ratio > 1.0 else "low"
        out.append({
            "project_id": p.id, "project": p.name, "risk": risk,
            "elapsed_days": elapsed, "total_days": total_days,
            "daily_burn": round(burn, 2), "projected_total": round(projected, 2),
            "budget": round(budget, 2), "projected_ratio": round(ratio, 2),
            "message": f"At the current burn rate the project would spend about {projected:,.0f} "
                       f"against a budget of {budget:,.0f}.",
            "limitation": "Assumes a constant burn rate from start date to end date.",
        })
    return out


def material_consumption(db: Session, owner_id: int, project_id: int | None = None) -> list[dict]:
    q = (db.query(m.InventoryItem.material_name, m.InventoryItem.unit,
                  func.sum(m.InventoryTxn.quantity))
         .join(m.InventoryTxn, m.InventoryTxn.item_id == m.InventoryItem.id)
         .join(m.Project, m.InventoryItem.project_id == m.Project.id)
         .filter(m.Project.owner_id == owner_id, m.InventoryTxn.kind == "consumed"))
    if project_id:
        q = q.filter(m.InventoryItem.project_id == project_id)
    rows = q.group_by(m.InventoryItem.material_name, m.InventoryItem.unit).all()
    return [{"material": name, "unit": unit, "consumed": round(float(qty or 0), 2)}
            for name, unit, qty in sorted(rows, key=lambda r: -(r[2] or 0))]


def supplier_performance(db: Session, owner_id: int) -> dict:
    suppliers = db.query(m.Supplier).filter_by(owner_id=owner_id).all()
    rows = []
    for s in suppliers:
        pos = (db.query(m.PurchaseOrder)
               .filter(m.PurchaseOrder.supplier_id == s.id).all())
        delivered = [p for p in pos if p.received_date and p.expected_date]
        on_time = [p for p in delivered if p.received_date <= p.expected_date]
        quotes = db.query(m.MaterialPrice).filter_by(owner_id=owner_id, supplier_id=s.id).count()
        if not delivered and not pos:
            rows.append({"supplier": s.name, "supplier_id": s.id, "orders": 0, "delivered": 0,
                         "on_time_pct": None, "quotes": quotes,
                         "note": "No purchase history yet — performance cannot be scored."})
            continue
        rows.append({
            "supplier": s.name, "supplier_id": s.id, "orders": len(pos), "delivered": len(delivered),
            "on_time_pct": round(100 * len(on_time) / len(delivered), 1) if delivered else None,
            "quotes": quotes,
            "note": "" if delivered else "Orders exist but no delivery dates recorded yet.",
        })
    scored = [r for r in rows if r["on_time_pct"] is not None]
    return {"rows": rows, "scored": len(scored),
            "sufficient": len(scored) >= 2,
            "message": ("Supplier reliability is computed from recorded purchase order deliveries."
                        if scored else "Insufficient delivery history for supplier scoring.")}


def project_health(db: Session, project: m.Project) -> dict:
    s = budget_svc.summary(db, project)
    tasks = db.query(m.Task).filter_by(project_id=project.id).all()
    today = date.today()
    overdue = [t for t in tasks if t.start_date and t.progress < 100
               and t.start_date + timedelta(days=t.duration_days) < today]
    avg_progress = round(sum(t.progress for t in tasks) / len(tasks), 1) if tasks else 0.0
    score = 100.0
    factors = []
    util = s["utilization_pct"]
    if util is None:
        score -= 10
        factors.append(("No budget set", -10))
    elif util > 100:
        score -= 40
        factors.append((f"Over budget ({util}%)", -40))
    elif util >= 90:
        score -= 22
        factors.append((f"Budget almost exhausted ({util}%)", -22))
    elif util >= 75:
        score -= 8
        factors.append((f"Budget at {util}%", -8))
    if overdue:
        penalty = min(30, 6 * len(overdue))
        score -= penalty
        factors.append((f"{len(overdue)} overdue task(s)", -penalty))
    if tasks and avg_progress < 35 and project.status == "active":
        score -= 10
        factors.append((f"Low progress ({avg_progress}%)", -10))
    if not tasks:
        factors.append(("No schedule yet — health is budget-only", 0))
    score = max(0, min(100, round(score)))
    band = "healthy" if score >= 75 else "watch" if score >= 50 else "at_risk"
    return {"project_id": project.id, "project": project.name, "score": score, "band": band,
            "factors": factors, "overdue_tasks": len(overdue), "avg_progress": avg_progress,
            "budget_status": s["status"], "utilization_pct": util}
