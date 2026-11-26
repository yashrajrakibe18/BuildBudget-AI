"""Password hashing, password policy, reset tokens and CSRF helpers.

PBKDF2-SHA256 with per-password salt. Tokens are stored hashed, single-use and
expiring. No secret material is ever logged.
"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

_ITER = 210_000
MIN_LENGTH = 8
RESET_TTL_MINUTES = 30


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), dk)
    except Exception:
        return False


def password_strength(password: str) -> dict:
    """Return a 0-4 score with actionable feedback (used by the registration UI)."""
    pw = password or ""
    checks = {
        "length": len(pw) >= MIN_LENGTH,
        "long": len(pw) >= 12,
        "lower_upper": bool(re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw)),
        "digit": bool(re.search(r"\d", pw)),
        "symbol": bool(re.search(r"[^A-Za-z0-9]", pw)),
    }
    score = sum(1 for k in ("length", "long", "lower_upper", "digit", "symbol") if checks[k])
    score = min(4, score)
    labels = ["Very weak", "Weak", "Fair", "Strong", "Very strong"]
    missing = []
    if not checks["length"]:
        missing.append(f"at least {MIN_LENGTH} characters")
    if not checks["lower_upper"]:
        missing.append("upper and lower case letters")
    if not checks["digit"]:
        missing.append("a number")
    if not checks["symbol"]:
        missing.append("a symbol")
    return {"score": score, "label": labels[score], "checks": checks, "missing": missing}


def validate_password(password: str) -> None:
    if len(password or "") < MIN_LENGTH:
        raise ValueError(f"Password must be at least {MIN_LENGTH} characters")
    if password.lower() in {"password123", "12345678", "qwerty123", "letmein123"}:
        raise ValueError("That password is too common; choose something less guessable")


def new_reset_token() -> tuple[str, str, datetime]:
    """Return (plaintext token, token hash, expiry). Only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest(), _now() + timedelta(minutes=RESET_TTL_MINUTES)


def hash_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def random_idempotency_key(prefix: str = "k") -> str:
    return f"{prefix}_{secrets.token_hex(12)}"
