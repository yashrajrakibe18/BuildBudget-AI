"""Engine, session factory and idempotent schema upgrade.

`init_db()` creates missing tables and then adds any new columns to existing
tables (additive only — it never drops or rewrites user data).
"""
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

log = logging.getLogger(__name__)

_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_args, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401  (register metadata)

    Base.metadata.create_all(engine)
    from app.db_migrate import upgrade_schema

    upgrade_schema(engine)
