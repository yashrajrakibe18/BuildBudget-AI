"""Shared plumbing for the tool-calling layer.

Every tool is a genuine Python function with a validated Pydantic schema, a
permission check, and a `tool_executions` audit row. Tools never fabricate a
result: when data is missing they say so.
"""
from __future__ import annotations

import json
import time
from datetime import date
from typing import Callable

from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session

from app import models as m
from app.core import permissions as P


class ToolContext:
    """Mutable per-run context so one agent can hand a resolved project to the next."""

    def __init__(self, db: Session, user: m.User, project_id: int | None,
                  conversation_id: int | None = None, document_id: int | None = None):
        self.db = db
        self.user = user
        self.project_id = project_id
        self.conversation_id = conversation_id
        self.document_id = document_id
        self.resolved_by: str | None = None
        self.tool_events: list[dict] = []

    def projects(self) -> list[m.Project]:
        q = self.db.query(m.Project)
        if P.effective_role(self.user.role) != "admin":
            q = q.filter_by(owner_id=self.user.id)
        return q.order_by(m.Project.id.desc()).all()

    def project(self) -> m.Project:
        if self.project_id is None:
            names = [p.name for p in self.projects()[:6]]
            hint = f" Your projects: {', '.join(names)}." if names else " Create one first."
            raise ValueError("No project is selected for this request." + hint +
                             " Call find_project with the project name, or ask the user which project.")
        p = self.db.get(m.Project, self.project_id)
        if not p or (p.owner_id != self.user.id and P.effective_role(self.user.role) != "admin"):
            raise PermissionError("That project was not found or you do not have access to it.")
        return p

    def try_project(self) -> m.Project | None:
        try:
            return self.project()
        except (ValueError, PermissionError):
            return None

    def document(self):
        if self.document_id is None:
            return None
        d = self.db.get(m.Document, self.document_id)
        if not d or d.owner_id != self.user.id or not getattr(d, "active", True):
            return None
        return d

    def try_document(self):
        try:
            return self.document()
        except Exception:  # noqa: BLE001
            return None


def _summarize(name: str, out) -> str:
    if not isinstance(out, dict):
        return name
    for key in ("message", "summary", "note", "title"):
        v = out.get(key)
        if isinstance(v, str) and v:
            return v[:300]
    if "final_quantity" in out:
        return f"{out['final_quantity']} {out.get('unit', '')} of {out.get('item', 'material')}".strip()
    if "status" in out and "approval_id" in out:
        return f"Approval #{out['approval_id']} created"
    if "ai_message" in out:
        return str(out["ai_message"])[:300]
    return name


class ToolRegistry:
    def __init__(self, ctx: ToolContext, on_event: Callable[[dict], None] | None = None):
        self.ctx = ctx
        self.on_event = on_event
        self.specs: list[tuple] = []

    # ---- registration ----------------------------------------------------
    def add(self, name: str, description: str, schema, fn: Callable, *,
            write: bool = False, capability: str | None = None,
            needs_project: bool = False) -> None:
        self.specs.append((name, description, schema, fn, write, capability, needs_project))

    # ---- execution -------------------------------------------------------
    def _wrap(self, name, description, schema, fn, write, capability, needs_project):
        ctx = self.ctx

        def run(**kwargs) -> str:
            started = time.time()
            status = "ok"
            try:
                if needs_project:
                    ctx.project()
                if write:
                    P.assert_can(ctx.user, capability or "project.edit")
                out = fn(**kwargs)
                if isinstance(out, tuple):
                    out, summary = out
                else:
                    summary = _summarize(name, out)
            except PermissionError as exc:
                status, out, summary = "denied", {"error": str(exc)}, str(exc)[:300]
            except Exception as exc:  # noqa: BLE001 - returned to the model so it can recover
                status, out, summary = "error", {"error": str(exc)}, str(exc)[:300]
            payload = json.dumps(out, default=str, ensure_ascii=False)
            elapsed = int((time.time() - started) * 1000)
            ctx.db.add(m.ToolExecution(
                user_id=ctx.user.id, project_id=ctx.project_id, conversation_id=ctx.conversation_id,
                tool=name, args=json.dumps(kwargs, default=str)[:2000], result=payload[:6000],
                summary=(summary or "")[:500], status=status, duration_ms=elapsed,
            ))
            ctx.db.commit()
            event = {"type": "tool", "tool": name, "status": status, "duration_ms": elapsed,
                     "summary": (summary or "")[:300]}
            ctx.tool_events.append(event)
            if self.on_event:
                try:
                    self.on_event(event)
                except Exception:  # noqa: BLE001 - a broken listener must not break a tool
                    pass
            return payload

        return StructuredTool.from_function(func=run, name=name, description=description,
                                            args_schema=schema)

    def build(self) -> dict[str, StructuredTool]:
        return {name: self._wrap(name, desc, schema, fn, write, cap, needs)
                for name, desc, schema, fn, write, cap, needs in self.specs}


def inr(v) -> str:
    try:
        return f"₹{float(v):,.2f}"
    except (TypeError, ValueError):
        return "₹0.00"


def d(value) -> str:
    if isinstance(value, (date,)):
        return value.isoformat()
    return str(value) if value is not None else "—"


def money_dict(label_amounts: dict) -> dict:
    return {k: round(float(v), 2) for k, v in label_amounts.items()}
