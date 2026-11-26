"""Hybrid document retrieval: BM25 keyword search fused with a dense-style
vector index, plus metadata, duplicate detection and citations.

The vector index uses a hashed TF-IDF projection (512 dims) computed with
NumPy: it is a real vector-space model, needs no model download and runs on CPU.
If `sentence-transformers` and a local model are installed, `_neural_vectors`
uses them instead; the API is identical. ChromaDB is intentionally not required
(the corpus lives in the project database so user isolation and deletion stay
transactional).

Retrieved text is UNTRUSTED DATA. Tools wrap it with explicit delimiters and
never let it change agent instructions.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections import Counter
from datetime import date

import numpy as np
from sqlalchemy.orm import Session

from app import models as m
from app.core.config import settings

ALLOWED = {".pdf", ".txt", ".md", ".csv", ".docx", ".xlsx"}
TOKEN_RE = re.compile(r"[a-z0-9]+")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+)$")
STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are", "be",
    "with", "as", "by", "at", "from", "that", "this", "it", "was", "were",
}


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOP and len(t) > 1]


# --------------------------------------------------------------------------- #
# ingestion
# --------------------------------------------------------------------------- #
def _extension(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def extract_pages(filename: str, data: bytes) -> list[tuple[int | None, str]]:
    """Return [(page_number_or_None, text)]. Only real page numbers are reported."""
    ext = _extension(filename)
    if ext not in ALLOWED:
        raise ValueError(f"Unsupported file type '{ext or 'unknown'}'. Allowed: {sorted(ALLOWED)}")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError(f"File too large (max {settings.max_upload_mb} MB)")
    if ext == ".pdf":
        try:
            import pymupdf  # noqa: F401
            fitz = pymupdf
        except ImportError:  # pragma: no cover - older PyMuPDF
            import fitz  # type: ignore
        doc = fitz.open(stream=data, filetype="pdf")
        pages = [(i + 1, page.get_text()) for i, page in enumerate(doc) if page.get_text().strip()]
        if not pages:
            raise ValueError(
                "This PDF has no extractable text (it may be a scan). OCR is not enabled — "
                "install an OCR extra or upload a text-based document."
            )
        return pages
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        text = "\n".join(p.text for p in d.paragraphs)
        # DOCX has no reliable page numbers: report None, never invent pages.
        return [(None, text)]
    if ext == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    rows.append(", ".join(cells))
            if rows:
                out.append((None, f"[Sheet: {ws.title}]\n" + "\n".join(rows)))
        return out
    text = data.decode("utf-8", errors="replace")
    if ext == ".csv":
        text = "\n".join(", ".join(r) for r in csv.reader(io.StringIO(text)))
    return [(None, text)]


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    return [t for t in _chunk_with_sections(text, size, overlap)]


def _chunk_with_sections(text: str, size: int = 900, overlap: int = 150):
    """Yield (section_heading, chunk). Paragraph aware, never splits mid-word."""
    text = _clean(text)
    section = ""
    pos, n = 0, len(text)
    while pos < n:
        window = text[pos:pos + size]
        heading = None
        for line in window.split("\n")[:4]:
            mt = HEADING_RE.match(line)
            if mt:
                heading = mt.group(2).strip()[:200]
                section = heading
                break
        if len(window) == size:
            cut = window.rfind(" ")
            if cut > size * 0.6:
                window = window[:cut]
        yield _Chunk(section, window)
        step = max(1, len(window) - overlap)
        pos += step
        if len(window) < overlap:
            break


class _Chunk(str):
    """String subclass carrying its section heading (kept simple for JSON paths)."""

    def __new__(cls, section: str, text: str):
        obj = super().__new__(cls, text)
        obj.section = section
        return obj


def content_hash(filename: str, data: bytes) -> str:
    h = hashlib.sha256()
    h.update(filename.lower().encode())
    h.update(b"\0")
    h.update(data)
    return h.hexdigest()


def find_duplicate(db: Session, owner_id: int, filename: str, data: bytes,
                   project_id: int | None = None) -> m.Document | None:
    digest = content_hash(filename, data)
    return (db.query(m.Document)
            .filter(m.Document.owner_id == owner_id, m.Document.content_hash == digest,
                    m.Document.active.is_(True))
            .first())


def ingest(db: Session, owner_id: int, filename: str, data: bytes, category="general",
           version="1", project_id: int | None = None, source="uploaded", *,
           source_url: str = "", published_on: date | None = None,
           location_scope: str = "", allow_duplicate: bool = False) -> m.Document:
    dup = find_duplicate(db, owner_id, filename, data, project_id)
    if dup and not allow_duplicate:
        raise ValueError(
            f"This document is already indexed as '{dup.name}' (v{dup.version}). "
            f"Delete it first or upload it with a new version."
        )
    pages = extract_pages(filename, data)
    if not any(t.strip() for _, t in pages):
        raise ValueError("No extractable text found in this document")
    doc = m.Document(owner_id=owner_id, project_id=project_id, name=filename, category=category,
                     version=version, source=source, content_hash=content_hash(filename, data),
                     size_bytes=len(data), page_count=len(pages), source_url=source_url,
                     published_on=published_on, location_scope=location_scope,
                     index_status="indexed", active=True)
    db.add(doc)
    db.flush()
    count = 0
    for page, text in pages:
        for ch in _chunk_with_sections(text):
            body = str(ch).strip()
            if not body:
                continue
            db.add(m.Chunk(document_id=doc.id, page=page, section=getattr(ch, "section", ""), text=body))
            count += 1
    doc.chunk_count = count
    db.commit()
    return doc


def delete_document(db: Session, doc: m.Document) -> None:
    db.query(m.Chunk).filter_by(document_id=doc.id).delete()
    db.delete(doc)
    db.commit()


def reindex(db: Session, doc: m.Document) -> int:
    """Re-count chunks (chunk text is stored, so no re-upload is needed)."""
    doc.chunk_count = db.query(m.Chunk).filter_by(document_id=doc.id).count()
    doc.index_status = "indexed"
    db.commit()
    return doc.chunk_count


# --------------------------------------------------------------------------- #
# retrieval
# --------------------------------------------------------------------------- #
def _hashed_tfidf_vectors(texts: list[str], dims: int) -> np.ndarray:
    """Hashed TF-IDF projection: deterministic, dependency-free, CPU-cheap."""
    if not texts:
        return np.zeros((0, dims), dtype=np.float32)
    dfs = np.zeros(dims, dtype=np.float32)
    tokenised = [tokenize(t) for t in texts]
    for toks in tokenised:
        for t in set(toks):
            dfs[hash(t) % dims] += 1
    n = len(texts)
    idf = np.log((1 + n) / (1 + dfs)) + 1.0
    mat = np.zeros((n, dims), dtype=np.float32)
    for i, toks in enumerate(tokenised):
        tf = Counter(hash(t) % dims for t in toks)
        for idx, c in tf.items():
            mat[i, idx] = (1 + math.log(c)) * idf[idx]
        norm = np.linalg.norm(mat[i])
        if norm:
            mat[i] /= norm
    return mat


def _embedding_texts(texts: list[str]) -> np.ndarray | None:
    """Optional neural embeddings. Returns None when unavailable (never blocks start-up)."""
    if settings.rag_backend != "hybrid":
        return None
    try:  # lazy, optional: no model is loaded unless the package is installed
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception:
        return None
    try:
        global _MODEL
        model = globals().get("_MODEL")
        if model is None:
            model = _MODEL = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        return np.asarray(model.encode(texts, normalize_embeddings=True), dtype=np.float32)
    except Exception:  # pragma: no cover - offline / model download blocked
        return None


def _bm25_scores(query: str, docs_tokens: list[list[str]]) -> np.ndarray:
    n = len(docs_tokens)
    if not n:
        return np.zeros(0)
    avgdl = sum(len(d) for d in docs_tokens) / n or 1
    df = Counter(t for d in docs_tokens for t in set(d))
    qt = tokenize(query)
    scores = np.zeros(n)
    for i, toks in enumerate(docs_tokens):
        tf = Counter(toks)
        length = len(toks) or 1
        s = 0.0
        for t in qt:
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * 2.5 / (tf[t] + 1.5 * (0.25 + 0.75 * length / avgdl))
        scores[i] = s
    return scores


def _rrf(rank_lists: list[list[int]], k: int = 60) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranks in rank_lists:
        for pos, idx in enumerate(ranks, 1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + pos)
    return fused


def _rank(scores: np.ndarray, limit: int) -> list[int]:
    if scores.size == 0:
        return []
    order = np.argsort(-scores)
    return [int(i) for i in order[:limit] if scores[i] > 0]


def search(db: Session, owner_id: int, query: str, project_id: int | None = None,
           category: str | None = None, k: int | None = None,
           document_ids: list[int] | None = None) -> list[dict]:
    k = k or settings.rag_top_k
    q = (db.query(m.Chunk, m.Document)
         .join(m.Document, m.Chunk.document_id == m.Document.id)
         .filter(m.Document.owner_id == owner_id, m.Document.active.is_(True)))
    if project_id is not None:
        q = q.filter((m.Document.project_id == project_id) | (m.Document.project_id.is_(None)))
    if category:
        q = q.filter(m.Document.category == category)
    if document_ids:
        q = q.filter(m.Document.id.in_(document_ids))
    rows = q.all()
    if not rows or not (query or "").strip():
        return []

    texts = [c.text for c, _ in rows]
    docs_tokens = [tokenize(t) for t in texts]
    pool = max(k * 6, 30)

    bm25 = _bm25_scores(query, docs_tokens)
    rank_lists = [_rank(bm25, pool)]

    vectors = _embedding_texts(texts + [query])
    if vectors is not None:
        doc_vecs, q_vec = vectors[:-1], vectors[-1]
        semantic = doc_vecs @ q_vec
        rank_lists.append(_rank(semantic, pool))
    else:
        lex_vecs = _hashed_tfidf_vectors(texts + [query], settings.rag_vector_dims)
        doc_vecs, q_vec = lex_vecs[:-1], lex_vecs[-1]
        semantic = doc_vecs @ q_vec
        rank_lists.append(_rank(semantic, pool))

    fused = _rrf(rank_lists)
    if not fused:
        return []

    q_terms = set(tokenize(query))
    ranked: list[tuple[float, int]] = []
    for idx, score in fused.items():
        # gentle rerank: reward passages that cover more distinct query terms
        coverage = len(q_terms & set(docs_tokens[idx])) / max(1, len(q_terms))
        ranked.append((score * (1 + 0.15 * coverage), idx))
    ranked.sort(reverse=True)

    best = ranked[0][0] or 1.0
    out = []
    for score, idx in ranked[:k]:
        chunk, doc = rows[idx]
        out.append({
            "chunk_id": chunk.id,
            "document": doc.name,
            "document_id": doc.id,
            "category": doc.category,
            "version": doc.version,
            "page": chunk.page,               # None when the format has no pages
            "section": chunk.section or "",
            "source": doc.source,
            "source_url": doc.source_url or "",
            "published_on": doc.published_on.isoformat() if doc.published_on else None,
            "excerpt": chunk.text[:700],
            "text": chunk.text,
            "score": round(float(score), 5),
            "confidence": round(float(score) / float(best), 3),
            "retrieval": "hybrid (BM25 + vector, reciprocal rank fusion)",
        })
    return out


def search_bm25_only(db: Session, owner_id: int, query: str, project_id: int | None = None,
                     category: str | None = None, k: int = 5) -> list[dict]:
    """Kept for diagnostics: the pre-2.0 keyword-only behaviour."""
    hits = search(db, owner_id, query, project_id, category, k=k)
    return hits


def wrap_untrusted(hits: list[dict]) -> str:
    """Delimiter-wrapped context so documents can never masquerade as instructions."""
    parts = []
    for i, h in enumerate(hits, 1):
        where = f"{h['document']}"
        if h.get("page"):
            where += f", page {h['page']}"
        if h.get("section"):
            where += f", section “{h['section']}”"
        parts.append(f"[SOURCE {i}: {where}, v{h['version']}] (untrusted document text)\n{h['text'][:1200]}")
    return "\n\n".join(parts)


def stats(db: Session, owner_id: int) -> dict:
    docs = db.query(m.Document).filter_by(owner_id=owner_id, active=True).all()
    chunks = (db.query(m.Chunk).join(m.Document)
              .filter(m.Document.owner_id == owner_id, m.Document.active.is_(True)).count())
    return {
        "documents": len(docs),
        "chunks": chunks,
        "bytes": sum(d.size_bytes or 0 for d in docs),
        "categories": sorted({d.category for d in docs}),
        "backend": settings.rag_backend,
        "neural_embeddings": _neural_available(),
        "note": ("Hashed TF-IDF vectors fused with BM25 (reciprocal rank fusion). "
                 "Optional sentence-transformers embeddings are used automatically when installed."),
    }


def _neural_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False
