"""BuildBudget AI entry point: security middleware, page shell, API mount."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import models as m
from app.api import router as api_router
from app.core import permissions as P
from app.core.config import settings
from app.core.labels import (
    APPROVAL_ACTIONS,
    DOCUMENT_CATEGORIES,
    MAIL_FOLDERS,
    PROJECT_STATUS,
    PROJECT_TYPES,
    ROLE_LABELS,
    project_type_label,
)
from app.database import get_db, init_db
from app.services import notifications

logging.basicConfig(level=settings.log_level,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("buildbudget")

BASE = Path(__file__).parent

NAV = [
    ("Workspace", [
        ("/dashboard", "Overview", "layout-dashboard"),
        ("/projects", "My Projects", "folder-kanban"),
        ("/assistant", "AI Assistant", "sparkles"),
    ]),
    ("Construction", [
        ("/estimator", "Cost Estimator", "calculator"),
        ("/boq", "Bill of Quantities", "list-checks"),
        ("/budgets", "Budget & Expenses", "wallet"),
        ("/inventory", "Inventory", "package"),
        ("/suppliers", "Suppliers & Prices", "truck"),
        ("/procurement", "Procurement", "clipboard-list"),
        ("/labour", "Labour", "hard-hat"),
        ("/schedule", "Project Schedule", "calendar-range"),
    ]),
    ("Intelligence", [
        ("/analytics", "Analytics", "chart-line"),
        ("/knowledge", "Knowledge Base", "library"),
        ("/reports", "Reports", "file-text"),
    ]),
    ("Communication", [
        ("/mail", "Mail Centre", "mail"),
        ("/notifications", "Notifications", "bell"),
        ("/automations", "Automations", "zap"),
        ("/approvals", "Approval Centre", "shield-check"),
    ]),
    ("Administration", [
        ("/profile", "Profile", "user"),
        ("/settings", "Settings", "settings"),
        ("/activity", "Activity Logs", "history"),
    ]),
]

PAGES = {
    "dashboard": ("dashboard.html", "Overview"),
    "projects": ("projects.html", "My Projects"),
    "estimator": ("estimator.html", "Cost Estimator"),
    "boq": ("modules.html", "Bill of Quantities"),
    "budgets": ("modules.html", "Budget & Expenses"),
    "inventory": ("modules.html", "Inventory"),
    "procurement": ("modules.html", "Procurement"),
    "labour": ("modules.html", "Labour"),
    "schedule": ("modules.html", "Project Schedule"),
    "suppliers": ("suppliers.html", "Suppliers & Prices"),
    "knowledge": ("knowledge.html", "Knowledge Base"),
    "reports": ("reports.html", "Reports"),
    "analytics": ("analytics.html", "Analytics"),
    "assistant": ("assistant.html", "AI Assistant"),
    "mail": ("mail.html", "Mail Centre"),
    "notifications": ("notifications.html", "Notifications"),
    "automations": ("automations.html", "Automations"),
    "approvals": ("approvals.html", "Approval Centre"),
    "profile": ("profile.html", "Profile"),
    "settings": ("settings.html", "Settings"),
    "activity": ("activity.html", "Activity Logs"),
}

MODULE_PAGES = {"boq", "budgets", "inventory", "procurement", "labour", "schedule"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.scheduler_enabled and settings.scheduler_in_app:
        from app.workers.scheduler import start
        app.state.scheduler = start()
    yield
    if getattr(app.state, "scheduler", None):
        app.state.scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware, secret_key=settings.secret_key, session_cookie="bb_session",
    same_site="lax", https_only=settings.app_env == "production",
    max_age=30 * 24 * 3600,   # cookie lifetime; per-session expiry is enforced server-side
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals.update(
    project_type_label=project_type_label, PROJECT_TYPES=PROJECT_TYPES,
    PROJECT_STATUS=PROJECT_STATUS, ROLE_LABELS=ROLE_LABELS, APPROVAL_ACTIONS=APPROVAL_ACTIONS,
    DOCUMENT_CATEGORIES=DOCUMENT_CATEGORIES, MAIL_FOLDERS=MAIL_FOLDERS,
)
app.include_router(api_router, prefix="/api/v1")

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self' https://cdn.jsdelivr.net https://unpkg.com; font-src 'self' data:; "
       "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    path = request.url.path
    if not path.startswith("/docs") and not path.startswith("/openapi"):
        response.headers.setdefault("Content-Security-Policy", CSP)
    if path.startswith("/api/") and not path.endswith("/stream"):
        response.headers.setdefault("Cache-Control", "no-store")
    if path.startswith("/static/") and settings.app_env != "production":
        # Revalidate JS/CSS in development so a stale cached page script can never
        # mask a fix. Production should serve content-hashed asset filenames.
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": getattr(exc, "detail", "Not found")}, status_code=404)
    return templates.TemplateResponse(request, "error.html",
                                      {"title": "Page not found", "app_name": settings.app_name,
                                       "code": 404, "message": "That page does not exist.",
                                       "auth": not request.session.get("uid")}, status_code=404)


@app.exception_handler(500)
async def server_error(request: Request, exc):
    log.exception("Unhandled error on %s", request.url.path)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "An unexpected error occurred."}, status_code=500)
    return templates.TemplateResponse(request, "error.html",
                                      {"title": "Something went wrong", "app_name": settings.app_name,
                                       "code": 500, "message": "Something went wrong. Please try again.",
                                       "auth": not request.session.get("uid")}, status_code=500)


@app.get("/health")
def health():
    return {"status": "ok", "version": settings.version}


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(BASE / "static" / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def web_manifest():
    return FileResponse(BASE / "static" / "manifest.webmanifest",
                        media_type="application/manifest+json",
                        headers={"Cache-Control": "public, max-age=3600"})


@app.get("/ready")
def ready():
    from sqlalchemy import text

    from app.database import engine
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    return {"status": "ready", "version": settings.version}


def shell(request: Request, db: Session, page: str, title: str, **extra) -> dict:
    user = db.get(m.User, request.session["uid"])
    unread = notifications.unread_count(db, user.id)
    pending = db.query(m.ApprovalRequest).filter_by(user_id=user.id, status="pending").count()
    if P.effective_role(user.role) == "admin":
        projects = (db.query(m.Project)
                    .filter(m.Project.archived.is_(False))
                    .order_by(m.Project.name).limit(50).all())
    else:
        projects = (db.query(m.Project)
                    .filter(m.Project.owner_id == user.id, m.Project.archived.is_(False))
                    .order_by(m.Project.name).limit(50).all())
    return {
        "title": title, "page": page, "app_name": settings.app_name, "version": settings.version,
        "nav": NAV, "user": user, "role_label": P.role_label(user.role),
        "unread_count": unread, "pending_approvals": pending,
        "switcher_projects": projects, "csrf": request.session.get("csrf", ""),
        "demo_mode": settings.demo_mode, "environment": settings.app_env,
        **extra,
    }


def _guard(request: Request, db: Session, template: str, page: str, title: str, **extra):
    if not request.session.get("uid"):
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, template,
                                      shell(request, db, page, title, **extra))


def _make_page(name: str):
    template, title = PAGES[name]

    def view(request: Request, db: Session = Depends(get_db)):
        extra = {"module": name} if name in MODULE_PAGES else {}
        return _guard(request, db, template, name, title, **extra)
    return view


@app.get("/")
def index(request: Request):
    return RedirectResponse("/dashboard" if request.session.get("uid") else "/login")


@app.get("/login")
def login_page(request: Request):
    if request.session.get("uid"):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse(request, "login.html",
                                      {"title": "Sign in", "app_name": settings.app_name,
                                       "demo_mode": settings.demo_mode,
                                       "environment": settings.app_env})


@app.get("/register")
def register_page(request: Request):
    if request.session.get("uid"):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse(request, "register.html",
                                      {"title": "Create account", "app_name": settings.app_name,
                                       "roles": ["project_manager", "site_engineer", "accountant",
                                                 "procurement_manager", "viewer"],
                                       "demo_mode": settings.demo_mode})


@app.get("/reset-password")
def reset_page(request: Request):
    return templates.TemplateResponse(request, "reset_password.html",
                                      {"title": "Reset password", "app_name": settings.app_name,
                                       "token": request.query_params.get("token", "")})


@app.get("/projects/{pid}")
def project_page(pid: int, request: Request, db: Session = Depends(get_db)):
    if not request.session.get("uid"):
        return RedirectResponse("/login")
    user = db.get(m.User, request.session["uid"])
    project = db.get(m.Project, pid)
    if not project or (project.owner_id != user.id and P.effective_role(user.role) != "admin"):
        raise HTTPException(404, "Project not found")
    return _guard(request, db, "project.html", "project", project.name, pid=pid,
                  project_name=project.name, initial_tab=request.query_params.get("tab", "overview"))


for _name in PAGES:
    app.add_api_route(f"/{_name}", _make_page(_name), include_in_schema=False)

for _alias, _target in (("/expenses", "budgets"), ("/tasks", "schedule"), ("/documents", "knowledge")):
    app.add_api_route(_alias, _make_page(_target), include_in_schema=False)
