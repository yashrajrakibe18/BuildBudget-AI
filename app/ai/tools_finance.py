"""Project, BOQ, budget and expense tools."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from app import models as m
from app.ai.tools_core import ToolContext, ToolRegistry, inr
from app.services import approvals
from app.services import budget as budget_svc


class Empty(BaseModel):
    pass


class FindProjectIn(BaseModel):
    query: str = Field(description="Project name, part of a name, or numeric project id")


class ProjectDetailsIn(BaseModel):
    project_id: Optional[int] = None


class ActivityIn(BaseModel):
    limit: int = Field(10, ge=1, le=50)


class ExpenseDraftIn(BaseModel):
    category: str = Field(description="Materials, Labour, Equipment, Transportation, etc.")
    amount: float = Field(gt=0)
    description: str = ""
    vendor: str = ""
    invoice_no: Optional[str] = None


class ExpenseHistoryIn(BaseModel):
    limit: int = Field(20, ge=1, le=100)


class DuplicateIn(BaseModel):
    vendor: str
    invoice_no: str


class BoqDraftLine(BaseModel):
    material_name: str
    kind: str = Field(description="tiles | paint | primer | bricks | plaster | tile_adhesive")
    params: dict = Field(description="Validator parameters for the chosen estimator")
    unit_rate: Optional[float] = Field(None, ge=0, description="Price per unit; omit to use a stored quotation")
    labour_cost: float = Field(0, ge=0)
    category: str = "Finishing"


class BoqDraftIn(BaseModel):
    lines: list[BoqDraftLine] = Field(min_length=1, max_length=12)


class ProjectDraftIn(BaseModel):
    name: str
    project_type: str = "single_room"
    location: str = ""
    budget: float = Field(0, ge=0)
    description: str = ""
    manager_email: str = ""


class ProjectUpdateIn(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    budget: Optional[float] = Field(None, ge=0)
    status: Optional[str] = None
    manager_name: Optional[str] = None
    manager_email: Optional[str] = None


class RevisionIn(BaseModel):
    revision: Optional[int] = None


def register(reg: ToolRegistry) -> None:
    ctx: ToolContext = reg.ctx
    db = ctx.db
    user = ctx.user

    # ---------------- projects ----------------
    def list_projects() -> dict:
        rows = ctx.projects()
        return {
            "count": len(rows),
            "projects": [{
                "id": p.id, "name": p.name, "type": p.project_type, "status": p.status,
                "location": p.location, "budget": float(p.budget or 0),
                "archived": p.archived,
            } for p in rows[:40]],
            "summary": f"{len(rows)} project(s) available",
        }

    def find_project(query: str) -> dict:
        q = (query or "").strip()
        rows = ctx.projects()
        match = None
        if q.isdigit():
            match = next((p for p in rows if p.id == int(q)), None)
        if match is None:
            match = next((p for p in rows if p.name.lower() == q.lower()), None)
        if match is None:
            match = next((p for p in rows if q.lower() in p.name.lower()), None)
        if match is None:
            return {"found": False,
                    "message": f"No project matches '{q}'.",
                    "available": [p.name for p in rows[:10]],
                    "summary": f"No project matches '{q}'"}
        ctx.project_id = match.id
        ctx.resolved_by = f"find_project:{q}"
        return {"found": True, "project_id": match.id, "name": match.name,
                "type": match.project_type, "status": match.status, "location": match.location,
                "budget": float(match.budget or 0),
                "message": f"Using project '{match.name}' (#{match.id}).",
                "summary": f"Resolved project '{match.name}'"}

    def project_details(project_id: Optional[int] = None) -> dict:
        if project_id:
            ctx.project_id = project_id
        p = ctx.project()
        s = budget_svc.summary(db, p)
        tasks = db.query(m.Task).filter_by(project_id=p.id).all()
        return {
            "id": p.id, "name": p.name, "type": p.project_type, "status": p.status,
            "location": p.location, "latitude": p.latitude, "longitude": p.longitude,
            "contractor": p.contractor, "manager_name": p.manager_name,
            "manager_email": p.manager_email, "start_date": p.start_date, "end_date": p.end_date,
            "description": p.description, "assumptions": p.assumptions,
            "is_demo": p.is_demo, "tasks": len(tasks),
            "avg_progress": round(sum(t.progress for t in tasks) / len(tasks), 1) if tasks else 0,
            "budget": s,
            "summary": f"{p.name}: {p.status}, budget {inr(s['approved_budget'])}",
        }

    def project_status() -> dict:
        p = ctx.project()
        s = budget_svc.summary(db, p)
        tasks = db.query(m.Task).filter_by(project_id=p.id).all()
        today = date.today()
        overdue = [t.name for t in tasks if t.start_date and t.progress < 100
                   and t.start_date + timedelta(days=t.duration_days) < today]
        return {"name": p.name, "status": p.status, "tasks": len(tasks),
                "avg_progress": round(sum(t.progress for t in tasks) / len(tasks), 1) if tasks else 0,
                "overdue_tasks": overdue, "budget": s,
                "summary": f"{p.name}: {len(tasks)} task(s), {len(overdue)} overdue"}

    def project_activity(limit: int = 10) -> dict:
        p = ctx.project()
        rows = (db.query(m.ActivityLog).filter_by(project_id=p.id)
                .order_by(m.ActivityLog.id.desc()).limit(limit).all())
        return {"project": p.name, "activity": [
            {"action": r.action.replace("_", " ").title(), "summary": r.summary,
             "when": r.created_at} for r in rows],
            "count": len(rows),
            "summary": f"{len(rows)} recent activity item(s)"}

    def create_project_draft(name: str, project_type: str = "single_room", location: str = "",
                             budget: float = 0, description: str = "", manager_email: str = "") -> dict:
        a = approvals.create(
            db, user, action="create_project",
            payload={"name": name, "project_type": project_type, "location": location,
                     "budget": budget, "description": description, "manager_email": manager_email,
                     "status": "planning"},
            title=f"Create project: {name}",
            summary=(f"New {project_type.replace('_', ' ')} project at {location or 'unspecified location'} "
                     f"with a budget of {inr(budget)}. Nothing is created until you approve."),
            conversation_id=ctx.conversation_id,
        )
        return {"status": "approval_required", "approval_id": a.id,
                "message": f"Approval #{a.id} created. Approve it to create '{name}'.",
                "summary": f"Approval #{a.id} created for new project '{name}'"}

    def update_project_draft(**fields) -> dict:
        p = ctx.project()
        clean = {k: v for k, v in fields.items() if v is not None}
        if not clean:
            return {"status": "no_change", "message": "No changes supplied.", "summary": "No changes supplied"}
        before = {k: getattr(p, k) for k in clean if hasattr(p, k)}
        a = approvals.create(
            db, user, action="update_project", payload=clean, project_id=p.id,
            title=f"Update project: {p.name}",
            summary="Proposed changes: " + ", ".join(f"{k.replace('_', ' ')} → {v}" for k, v in clean.items()),
            before=before, conversation_id=ctx.conversation_id,
        )
        return {"status": "approval_required", "approval_id": a.id,
                "changes": clean, "before": before,
                "message": f"Approval #{a.id} created. Approve it to apply the changes.",
                "summary": f"Approval #{a.id} created for project update"}

    # ---------------- BOQ ----------------
    def latest_revision(p) -> int:
        from sqlalchemy import func
        return db.query(func.max(m.BOQItem.revision)).filter_by(project_id=p.id).scalar() or 1

    def get_boq(revision: Optional[int] = None) -> dict:
        p = ctx.project()
        rev = revision or latest_revision(p)
        items = (db.query(m.BOQItem).filter_by(project_id=p.id, revision=rev)
                 .order_by(m.BOQItem.item_no).all())
        return {"project": p.name, "revision": rev, "items": [
            {"item_no": i.item_no, "description": i.description, "category": i.category,
             "unit": i.unit, "quantity": i.quantity, "unit_rate": float(i.unit_rate),
             "labour_cost": float(i.labour_cost), "tax_pct": i.tax_pct, "total": float(i.total),
             "rate_source": i.rate_source, "approval_status": i.approval_status,
             "assumptions": i.assumptions} for i in items],
            "total": round(sum(float(i.total or 0) for i in items), 2),
            "summary": f"Revision {rev}: {len(items)} item(s), {inr(sum(float(i.total or 0) for i in items))}"}

    def calculate_boq_total(revision: Optional[int] = None) -> dict:
        data = get_boq(revision)
        return {"revision": data["revision"], "total": data["total"], "items": len(data["items"]),
                "formula": "sum(item.total) for the selected revision",
                "summary": f"BOQ total {inr(data['total'])}"}

    def create_boq_draft(lines: list[BoqDraftLine]) -> dict:
        from app.services import estimation
        p = ctx.project()
        prepared, missing = [], []
        for line in lines:
            try:
                est = estimation.run(line.kind, line.params)
            except ValueError as exc:
                missing.append(f"{line.material_name}: {exc}")
                continue
            rate = line.unit_rate
            source = "user_entered"
            if rate is None:
                from app.ai.tools_materials import latest_prices
                rows = latest_prices(db, user.id, line.material_name)
                if not rows:
                    missing.append(f"{line.material_name}: no stored price — add a quotation or give a unit rate")
                    continue
                rate = float(rows[0].unit_price)
                source = rows[0].source_type
            qty = float(est["final_quantity"])
            prepared.append({
                "kind": line.kind, "params": line.params, "material_name": line.material_name,
                "category": line.category, "unit_rate": rate, "labour_cost": line.labour_cost,
                "rate_source": source, "quantity": qty, "unit": est["unit"],
                "description": est["item"], "formula": est["formula"],
                "assumptions": "; ".join(est["assumptions"]),
            })
        if not prepared:
            return {"status": "needs_input", "missing": missing,
                    "message": "No BOQ lines could be priced. " + " | ".join(missing),
                    "summary": "BOQ draft needs prices"}
        a = approvals.create(
            db, user, action="add_boq_items",
            payload={"lines": prepared}, project_id=p.id,
            title=f"Add {len(prepared)} BOQ line(s) to {p.name}",
            summary="Quantities are calculated deterministically; unit rates come from your data.",
            conversation_id=ctx.conversation_id,
        )
        return {"status": "approval_required", "approval_id": a.id, "lines": prepared,
                "missing": missing,
                "message": f"Approval #{a.id} created with {len(prepared)} priced line(s).",
                "summary": f"BOQ draft with {len(prepared)} line(s) awaiting approval"}

    # ---------------- budget / expenses ----------------
    def get_project_budget() -> dict:
        p = ctx.project()
        s = budget_svc.summary(db, p)
        return {**s, "project": p.name,
                "summary": f"Budget {inr(s['approved_budget'])}, spent {inr(s['actual_expenses'])}, "
                           f"remaining {inr(s['remaining_budget'])}"}

    def budget_utilization() -> dict:
        s = get_project_budget()
        util = s["utilization_pct"]
        return {"project": s["project"], "utilization_pct": util,
                "formula": "actual expenses / approved budget * 100",
                "status": s["status"],
                "message": (f"{util}% of the approved budget has been spent." if util is not None
                            else "No approved budget is set, so utilisation is undefined."),
                "summary": f"Utilisation {util}%" if util is not None else "No budget set"}

    def budget_variance() -> dict:
        s = get_project_budget()
        return {"project": s["project"],
                "variance_actual_vs_budget": s["remaining_budget"],
                "variance_estimate_vs_actual": s["variance_estimate_vs_actual"],
                "estimate_vs_budget": s["estimate_vs_budget"],
                "note": "Positive numbers mean budget remains. Estimate variance compares the BOQ total "
                        "with recorded expenses, not with the final cost.",
                "summary": f"Remaining {inr(s['remaining_budget'])}"}

    def expense_history(limit: int = 20) -> dict:
        p = ctx.project()
        rows = (db.query(m.Expense).filter_by(project_id=p.id)
                .order_by(m.Expense.expense_date.desc()).limit(limit).all())
        return {"project": p.name, "count": len(rows), "expenses": [
            {"id": e.id, "date": e.expense_date.isoformat(), "category": e.category,
             "amount": float(e.amount), "vendor": e.vendor, "invoice_no": e.invoice_no,
             "description": e.description} for e in rows],
            "total": round(sum(float(e.amount) for e in rows), 2),
            "summary": f"{len(rows)} expense(s) listed"}

    def duplicate_invoice(vendor: str, invoice_no: str) -> dict:
        p = ctx.project()
        hit = (db.query(m.Expense)
               .filter_by(project_id=p.id, vendor=vendor, invoice_no=invoice_no).first())
        return {"duplicate": bool(hit), "vendor": vendor, "invoice_no": invoice_no,
                "existing_expense_id": hit.id if hit else None,
                "message": ("A matching invoice already exists for this project — do not record it again."
                            if hit else "No duplicate found for this vendor and invoice number."),
                "summary": "Duplicate invoice found" if hit else "No duplicate invoice"}

    def record_expense_draft(category: str, amount: float, description: str = "",
                             vendor: str = "", invoice_no: Optional[str] = None) -> dict:
        p = ctx.project()
        if invoice_no and vendor:
            dup = (db.query(m.Expense)
                   .filter_by(project_id=p.id, vendor=vendor, invoice_no=invoice_no).first())
            if dup:
                return {"status": "duplicate", "message": "That invoice is already recorded for this project.",
                        "summary": "Duplicate invoice blocked"}
        a = approvals.create(
            db, user, action="record_expense",
            payload={"category": category, "amount": amount, "description": description,
                     "vendor": vendor, "invoice_no": invoice_no,
                     "expense_date": date.today().isoformat()},
            project_id=p.id, title=f"Record expense: {inr(amount)} {category}",
            summary=f"{description or category} from {vendor or 'unspecified vendor'}",
            conversation_id=ctx.conversation_id,
        )
        return {"status": "approval_required", "approval_id": a.id,
                "message": f"The expense was NOT recorded. Approval #{a.id} is waiting for you.",
                "summary": f"Expense approval #{a.id} created"}

    reg.add("list_projects", "List the user's projects with id, type, status and budget.", Empty,
            list_projects)
    reg.add("find_project", "Resolve a project by name or id and select it for the rest of this request.",
            FindProjectIn, find_project)
    reg.add("get_project_details", "Full project record including budget, schedule size and contacts.",
            ProjectDetailsIn, project_details)
    reg.add("get_project_status", "Current status, progress and overdue count for the selected project.",
            Empty, project_status)
    reg.add("get_project_activity", "Recent audit-log entries for the selected project.", ActivityIn,
            project_activity)
    reg.add("create_project_draft", "Draft a new project (requires human approval before creation).",
            ProjectDraftIn, create_project_draft, write=True, capability="project.create")
    reg.add("update_project_draft", "Propose changes to the selected project (requires approval).",
            ProjectUpdateIn, update_project_draft, write=True, capability="project.edit")
    reg.add("get_boq", "Read the bill of quantities for a revision.", RevisionIn, get_boq)
    reg.add("calculate_boq_total", "Sum the current BOQ revision.", RevisionIn, calculate_boq_total)
    reg.add("create_boq_draft",
            "Build a priced BOQ draft from calculator quantities and stored prices (requires approval).",
            BoqDraftIn, create_boq_draft, write=True, capability="boq.write")
    reg.add("get_project_budget", "Budget summary: approved, estimated, actual, remaining, utilisation.",
            Empty, get_project_budget, needs_project=True)
    reg.add("calculate_budget_utilization", "Percentage of the approved budget already spent.",
            Empty, budget_utilization, needs_project=True)
    reg.add("calculate_budget_variance", "Variance between budget, BOQ estimate and actual spend.",
            Empty, budget_variance, needs_project=True)
    reg.add("get_expense_history", "Recent expenses for the project.", ExpenseHistoryIn, expense_history,
            needs_project=True)
    reg.add("detect_duplicate_invoice", "Check whether a vendor invoice number is already recorded.",
            DuplicateIn, duplicate_invoice)
    reg.add("record_project_expense", "Propose recording an expense (needs human approval).",
            ExpenseDraftIn, record_expense_draft, write=True, capability="expense.write")
    reg.add("record_expense_draft", "Alias of record_project_expense: draft an expense for approval.",
            ExpenseDraftIn, record_expense_draft, write=True, capability="expense.write")
