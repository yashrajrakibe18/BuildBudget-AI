"""Authentication, profile and password reset."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models as m
from app.api import serialize
from app.api.deps import current_user, session_start, utcnow
from app.api.schemas import LoginIn, PasswordChangeIn, ProfileIn, RegisterIn, ResetConfirmIn, ResetRequestIn
from app.core import permissions as P
from app.core import ratelimit
from app.core.config import settings
from app.core.security import (
    RESET_TTL_MINUTES,
    hash_password,
    hash_token,
    new_reset_token,
    password_strength,
    validate_password,
    verify_password,
)
from app.database import get_db
from app.services import activity

router = APIRouter()

SELF_ROLES = ["project_manager", "site_engineer", "accountant", "procurement_manager",
              "viewer", "homeowner", "contractor", "estimator", "analyst"]


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if body.role not in SELF_ROLES:
        raise HTTPException(422, f"role must be one of {SELF_ROLES}")
    email = body.email.lower().strip()
    if db.query(m.User).filter_by(email=email).first():
        raise HTTPException(409, "That email is already registered")
    try:
        validate_password(body.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    user = m.User(email=email, name=body.name.strip(), role=body.role,
                  password_hash=hash_password(body.password),
                  theme="system", units=settings.units, currency=settings.currency,
                  timezone=settings.timezone, last_login_at=utcnow())
    db.add(user)
    activity.log(db, user_id=None, action="user_registered", entity="user", summary=email)
    db.commit()
    csrf = session_start(request, user, body.remember)
    return {**serialize.user(user), "csrf": csrf}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower().strip()
    if not ratelimit.allow(f"login:{email}", limit=8, window_seconds=300):
        raise HTTPException(429, "Too many sign-in attempts. Wait a few minutes and try again.")
    user = db.query(m.User).filter_by(email=email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect")
    user.last_login_at = utcnow()
    db.commit()
    csrf = session_start(request, user, body.remember)
    ratelimit.reset(f"login:{email}")
    return {**serialize.user(user), "csrf": csrf}


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request, user: m.User = Depends(current_user)):
    if not request.session.get("csrf"):
        from app.core.security import new_csrf_token
        request.session["csrf"] = new_csrf_token()
    return {**serialize.user(user), "csrf": request.session["csrf"],
            "password_strength": password_strength("")}


@router.put("/auth/profile")
def update_profile(body: ProfileIn, user: m.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True)
    if "email" in changes and changes["email"]:
        new_email = changes["email"].lower()
        clash = db.query(m.User).filter(m.User.email == new_email, m.User.id != user.id).first()
        if clash:
            raise HTTPException(409, "That email is already used by another account")
        changes["email"] = new_email
    for key, value in changes.items():
        if value is not None:
            setattr(user, key, value)
    activity.log(db, user_id=user.id, action="profile_updated", entity="user", entity_id=user.id,
                 summary=", ".join(k.replace("_", " ") for k in changes))
    db.commit()
    return serialize.user(user)


@router.post("/auth/password")
def change_password(body: PasswordChangeIn, user: m.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    try:
        validate_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(422, "Choose a password different from the current one")
    user.password_hash = hash_password(body.new_password)
    activity.log(db, user_id=user.id, action="password_changed", entity="user", entity_id=user.id)
    db.commit()
    return {"ok": True, "message": "Password updated"}


@router.get("/auth/password-strength")
def strength(password: str = ""):
    return password_strength(password)


@router.post("/auth/password-reset/request")
def request_reset(body: ResetRequestIn, db: Session = Depends(get_db)):
    """Always returns the same answer so the endpoint cannot enumerate accounts.

    With no email provider configured the reset link is returned to the caller in
    development mode only, and the UI says so explicitly.
    """
    email = body.email.lower()
    user = db.query(m.User).filter_by(email=email).first()
    generic = {"sent": True,
               "message": "If that email has an account, a reset link has been created."}
    if not user:
        return generic
    raw, token_hash, expires = new_reset_token()
    db.add(m.PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=expires))
    db.commit()
    from app.services import mail
    provider_ok, why = mail.SMTPProvider().available()
    link = f"/reset-password?token={raw}"
    if provider_ok:
        try:
            mail.draft(db, user, to=user.email, subject="Reset your BuildBudget AI password",
                       body=(f"Use this link within {RESET_TTL_MINUTES} minutes to reset your password:\n"
                             f"{settings.app_name} {link}\n\nIf you did not request this, ignore the email."))
            return {**generic, "message": "Reset link emailed. Check your inbox."}
        except Exception:  # noqa: BLE001
            pass
    if settings.app_env != "production":
        return {**generic, "dev_link": link,
                "message": ("Email is not configured, so here is the reset link for local "
                            "development. It expires in "
                            f"{RESET_TTL_MINUTES} minutes.")}
    return {**generic, "message": "Email delivery is not configured on this server; ask the administrator."}


@router.post("/auth/password-reset/confirm")
def confirm_reset(body: ResetConfirmIn, db: Session = Depends(get_db)):
    row = db.query(m.PasswordResetToken).filter_by(token_hash=hash_token(body.token)).first()
    if not row or row.used_at is not None:
        raise HTTPException(400, "This reset link is invalid or has already been used")
    if row.expires_at < utcnow():
        raise HTTPException(400, "This reset link has expired. Request a new one.")
    try:
        validate_password(body.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    user = db.get(m.User, row.user_id)
    user.password_hash = hash_password(body.password)
    row.used_at = utcnow()
    activity.log(db, user_id=user.id, action="password_reset", entity="user", entity_id=user.id)
    db.commit()
    return {"ok": True, "message": "Password reset. You can sign in now."}


@router.get("/auth/session")
def session_info(request: Request, user: m.User = Depends(current_user)):
    exp = request.session.get("exp")
    from datetime import datetime
    return {"remember": bool(request.session.get("remember")),
            "expires_at": datetime.fromtimestamp(float(exp)) if exp else None,
            "role_label": P.role_label(user.role)}
