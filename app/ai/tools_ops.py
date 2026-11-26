"""Scheduling, weather, knowledge-base, analytics and reporting tools."""
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app import models as m
from app.ai.tools_core import ToolContext, ToolRegistry
from app.services import analytics, approvals, rag, reporting, scheduling, weather

REPORT_DIR = Path("reports/generated")


class Empty(BaseModel):
    pass


class DaysIn(BaseModel):
    days: int = Field(3, ge=1, le=7)


class TaskDraftIn(BaseModel):
    name: str
    duration_days: int = Field(gt=0)
    start_date: Optional[date] = None
    depends_on_names: list[str] = []
    priority: str = "normal"
    assignee: str = ""
    milestone: bool = False
    notes: str = ""


class KnowledgeIn(BaseModel):
    query: str
    category: Optional[str] = None
    k: int = Field(5, ge=1, le=10)


class DocIn(BaseModel):
    document_id: Optional[int] = None


class TrendIn(BaseModel):
    months: int = Field(12, ge=3, le=36)


class ForecastIn(BaseModel):
    horizon: int = Field(3, ge=1, le=6)


class ReportIn(BaseModel):
    pass


def project_pack(db, project) -> tuple:
    """Budget summary, BOQ items, expenses, schedule plan and labour for one project."""
    from sqlalchemy import func

    from app.services import budget as budget_svc
    from app.services import labour as labour_svc

    summary = budget_svc.summary(db, project)
    rev = db.query(func.max(m.BOQItem.revision)).filter_by(project_id=project.id).scalar() or 1
    items = (db.query(m.BOQItem).filter_by(project_id=project.id, revision=rev)
             .order_by(m.BOQItem.item_no).all())
    exps = (db.query(m.Expense).filter_by(project_id=project.id)
            .order_by(m.Expense.expense_date).all())
    tasks = db.query(m.Task).filter_by(project_id=project.id).all()
    plan = scheduling.calendar_plan([{"id": t.id, "name": t.name, "duration": t.duration_days,
                                     "deps": [d.depends_on_id for d in t.deps],
                                     "start_date": t.start_date, "progress": t.progress,
                                     "priority": t.priority, "assignee": t.assignee,
                                     "milestone": t.milestone} for t in tasks], project.start_date)
    lab = labour_svc.summary(db, project.id)
    return summary, items, exps, plan, lab


def _save(data: bytes, ext: str, title: str) -> dict:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (REPORT_DIR / name).write_bytes(data)
    return {"file": name, "download_url": f"/api/v1/reports/files/{name}", "title": title,
            "size_bytes": len(data)}


