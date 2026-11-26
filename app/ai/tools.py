"""Tool registry facade.

`build_tools` returns the LangChain tool dict used by the agents. Every tool has
a validated schema and writes an audit row. The same service functions back the
REST API, so the assistant can never do something the website cannot.
"""
from __future__ import annotations

from typing import Callable, Optional

from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session

from app import models as m
from app.ai import tools_comms, tools_finance, tools_materials, tools_ops
from app.ai.tools_core import ToolContext, ToolRegistry
from app.ai.tools_materials import latest_prices, quotes_as_dicts  # re-exported for the API

WRITE_ROLES = {"homeowner", "contractor", "project_manager", "procurement_manager",
               "estimator", "site_engineer", "accountant", "admin"}

__all__ = ["build_tools", "build_tools_with_context", "latest_prices", "quotes_as_dicts",
           "ToolContext", "WRITE_ROLES"]


def build_tools_with_context(db: Session, user: m.User, project_id: Optional[int],
                              conversation_id: Optional[int] = None,
                              document_id: Optional[int] = None,
                              on_event: Callable[[dict], None] | None = None
                              ) -> tuple[dict[str, StructuredTool], ToolContext]:
    ctx = ToolContext(db, user, project_id, conversation_id, document_id=document_id)
    reg = ToolRegistry(ctx, on_event)
    for module in (tools_finance, tools_materials, tools_ops, tools_comms):
        module.register(reg)
    return reg.build(), ctx


def build_tools(db: Session, user: m.User, project_id: Optional[int],
                conversation_id: Optional[int] = None,
                on_event: Callable[[dict], None] | None = None
                ) -> dict[str, StructuredTool]:
    tools, _ = build_tools_with_context(db, user, project_id, conversation_id, on_event)
    return tools
