"""Dashboard aggregation. Every number comes from the database; nothing is hardcoded."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import models as m
from app.services import analytics
from app.services import budget as budget_svc


def visible_projects(db: Session, user: m.User) -> list[m.Project]:
    q = db.query(m.Project)
    if user.role != "admin":
        q = q.filter_by(owner_id=user.id)
    return q.order_by(m.Project.id.desc()).all()


def _filtered(projects: list[m.Project], *, project_id: int | None, status: str | None,
              location: str | None, include_archived: bool) -> list[m.Project]:
    out = []
    for p in projects:
        if not include_archived and p.archived:
            continue
        if project_id and p.id != project_id:
            continue
        if status and p.status != status:
            continue
        if location and location.lower() not in (p.location or "").lower():
            continue
        out.append(p)
    return out


def overview(db: Session, user: m.User, *, project_id: int | None = None, status: str | None = None,
             location: str | None = None, months: int = 12, date_from: date | None = None,
             date_to: date | None = None, include_archived: bool = False) -> dict:
    all_projects = visible_projects(db, user)
    projects = _filtered(all_projects, project_id=project_id, status=status,
                         location=location, include_archived=include_archived)
    ids = [p.id for p in projects]
    summaries = [budget_svc.summary(db, p) for p in projects]

    def total(key):
        return round(sum(s[key] for s in summaries), 2)

    today = date.today()
    pending_approvals = (db.query(m.ApprovalRequest)
                         .filter_by(user_id=user.id, status="pending").count())
    unread = (db.query(m.Notification)
              .filter(m.Notification.owner_id == user.id, m.Notification.read_at.is_(None),
                      m.Notification.archived.is_(False)).count())

    low_stock = 0
    overdue_tasks: list[dict] = []
    expenses_by_category: dict[str, float] = {}
    monthly: dict[str, float] = {}
    project_rows = []
    health_bands = {"healthy": 0, "watch": 0, "at_risk": 0}
    upcoming: list[dict] = []

    if ids:
        items = (db.query(m.InventoryItem).filter(m.InventoryItem.project_id.in_(ids)).all())
        low_stock = sum(1 for i in items if i.reorder_level > 0 and i.available <= i.reorder_level)

        tasks = db.query(m.Task).filter(m.Task.project_id.in_(ids)).all()
        names = {p.id: p.name for p in projects}
        overdue_tasks = [{
            "id": t.id, "name": t.name, "project": names.get(t.project_id, ""),
            "project_id": t.project_id,
            "planned_end": (t.start_date + timedelta(days=t.duration_days)).isoformat(),
            "days_late": (today - (t.start_date + timedelta(days=t.duration_days))).days,
            "progress": t.progress,
        } for t in tasks if t.start_date and t.progress < 100
            and t.start_date + timedelta(days=t.duration_days) < today]
        overdue_tasks.sort(key=lambda r: -r["days_late"])
        upcoming = [{
            "task": t.name, "project": names.get(t.project_id, ""), "project_id": t.project_id,
            "due": (t.start_date + timedelta(days=t.duration_days)).isoformat(),
            "progress": t.progress, "priority": t.priority,
        } for t in tasks if t.start_date and t.progress < 100
            and today <= t.start_date + timedelta(days=t.duration_days) <= today + timedelta(days=21)]
        upcoming.sort(key=lambda r: r["due"])

        eq = (db.query(m.Expense.category, m.Expense.expense_date, m.Expense.amount)
              .filter(m.Expense.project_id.in_(ids)))
        if date_from:
            eq = eq.filter(m.Expense.expense_date >= date_from)
        if date_to:
            eq = eq.filter(m.Expense.expense_date <= date_to)
        for cat, d, amount in eq.all():
            key = d.strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + float(amount)
            expenses_by_category[cat] = expenses_by_category.get(cat, 0) + float(amount)

        for p, s in zip(projects, summaries, strict=True):
            health = analytics.project_health(db, p)
            health_bands[health["band"]] = health_bands.get(health["band"], 0) + 1
            p_tasks = [t for t in tasks if t.project_id == p.id]
            progress = round(sum(t.progress for t in p_tasks) / len(p_tasks), 1) if p_tasks else 0.0
            row = {
                "id": p.id, "name": p.name, "project_type": p.project_type, "location": p.location,
                "status": "archived" if p.archived else p.status, "archived": p.archived,
                "start_date": p.start_date, "end_date": p.end_date,
                "manager_name": p.manager_name, "progress": progress,
                "health": health["band"], "health_score": health["score"],
                "is_demo": p.is_demo, **s,
            }
            # `s` carries the *budget* status; keep the project status separately so the
            # UI never shows "Ok" where an active project is expected.
            row["budget_status"] = s["status"]
            row["status"] = "archived" if p.archived else p.status
            project_rows.append(row)

    series = analytics.expense_series(db, user.id, project_id, months=months)
    approved = total("approved_budget")
    actual = total("actual_expenses")
    utilization = round(actual / approved * 100, 1) if approved > 0 else None
    over_budget = [r for r in project_rows if r["status"] != "archived"
                   and r["approved_budget"] > 0 and r["actual_expenses"] > r["approved_budget"]]

    return {
        "generated_at": m.now(),
        "currency": "INR",
        "filters": {"project_id": project_id, "status": status, "location": location,
                    "months": months, "date_from": date_from, "date_to": date_to},
        "kpis": {
            "total_projects": len(projects),
            "active_projects": sum(1 for p in projects if p.status not in ("completed", "cancelled") and not p.archived),
            "completed_projects": sum(1 for p in projects if p.status == "completed"),
            "archived_projects": sum(1 for p in all_projects if p.archived),
            "approved_budget": approved,
            "estimated_cost": total("estimated_cost"),
            "actual_expenses": actual,
            "remaining_budget": round(approved - actual, 2),
            "budget_utilization_pct": utilization,
            "over_budget_projects": len(over_budget),
            "low_stock_items": low_stock,
            "overdue_tasks": len(overdue_tasks),
            "pending_approvals": pending_approvals,
            "unread_notifications": unread,
            "boq_items_estimated": total("estimated_cost"),
        },
        "monthly_expenses": dict(sorted(monthly.items())),
        "expenses_by_category": expenses_by_category,
        "expense_series": series,
        "projects": project_rows,
        "health_distribution": health_bands,
        "overdue_task_list": overdue_tasks[:8],
        "upcoming_deadlines": upcoming[:8],
        "budget_alerts": [{"project": r["name"], "project_id": r["id"], "status": r["status"],
                           "utilization_pct": r["utilization_pct"]}
                          for r in project_rows if r["status"] in ("warning", "critical", "over_budget")],
        "insights": insights(project_rows, low_stock, len(overdue_tasks), pending_approvals, utilization),
        "notes": {
            "estimate_scope": ("Estimated cost covers only the BOQ items you have entered. It is not a full "
                               "construction cost and excludes any structural work awaiting engineer approval."),
            "demo_data": any(p.is_demo for p in projects),
        },
    }


def insights(rows: list[dict], low_stock: int, overdue: int, approvals: int,
             utilization: float | None) -> list[dict]:
    """Grounded observations computed from the records above — not model output."""
    out: list[dict] = []
    for r in sorted(rows, key=lambda x: -(x.get("utilization_pct") or 0))[:3]:
        util = r.get("utilization_pct")
        if util is not None and util >= 90:
            out.append({"tone": "critical", "project_id": r["id"],
                        "title": f"{r['name']} is at {util}% of budget",
                        "detail": f"₹{r['actual_expenses']:,.0f} spent of ₹{r['approved_budget']:,.0f}. "
                                  f"Review open commitments before approving more spend."})
        elif util is not None and util >= 75:
            out.append({"tone": "warning", "project_id": r["id"],
                        "title": f"{r['name']} has used {util}% of budget",
                        "detail": "Spending is in the watch band (75–90%)."})
    if low_stock:
        out.append({"tone": "warning", "title": f"{low_stock} material(s) at or below reorder level",
                    "detail": "Open Inventory to raise a purchase requirement.", "link": "/inventory"})
    if overdue:
        out.append({"tone": "critical", "title": f"{overdue} task(s) past their planned finish",
                    "detail": "Check the schedule and update progress or dates.", "link": "/schedule"})
    if approvals:
        out.append({"tone": "info", "title": f"{approvals} action(s) waiting for your approval",
                    "detail": "Nothing external is sent until you approve it.", "link": "/approvals"})
    if not rows:
        out.append({"tone": "info", "title": "No projects yet",
                    "detail": "Create your first project to unlock budgets, estimates and insights."})
    return out
