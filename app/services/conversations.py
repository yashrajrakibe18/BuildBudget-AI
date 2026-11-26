"""Persistent chat conversations.

Every conversation and message belongs to one user; project context is optional.
Queries are scoped by `user_id` so one user can never read another's history.
"""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app import models as m

MAX_CONTEXT_MESSAGES = 12


def create(db: Session, user_id: int, project_id: int | None = None,
           title: str = "New chat") -> m.Conversation:
    c = m.Conversation(user_id=user_id, project_id=project_id, title=title[:200])
    db.add(c)
    db.commit()
    return c


def get_owned(db: Session, user_id: int, conversation_id: int) -> m.Conversation | None:
    return db.query(m.Conversation).filter_by(id=conversation_id, user_id=user_id).first()


def list_for(db: Session, user_id: int, q: str = "", limit: int = 60) -> list[m.Conversation]:
    query = db.query(m.Conversation).filter(m.Conversation.user_id == user_id)
    if q:
        like = f"%{q}%"
        ids = [row[0] for row in db.query(m.ChatMessage.conversation_id)
               .filter(m.ChatMessage.content.ilike(like)).distinct()]
        query = query.filter((m.Conversation.title.ilike(like)) | (m.Conversation.id.in_(ids or [-1])))
    return (query.order_by(m.Conversation.pinned.desc(), m.Conversation.updated_at.desc())
            .limit(limit).all())


def add_message(db: Session, conversation: m.Conversation, role: str, content: str,
                meta: dict | None = None) -> m.ChatMessage:
    msg = m.ChatMessage(conversation_id=conversation.id, role=role, content=content or "",
                        meta_json=json.dumps(meta or {}, default=str))
    db.add(msg)
    conversation.updated_at = m.now()
    db.commit()
    return msg


def history(db: Session, conversation: m.Conversation, limit: int = MAX_CONTEXT_MESSAGES) -> list[dict]:
    rows = (db.query(m.ChatMessage).filter_by(conversation_id=conversation.id)
            .order_by(m.ChatMessage.id.desc()).limit(limit).all())
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def auto_title(text: str) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if not clean:
        return "New chat"
    clean = clean[0].upper() + clean[1:]
    if len(clean) <= 58:
        return clean
    cut = clean[:58].rsplit(" ", 1)[0]
    return (cut or clean[:58]).rstrip(" ,.;:") + "…"


def rename(db: Session, c: m.Conversation, title: str) -> m.Conversation:
    title = (title or "").strip()
    if not title:
        raise ValueError("Title cannot be empty")
    c.title = title[:200]
    c.updated_at = m.now()
    db.commit()
    return c


def pin(db: Session, c: m.Conversation, pinned: bool) -> m.Conversation:
    c.pinned = bool(pinned)
    db.commit()
    return c


def delete(db: Session, c: m.Conversation) -> None:
    db.query(m.ChatMessage).filter_by(conversation_id=c.id).delete()
    db.query(m.ToolExecution).filter_by(conversation_id=c.id).update({"conversation_id": None})
    db.delete(c)
    db.commit()


def serialize(c: m.Conversation, with_messages: bool = False) -> dict:
    out = {
        "id": c.id, "title": c.title, "pinned": c.pinned, "project_id": c.project_id,
        "created_at": c.created_at, "updated_at": c.updated_at,
        "message_count": len(c.messages) if with_messages else None,
    }
    if with_messages:
        out["messages"] = [{
            "id": msg.id, "role": msg.role, "content": msg.content,
            "meta": safe_json(msg.meta_json), "created_at": msg.created_at,
        } for msg in c.messages]
    return out


def safe_json(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
