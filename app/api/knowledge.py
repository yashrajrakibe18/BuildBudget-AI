"""Knowledge base API: upload, index, search, preview, delete."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app import models as m
from app.api import serialize
from app.api.deps import current_user, owned_project, require
from app.core.labels import DOCUMENT_CATEGORIES, label
from app.database import get_db
from app.services import rag

router = APIRouter()


@router.post("/documents", status_code=201)
async def upload_document(file: UploadFile = File(...), category: str = Form("general"),
                          version: str = Form("1"), project_id: Optional[int] = Form(None),
                          source_url: str = Form(""), published_on: Optional[str] = Form(None),
                          location_scope: str = Form(""),
                          user: m.User = Depends(require("document.write")),
                          db: Session = Depends(get_db)):
    if project_id:
        owned_project(db, user, project_id)
    data = await file.read()
    from datetime import date
    try:
        doc = rag.ingest(db, user.id, file.filename or "upload", data, category, version,
                         project_id, source="uploaded", source_url=source_url,
                         published_on=date.fromisoformat(published_on) if published_on else None,
                         location_scope=location_scope)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"id": doc.id, "name": doc.name, "chunks": doc.chunk_count,
            "document": serialize.document(doc),
            "message": f"Indexed {doc.chunk_count} passage(s) from {doc.name}."}


@router.get("/documents")
def list_documents(project_id: Optional[int] = None, category: str = "", q: str = "",
                   user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    query = db.query(m.Document).filter(m.Document.owner_id == user.id,
                                        m.Document.active.is_(True))
    if project_id:
        owned_project(db, user, project_id)
        query = query.filter(m.Document.project_id == project_id)
    if category:
        query = query.filter(m.Document.category == category)
    if q:
        query = query.filter(m.Document.name.ilike(f"%{q}%"))
    docs = query.order_by(m.Document.id.desc()).all()
    return [serialize.document(d) for d in docs]


@router.get("/documents/stats")
def document_stats(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    stats = rag.stats(db, user.id)
    stats["categories_available"] = [{"key": k, "label": v} for k, v in DOCUMENT_CATEGORIES.items()]
    return stats


@router.get("/documents/search")
def search_documents(q: str = Query(min_length=1), project_id: Optional[int] = None,
                     category: Optional[str] = None, k: int = Query(6, ge=1, le=20),
                     user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if project_id:
        owned_project(db, user, project_id)
    return rag.search(db, user.id, q, project_id, category, k=k)


@router.get("/documents/{doc_id}")
def document_detail(doc_id: int, user: m.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    doc = db.query(m.Document).filter_by(id=doc_id, owner_id=user.id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    chunks = (db.query(m.Chunk).filter_by(document_id=doc_id).order_by(m.Chunk.id).limit(40).all())
    return {**serialize.document(doc),
            "category_label": label(DOCUMENT_CATEGORIES, doc.category),
            "passages": [{"id": c.id, "page": c.page, "section": c.section,
                          "text": c.text} for c in chunks]}


@router.post("/documents/{doc_id}/reindex")
def reindex_document(doc_id: int, user: m.User = Depends(require("document.write")),
                     db: Session = Depends(get_db)):
    doc = db.query(m.Document).filter_by(id=doc_id, owner_id=user.id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    count = rag.reindex(db, doc)
    return {"ok": True, "chunks": count}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, user: m.User = Depends(require("document.write")),
                    db: Session = Depends(get_db)):
    doc = db.query(m.Document).filter_by(id=doc_id, owner_id=user.id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    rag.delete_document(db, doc)
    return {"ok": True, "message": "Document and its indexed passages were deleted."}
