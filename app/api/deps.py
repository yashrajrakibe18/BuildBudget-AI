"""Shared API dependencies: session auth, permissions, CSRF and ownership."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models as m
from app.core import permissions as P
from app.core.security import new_csrf_token
from app.database import get_db

SESSION_HOURS = 12
REMEMBER_DAYS = 30
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def session_start(request: Request, user: m.User, remember: bool = False) -> str:
    """Start a fresh session, rotating the id and issuing a CSRF token."""
    request.session.clear()
    request.session["uid"] = user.id
    request.session["csrf"] = new_csrf_token()
    ttl = REMEMBER_DAYS * 24 * 3600 if remember else SESSION_HOURS * 3600
    request.session["exp"] = (utcnow().timestamp() + ttl)
    request.session["remember"] = bool(remember)
    return request.session["csrf"]


def csrf_guard(request: Request) -> None:
    """Defence in depth: same-origin check for browser requests + optional token.

    Browsers always send Origin on cross-site unsafe requests, so this blocks
    CSRF even before the token is compared. Non-browser API clients without an
    Origin header are unaffected (they are not vulnerable to CSRF).
    """
    if request.method not in UNSAFE:
        return
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        host = request.headers.get("host", "")
        if host and host not in origin:
            raise HTTPException(403, "Cross-origin state-changing request blocked")
    token = request.headers.get("x-csrf-token")
    if token:
        expected = request.session.get("csrf")
        if not expected or token != expected:
            raise HTTPException(403, "Invalid or expired CSRF token — reload the page")


def current_user(request: Request, db: Session = Depends(get_db)) -> m.User:
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(401, "Not authenticated")
    exp = request.session.get("exp")
    if exp and float(exp) < utcnow().timestamp():
        request.session.clear()
        raise HTTPException(401, "Your session expired — please sign in again")
    user = db.get(m.User, uid)
    if not user:
        request.session.clear()
        raise HTTPException(401, "Not authenticated")
    return user


def require(capability: str):
    def dependency(user: m.User = Depends(current_user)) -> m.User:
        if not P.can(user, capability):
            raise HTTPException(403, f"Role '{P.role_label(user.role)}' cannot perform this action")
        return user
    return dependency


def owned_project(db: Session, user: m.User, project_id: int) -> m.Project:
    project = db.get(m.Project, project_id)
    if not project or (project.owner_id != user.id and P.effective_role(user.role) != "admin"):
        raise HTTPException(404, "Project not found")
    return project


def assert_owner(user: m.User, row, owner_field: str = "owner_id") -> None:
    if getattr(row, owner_field, None) != user.id and P.effective_role(user.role) != "admin":
        raise HTTPException(404, "Not found")


def paginate(query, page: int = 1, size: int = 50):
    size = max(1, min(size, 200))
    page = max(1, page)
    total = query.count()
    rows = query.offset((page - 1) * size).limit(size).all()
    return rows, {"page": page, "size": size, "total": total,
                  "pages": (total + size - 1) // size}
