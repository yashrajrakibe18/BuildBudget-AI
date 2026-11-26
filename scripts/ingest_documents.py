"""Ingest every file in knowledge_base/ for a user.

Usage: python scripts/ingest_documents.py [email]
Safe to re-run: documents already indexed (same content hash) are skipped.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models as m  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.services import rag  # noqa: E402


def main() -> int:
    init_db()
    db = SessionLocal()
    email = sys.argv[1] if len(sys.argv) > 1 else "demo@buildbudget.dev"
    user = db.query(m.User).filter_by(email=email).first()
    if not user:
        print(f"User '{email}' not found — run scripts/seed_demo_data.py or register first.")
        return 1
    ingested = skipped = failed = 0
    root = Path(__file__).resolve().parents[1] / "knowledge_base"
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in rag.ALLOWED:
            continue
        try:
            doc = rag.ingest(db, user.id, path.name, path.read_bytes(),
                             category=path.parent.name if path.parent != root else "general",
                             source=str(path.relative_to(root.parent)))
            print(f"ingested {doc.name}: {doc.chunk_count} chunk(s)")
            ingested += 1
        except ValueError as exc:
            if "already indexed" in str(exc):
                print(f"skipped  {path.name} (already indexed)")
                skipped += 1
            else:
                print(f"failed   {path.name}: {exc}")
                failed += 1
    print(f"\n{ingested} ingested, {skipped} skipped, {failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
