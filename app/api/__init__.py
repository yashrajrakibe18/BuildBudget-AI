"""Versioned REST API (/api/v1).

Routers are split by responsibility. Business logic lives in app.services so the
website, the REST API and the AI tools all share one implementation.
"""
from fastapi import APIRouter, Depends

from app.api import assistant, auth, catalog, deps, knowledge, ops, workspace

router = APIRouter(dependencies=[Depends(deps.csrf_guard)])

for module in (auth, workspace, catalog, knowledge, assistant, ops):
    router.include_router(module.router)

__all__ = ["router"]