def register(reg: ToolRegistry) -> None:
    ctx: ToolContext = reg.ctx
    db = ctx.db
    user = ctx.user

    def _tasks(project) -> list[dict]:
        rows = db.query(m.Task).filter_by(project_id=project.id).all()
        return [{"id": t.id, "name": t.name, "duration": t.duration_days,
                 "deps": [dep.depends_on_id for dep in t.deps], "start_date": t.start_date,
                 "progress": t.progress, "priority": t.priority, "assignee": t.assignee,
                 "milestone": t.milestone} for t in rows]

    # ------------------------- scheduling -------------------------
    def project_schedule() -> dict:
        p = ctx.project()
        plan = scheduling.calendar_plan(_tasks(p), p.start_date)
        return {"project": p.name, **plan,
                "summary": (f"Planned finish {plan.get('project_finish') or '—'}, "
                            f"{len(plan.get('overdue', []))} overdue")}

    def critical_path_tool() -> dict:
        p = ctx.project()
        data = scheduling.critical_path(_tasks(p))
        return {**data, "summary": f"Critical path {data['total_duration_days']} working days"}

    def overdue_tasks() -> dict:
        p = ctx.project()
        today = date.today()
        rows = []
        for t in db.query(m.Task).filter_by(project_id=p.id).all():
            if t.start_date and t.progress < 100:
                end = t.start_date + __import__("datetime").timedelta(days=t.duration_days)
                if end < today:
                    rows.append({"name": t.name, "planned_finish": end.isoformat(),
                                 "days_late": (today - end).days, "progress": t.progress})
        return {"project": p.name, "overdue": rows, "count": len(rows),
                "summary": f"{len(rows)} overdue task(s)"}

    def weather_tool(days: int = 3) -> dict:
        p = ctx.project()
        if p.latitude is None or p.longitude is None:
            return {"available": False,
                    "message": "This project has no coordinates. Add them to get a forecast.",
                    "summary": "No coordinates for weather"}
        return weather.forecast(p.latitude, p.longitude, days)

    def variance_tool() -> dict:
        p = ctx.project()
        plan = scheduling.calendar_plan(_tasks(p), p.start_date)
        v = scheduling.schedule_variance(plan["rows"])
        return {"project": p.name, **v, "summary": f"Schedule progress {v['progress_pct']}%"}

    def create_task(name: str, duration_days: int, start_date: Optional[date] = None,
                    depends_on_names: list[str] = (), priority: str = "normal",
                    assignee: str = "", milestone: bool = False, notes: str = "") -> dict:
        p = ctx.project()
        existing = {t.name.lower(): t.id for t in db.query(m.Task).filter_by(project_id=p.id)}
        deps, unknown = [], []
        for dep_name in depends_on_names:
            key = dep_name.strip().lower()
            if key in existing:
                deps.append(existing[key])
            else:
                unknown.append(dep_name)
        if unknown:
            return {"status": "needs_input",
                    "message": f"Unknown dependency task(s): {', '.join(unknown)}. "
                               f"Existing tasks: {', '.join(n for n in existing) or 'none'}.",
                    "summary": "Unknown dependency"}
        a = approvals.create(
            db, user, action="create_task",
            payload={"name": name, "duration": duration_days,
                     "start_date": start_date.isoformat() if start_date else None,
                     "depends_on": deps, "priority": priority, "assignee": assignee,
                     "milestone": milestone, "notes": notes},
            project_id=p.id, title=f"Create task: {name}",
            summary=f"{duration_days} day(s), depends on {len(deps)} task(s).",
            conversation_id=ctx.conversation_id)
        return {"status": "approval_required", "approval_id": a.id,
                "message": f"Approval #{a.id} created; the task is not scheduled yet.",
                "summary": f"Task approval #{a.id} created"}

    # ------------------------- knowledge -------------------------
    def knowledge_search(query: str, category: Optional[str] = None, k: int = 5) -> dict:
        hits = rag.search(db, user.id, query, ctx.project_id, category, k=k)
        if not hits:
            return {"found": False,
                    "message": "No supporting passage found in the indexed documents. "
                               "I cannot verify this from your knowledge base.",
                    "summary": "No matching document passage"}
        return {"found": True, "query": query, "results": hits,
                "context": rag.wrap_untrusted(hits),
                "citation_rule": "Cite only these passage numbers; do not invent page numbers.",
                "summary": f"{len(hits)} passage(s) found"}

    def doc_passages(document_id: Optional[int] = None) -> dict:
        q = db.query(m.Chunk, m.Document).join(m.Document, m.Chunk.document_id == m.Document.id)\
            .filter(m.Document.owner_id == user.id, m.Document.active.is_(True))
        if document_id:
            q = q.filter(m.Document.id == document_id)
        rows = q.limit(60).all()
        if not rows:
            return {"found": False, "message": "No passages available.", "summary": "No passages"}
        return {"found": True, "passages": [{
            "document": d.name, "document_id": d.id, "page": c.page, "section": c.section,
            "text": c.text[:800]} for c, d in rows],
            "summary": f"{len(rows)} passage(s)"}

    def doc_metadata(document_id: Optional[int] = None) -> dict:
        q = db.query(m.Document).filter(m.Document.owner_id == user.id, m.Document.active.is_(True))
        if document_id:
            q = q.filter(m.Document.id == document_id)
        docs = q.all()
        if not docs:
            return {"found": False, "message": "No documents indexed.", "summary": "No documents"}
        return {"found": True, "documents": [{
            "id": d.id, "name": d.name, "category": d.category, "version": d.version,
            "pages": d.page_count, "chunks": d.chunk_count, "size_bytes": d.size_bytes,
            "source": d.source, "source_url": d.source_url, "published_on": d.published_on,
            "project_id": d.project_id, "uploaded": d.created_at,
        } for d in docs], "summary": f"{len(docs)} document(s)"}

    def compare_sources(query: str) -> dict:
        hits = rag.search(db, user.id, query, ctx.project_id, k=10)
        if not hits:
            return {"found": False, "message": "No passages to compare.", "summary": "No sources"}
        grouped: dict[str, dict] = {}
        for h in hits:
            g = grouped.setdefault(h["document"], {"document": h["document"], "version": h["version"],
                                                   "category": h["category"], "pages": set(),
                                                   "best_score": 0.0, "excerpt": ""})
            if h["page"]:
                g["pages"].add(h["page"])
            if h["score"] > g["best_score"]:
                g["best_score"] = h["score"]
                g["excerpt"] = h["excerpt"][:300]
        for g in grouped.values():
            g["pages"] = sorted(g["pages"])
        return {"found": True, "sources": list(grouped.values()),
                "message": "Multiple documents may disagree; cite each source separately.",
                "summary": f"{len(grouped)} source document(s) compared"}

    def verify_citations(query: str, claims: list[str] = ()) -> dict:
        hits = rag.search(db, user.id, query, ctx.project_id, k=6)
        return {"verified": bool(hits), "passages": [{
            "document": h["document"], "page": h["page"], "section": h["section"],
            "excerpt": h["excerpt"][:300]} for h in hits],
            "message": ("These passages can be cited. Only page numbers that appear here are real."
                        if hits else "No passage supports this claim — do not cite anything."),
            "summary": "Citations verified" if hits else "No supporting citation"}

    # ------------------------- analytics -------------------------
    def trends(months: int = 12) -> dict:
        series = analytics.expense_series(db, user.id, ctx.project_id, months)
        return {"series": series, **analytics.trend_analysis(series),
                "summary": analytics.trend_analysis(series).get("message")}

    def forecast(horizon: int = 3) -> dict:
        series = analytics.expense_series(db, user.id, ctx.project_id, months=18)
        out = analytics.forecast_expenses(series, horizon)
        return {**out, "summary": out.get("message")}

    def anomalies() -> dict:
        out = analytics.detect_unusual_expenses(db, user.id, ctx.project_id)
        return {**out, "summary": out.get("message")}

    def health() -> dict:
        p = ctx.project()
        out = analytics.project_health(db, p)
        return {**out, "summary": f"Health {out['score']}/100 ({out['band'].replace('_', ' ')})"}

    def supplier_perf() -> dict:
        out = analytics.supplier_performance(db, user.id)
        return {**out, "summary": out.get("message")}

    def material_use() -> dict:
        rows = analytics.material_consumption(db, user.id, ctx.project_id)
        return {"consumption": rows, "count": len(rows),
                "summary": f"{len(rows)} material(s) with consumption data"}

    # ------------------------- reports -------------------------
    def _project_pack(project):
        return project_pack(db, project)

    def boq_pdf() -> dict:
        p = ctx.project()
        summary, items, exps, plan, lab = _project_pack(p)
        data = reporting.boq_pdf(p.name, items, summary)
        saved = _save(data, "pdf", f"BOQ report — {p.name}")
        return {**saved, "message": f"PDF report generated for {p.name}.",
                "summary": f"BOQ PDF generated ({len(items)} items)"}

    def budget_report() -> dict:
        p = ctx.project()
        summary, items, exps, plan, lab = _project_pack(p)
        data = reporting.budget_pdf(p, summary, exps, items)
        saved = _save(data, "pdf", f"Budget report — {p.name}")
        return {**saved, "message": f"Budget report generated: {summary['actual_expenses']:,.0f} spent.",
                "summary": "Budget PDF generated"}

    def inventory_report() -> dict:
        p = ctx.project()
        rows = [{"material": i.material_name, "available": i.available, "unit": i.unit,
                 "reserved": i.reserved, "reorder_level": i.reorder_level, "location": i.location,
                 "low": i.reorder_level > 0 and i.available <= i.reorder_level}
                for i in db.query(m.InventoryItem).filter_by(project_id=p.id)]
        data = reporting.inventory_pdf(p.name, rows)
        saved = _save(data, "pdf", f"Inventory report — {p.name}")
        return {**saved, "message": "Inventory report generated.", "summary": "Inventory PDF generated"}

    def progress_report() -> dict:
        p = ctx.project()
        summary, items, exps, plan, lab = _project_pack(p)
        risks = []
        if summary["utilization_pct"] and summary["utilization_pct"] > 90:
            risks.append(f"Budget utilisation is {summary['utilization_pct']}%.")
        if plan.get("overdue"):
            risks.append(f"{len(plan['overdue'])} task(s) are overdue.")
        if not risks:
            risks.append("No budget or schedule red flags from the recorded data.")
        data = reporting.progress_pdf(p, summary, plan, risks)
        saved = _save(data, "pdf", f"Progress report — {p.name}")
        return {**saved, "message": "Progress report generated.", "summary": "Progress PDF generated"}

    def excel_report() -> dict:
        p = ctx.project()
        summary, items, exps, plan, lab = _project_pack(p)
        monthly = {}
        for e in exps:
            key = e.expense_date.strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + float(e.amount)
        data = reporting.summary_xlsx(p.name, summary, items, exps, monthly)
        saved = _save(data, "xlsx", f"Project summary — {p.name}")
        return {**saved, "message": "Excel workbook generated with summary, monthly chart and formatting.",
                "summary": "Excel report generated"}

    reg.add("get_project_schedule", "Task list with calendar dates, slack and critical-path flags.", Empty,
            project_schedule, needs_project=True)
    reg.add("calculate_critical_path", "Critical path and total working duration.", Empty,
            critical_path_tool, needs_project=True)
    reg.add("identify_overdue_tasks", "Tasks past their planned finish date.", Empty, overdue_tasks,
            needs_project=True)
    reg.add("get_weather_forecast", "Open-Meteo forecast for the project site (advisory only).", DaysIn,
            weather_tool)
    reg.add("calculate_schedule_variance", "Planned vs actual schedule progress.", Empty, variance_tool,
            needs_project=True)
    reg.add("create_task_draft", "Propose a schedule task with dependencies by name (needs approval).",
            TaskDraftIn, create_task, write=True, capability="schedule.write")
    reg.add("search_construction_knowledge", "Hybrid search over indexed documents with citations.",
            KnowledgeIn, knowledge_search)
    reg.add("retrieve_document_passages", "Read passages from indexed documents.", DocIn, doc_passages)
    reg.add("get_document_metadata", "List indexed documents and their metadata.", DocIn, doc_metadata)
    reg.add("compare_document_sources", "Compare which documents cover a topic.", KnowledgeIn,
            compare_sources)
    reg.add("verify_citations", "Check which real passages support a claim.", KnowledgeIn, verify_citations)
    reg.add("analyze_expense_trends", "Monthly expense trend with an OLS slope and R².", TrendIn, trends)
    reg.add("forecast_project_expenses", "Forecast monthly expenses with holdout metrics.", ForecastIn,
            forecast)
    reg.add("detect_unusual_expenses", "Flag statistical outliers in recorded expenses.", Empty, anomalies)
    reg.add("calculate_project_health", "Composite health score with contributing factors.", Empty, health,
            needs_project=True)
    reg.add("analyze_supplier_performance", "On-time delivery performance from purchase records.",
            Empty, supplier_perf)
    reg.add("analyze_material_consumption", "Consumption by material from inventory transactions.",
            Empty, material_use)
    reg.add("generate_boq_pdf", "Generate a branded BOQ PDF and return a download link.", Empty, boq_pdf,
            write=True, capability="report.read", needs_project=True)
    reg.add("generate_budget_report", "Generate a branded budget/expense PDF.", Empty, budget_report,
            write=True, capability="report.read", needs_project=True)
    reg.add("generate_inventory_report", "Generate an inventory PDF.", Empty, inventory_report,
            write=True, capability="report.read", needs_project=True)
    reg.add("generate_project_progress_report", "Generate a schedule/progress PDF.", Empty,
            progress_report, write=True, capability="report.read", needs_project=True)
    reg.add("generate_excel_report", "Generate a styled Excel project workbook.", Empty, excel_report,
            write=True, capability="report.read", needs_project=True)
