"""Additive schema upgrade for existing databases.

Alembic is the long-term answer, but this build must upgrade a real, populated
SQLite/PostgreSQL database in place without dropping anything. Rules:

* new tables are created by SQLAlchemy `create_all` (elsewhere);
* missing columns are added with `ALTER TABLE ... ADD COLUMN`, nullable or with
  a server default, so existing rows stay valid;
* nothing is dropped, renamed or rewritten;
* operations are idempotent and safe to run on every start.
"""
import logging

from sqlalchemy import inspect, text

log = logging.getLogger(__name__)

# Columns that must be NOT NULL for existing rows get an explicit server default.
_SERVER_DEFAULTS = {
    "Boolean": "0",
    "Integer": "0",
    "Float": "0",
    "Numeric": "0",
    "String": "''",
    "Text": "''",
    "DateTime": None,
    "Date": None,
}


def _default_sql(col, dialect: str):
    type_name = type(col.type).__name__
    default = _SERVER_DEFAULTS.get(type_name)
    if default is None:
        return None
    if type_name == "Boolean" and dialect == "postgresql":
        return "false"
    return default


def upgrade_schema(engine) -> list[str]:
    """Return a list of applied changes (empty when already up to date)."""
    from app import models  # noqa: F401
    from app.database import Base

    applied: list[str] = []
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    dialect = engine.dialect.name

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            if col.primary_key:
                continue
            col_type = col.type.compile(engine.dialect)
            ddl = f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col_type}'
            default = _default_sql(col, dialect)
            if default is not None:
                ddl += f" DEFAULT {default}"
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append(f"{table.name}.{col.name}")
            except Exception as exc:  # noqa: BLE001 - report, never abort startup
                log.warning("Could not add column %s.%s: %s", table.name, col.name, exc)
    if applied:
        log.info("Schema upgraded: %s", ", ".join(applied))
    return applied
