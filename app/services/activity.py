"""Audit trail helper. Call inside the same transaction as the change."""
from sqlalchemy.orm import Session

from app import models as m


def log(db: Session, *, user_id: int | None, action: str, project_id: int | None = None,
        entity: str = "", entity_id: int | None = None, summary: str = "") -> m.ActivityLog:
    row = m.ActivityLog(user_id=user_id, project_id=project_id, action=action,
                        entity=entity, entity_id=entity_id, summary=(summary or "")[:400])
    db.add(row)
    return row
