from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models as m

D = Decimal


def contingency(amount, pct) -> Decimal:
    if pct < 0:
        raise ValueError("pct must be >= 0")
    return (D(str(amount)) * D(str(pct)) / 100).quantize(D("0.01"))


def summary(db: Session, project: m.Project, revision: int | None = None) -> dict:
    rev = revision or db.query(func.max(m.BOQItem.revision)).filter_by(project_id=project.id).scalar()
    est = D(0)
    if rev:
        est = db.query(func.coalesce(func.sum(m.BOQItem.total), 0)).filter_by(
            project_id=project.id, revision=rev).scalar() or D(0)
    actual = db.query(func.coalesce(func.sum(m.Expense.amount), 0)).filter_by(project_id=project.id).scalar() or D(0)
    budget = D(str(project.budget or 0))
    est, actual = D(str(est)), D(str(actual))
    util = float((actual / budget * 100).quantize(D("0.1"))) if budget > 0 else None
    by_cat = {c: float(a) for c, a in db.query(m.Expense.category, func.sum(m.Expense.amount))
              .filter_by(project_id=project.id).group_by(m.Expense.category)}
    status = "no_budget" if budget <= 0 else ("over_budget" if actual > budget else
             "critical" if util >= 90 else "warning" if util >= 75 else "ok")
    return {"project_id": project.id, "approved_budget": float(budget), "estimated_cost": float(est),
            "boq_revision": rev, "actual_expenses": float(actual), "remaining_budget": float(budget - actual),
            "variance_estimate_vs_actual": float(est - actual), "estimate_vs_budget": float(budget - est),
            "utilization_pct": util, "status": status, "expenses_by_category": by_cat,
            "note": "Estimate covers only BOQ items entered; structural scope may be pending professional input."}
