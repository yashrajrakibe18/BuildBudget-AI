"""AI assistant: conversations, chat, SSE progress stream, tools and approvals."""
from __future__ import annotations

import json
import queue
import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import models as m
from app.ai import tools as ai_tools
from app.ai.graph import AGENTS, RULES, run_chat
from app.ai.llm import LLMNotConfigured, availability, get_chat_model
from app.api import serialize
from app.api.deps import current_user, owned_project, require
from app.api.schemas import ChatIn, ConversationPatch, DecideIn
from app.core import ratelimit
from app.core.labels import TOOL_LABELS, label
from app.database import SessionLocal, get_db
from app.services import approvals as approval_svc
from app.services import conversations as conv_svc
from app.services import rag

router = APIRouter()


def _require_llm():
    status = availability()
    if not status["available"]:
        raise HTTPException(503, f"The AI assistant is unavailable. {status['reason']}")
    try:
        return get_chat_model()
    except LLMNotConfigured as exc:
        raise HTTPException(503, str(exc)) from None


@router.get("/assistant/status")
def assistant_status(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return {
        "llm": availability(),
        "knowledge": rag.stats(db, user.id),
        "conversations": db.query(m.Conversation).filter_by(user_id=user.id).count(),
        "tools": len({t for _, (_, names) in AGENTS.items() for t in names}),
        "streaming": {"transport": "server-sent events",
                      "mode": "operational step events, final answer as one event",
                      "token_level": False},
    }


@router.get("/assistant/tools")
def assistant_tools(user: m.User = Depends(current_user)):
    groups = []
    for name, (desc, tools) in AGENTS.items():
        groups.append({
            "agent": name, "description": desc,
            "tools": [{"name": t, "label": label(TOOL_LABELS, t)} for t in tools],
        })
    return {"agents": groups, "guidance": RULES}


@router.get("/assistant/conversations")
def list_conversations(q: str = "", user: m.User = Depends(current_user),
                       db: Session = Depends(get_db)):
    rows = conv_svc.list_for(db, user.id, q)
    return [{"id": c.id, "title": c.title, "pinned": c.pinned, "project_id": c.project_id,
             "updated_at": c.updated_at, "created_at": c.created_at,
             "message_count": db.query(m.ChatMessage).filter_by(conversation_id=c.id).count()}
            for c in rows]


@router.post("/assistant/conversations", status_code=201)
def create_conversation(project_id: Optional[int] = None, title: str = "New chat",
                        user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if project_id:
        owned_project(db, user, project_id)
    conv = conv_svc.create(db, user.id, project_id, title)
    return conv_svc.serialize(conv, with_messages=True)


@router.get("/assistant/conversations/{cid}")
def get_conversation(cid: int, user: m.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    conv = conv_svc.get_owned(db, user.id, cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv_svc.serialize(conv, with_messages=True)


@router.patch("/assistant/conversations/{cid}")
def patch_conversation(cid: int, body: ConversationPatch,
                       user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    conv = conv_svc.get_owned(db, user.id, cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if body.title is not None:
        try:
            conv_svc.rename(db, conv, body.title)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    if body.pinned is not None:
        conv_svc.pin(db, conv, body.pinned)
    return conv_svc.serialize(conv)


@router.delete("/assistant/conversations/{cid}")
def delete_conversation(cid: int, user: m.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    conv = conv_svc.get_owned(db, user.id, cid)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    conv_svc.delete(db, conv)
    return {"ok": True}


@router.get("/assistant/tool-executions")
def tool_executions(conversation_id: Optional[int] = None, limit: int = Query(40, ge=1, le=200),
                    user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    query = db.query(m.ToolExecution).filter(m.ToolExecution.user_id == user.id)
    if conversation_id:
        query = query.filter(m.ToolExecution.conversation_id == conversation_id)
    rows = query.order_by(m.ToolExecution.id.desc()).limit(limit).all()
    return [{
        "id": r.id, "tool": r.tool, "label": label(TOOL_LABELS, r.tool), "status": r.status,
        "duration_ms": r.duration_ms, "summary": r.summary, "when": r.created_at,
        "args": serialize.safe_json(r.args),
        "result_preview": r.result[:1200],
        "conversation_id": r.conversation_id,
    } for r in rows]


def _run_turn(db: Session, user: m.User, message: str, project_id: Optional[int],
               conversation_id: Optional[int], document_id: Optional[int] = None,
               on_event=None) -> dict:
    llm = _require_llm()
    conv = conv_svc.get_owned(db, user.id, conversation_id) if conversation_id else None
    if conversation_id and not conv:
        raise HTTPException(404, "Conversation not found")
    if conv is None:
        conv = conv_svc.create(db, user.id, project_id, conv_svc.auto_title(message))
    elif project_id and conv.project_id != project_id:
        conv.project_id = project_id
        db.commit()
    history = conv_svc.history(db, conv)
    conv_svc.add_message(db, conv, "user", message)
    if conv.title in ("New chat", "") or conv.title is None:
        conv_svc.rename(db, conv, conv_svc.auto_title(message))

    if document_id is not None:
        doc = db.get(m.Document, document_id)
        if not doc or doc.owner_id != user.id or not getattr(doc, "active", True):
            document_id = None
    tools, ctx = ai_tools.build_tools_with_context(
        db, user, conv.project_id, conv.id, document_id=document_id, on_event=on_event)
    run = m.AgentRun(user_id=user.id, project_id=conv.project_id, conversation_id=conv.id,
                     prompt=message[:2000])
    db.add(run)
    db.commit()
    try:
        result = run_chat(llm, tools, message, history=history, on_event=on_event, ctx=ctx)
        run.answer, run.agents, run.status = result["answer"][:8000], ",".join(result["agents"]), "ok"
    except Exception as exc:  # noqa: BLE001
        run.status, run.answer = "error", str(exc)[:500]
        db.commit()
        raise HTTPException(502, f"The assistant run failed: {exc}") from None

    pending = (db.query(m.ApprovalRequest)
               .filter_by(conversation_id=conv.id, status="pending")
               .order_by(m.ApprovalRequest.id).all())
    meta = {
        "agents": result["agents"],
        "missing_info": result["missing_info"],
        "errors": result.get("errors", []),
        "tools": ctx.tool_events,
        "approval_ids": [a.id for a in pending],
        "usage": result.get("usage", {}),
        "project_id": conv.project_id,
    }
    msg = conv_svc.add_message(db, conv, "assistant", result["answer"], meta)
    db.commit()
    return {
        "conversation_id": conv.id, "message_id": msg.id, "answer": result["answer"],
        "agents": result["agents"], "missing_info": result["missing_info"],
        "errors": result.get("errors", []), "tool_events": ctx.tool_events,
        "approvals": [approval_svc.serialize(a) for a in pending],
        "usage": result.get("usage", {}),
    }


@router.post("/assistant/chat")
def chat(body: ChatIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if not ratelimit.allow(f"chat:{user.id}", limit=30, window_seconds=60):
        raise HTTPException(429, "Slow down a little — too many assistant requests in a minute.")
    if body.project_id:
        owned_project(db, user, body.project_id)
    return _run_turn(db, user, body.message, body.project_id, body.conversation_id,
                     body.document_id)


@router.post("/assistant/stream")
def chat_stream(body: ChatIn, request: Request, user: m.User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Server-Sent Events: routing, agent and tool events are streamed live.

    The final answer arrives as one event (token-level streaming is not enabled,
    which the assistant status endpoint reports honestly).
    """
    if not ratelimit.allow(f"chat:{user.id}", limit=30, window_seconds=60):
        raise HTTPException(429, "Slow down a little — too many assistant requests in a minute.")
    if body.project_id:
        owned_project(db, user, body.project_id)
    _require_llm()                       # fail before the stream starts, with a proper status code
    uid, message = user.id, body.message
    project_id, conversation_id = body.project_id, body.conversation_id
    document_id = body.document_id

    async def stream():
        events: queue.Queue = queue.Queue()
        outcome: dict = {}

        def worker():
            session = SessionLocal()
            try:
                worker_user = session.get(m.User, uid)
                events.put({"type": "status", "message": "Understanding your request…"})
                outcome.update(_run_turn(session, worker_user, message, project_id,
                                         conversation_id, document_id, on_event=events.put))
                events.put({"type": "answer", "answer": outcome.get("answer", ""),
                            "agents": outcome.get("agents", []),
                            "conversation_id": outcome.get("conversation_id"),
                            "message_id": outcome.get("message_id"),
                            "approvals": outcome.get("approvals", []),
                            "tool_events": outcome.get("tool_events", [])})
            except HTTPException as exc:
                events.put({"type": "error", "message": exc.detail})
            except Exception as exc:  # noqa: BLE001
                events.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                session.close()
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()
        started = time.time()
        yield "retry: 5000\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                # The worker is a blocking thread; read its queue without blocking the loop.
                item = await run_in_threadpool(events.get, timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                if time.time() - started > 240:
                    yield 'data: {"type":"error","message":"The assistant timed out."}\n\n'
                    break
                continue
            if item is None:
                break
            yield f"data: {json.dumps(item, default=str)}\n\n"
        yield 'data: {"type":"done"}\n\n'

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                                      "X-Accel-Buffering": "no"})


@router.get("/assistant/runs")
def assistant_runs(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(m.AgentRun).filter_by(user_id=user.id)
            .order_by(m.AgentRun.id.desc()).limit(30).all())
    return [{"id": r.id, "prompt": r.prompt, "agents": r.agents, "answer": r.answer,
             "status": r.status, "created_at": r.created_at,
             "conversation_id": r.conversation_id} for r in rows]


# --------------------------------------------------------------------------- #
# approvals
# --------------------------------------------------------------------------- #
@router.get("/approvals")
def list_approvals(status: str = "", user: m.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    query = db.query(m.ApprovalRequest).filter_by(user_id=user.id)
    if status:
        query = query.filter(m.ApprovalRequest.status == status)
    rows = query.order_by(m.ApprovalRequest.id.desc()).limit(100).all()
    projects = {p.id: p.name for p in db.query(m.Project).filter_by(owner_id=user.id)}
    return [{**approval_svc.serialize(a), "project": projects.get(a.project_id)}
            for a in rows]


@router.get("/approvals/summary")
def approval_summary(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(m.ApprovalRequest).filter_by(user_id=user.id).all()
    return {"pending": sum(1 for a in rows if a.status == "pending"),
            "approved": sum(1 for a in rows if a.status == "approved"),
            "rejected": sum(1 for a in rows if a.status == "rejected"),
            "expired": sum(1 for a in rows if a.status == "expired"),
            "total": len(rows)}


@router.post("/approvals/{aid}/decide")
def decide_approval(aid: int, body: DecideIn, user: m.User = Depends(require("approval.decide")),
                    db: Session = Depends(get_db)):
    row = db.get(m.ApprovalRequest, aid)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Approval request not found")
    try:
        result = approval_svc.decide(db, row, user, body.approve)
    except approval_svc.ApprovalError as exc:
        raise HTTPException(409, str(exc)) from None
    return result


@router.post("/approvals/{aid}/execute")
def execute_approval(aid: int, user: m.User = Depends(require("approval.decide")),
                     db: Session = Depends(get_db)):
    row = db.get(m.ApprovalRequest, aid)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Approval request not found")
    try:
        return approval_svc.execute_approved(db, row, user)
    except approval_svc.ApprovalError as exc:
        raise HTTPException(409, str(exc)) from None
