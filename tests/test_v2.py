"""v2 behaviour tests: conversations, approvals-once, mail, hybrid RAG, analytics, pages."""
import uuid

from app import models as m
from app.core.config import settings
from app.main import PAGES
from app.services import approvals, conversations, mail


def _register(client, db, role="homeowner"):
    email = f"{uuid.uuid4().hex[:10]}@v2.io"
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "name": "V2", "password": "TestPass!234", "role": role})
    assert r.status_code == 201, r.text
    return db.query(m.User).filter_by(email=email).one()


def test_conversation_persistence_and_isolation(client, db):
    user = _register(client, db)
    conv = conversations.create(db, user.id, None, "Tile planning")
    conversations.add_message(db, conv, "user", "My room is 12 x 15 feet.")
    conversations.add_message(db, conv, "assistant", "Noted — 180 sq ft floor area.")
    conversations.rename(db, conv, "12x15 room")
    conversations.pin(db, conv, True)

    rows = client.get("/api/v1/assistant/conversations").json()
    assert any(r["id"] == conv.id and r["pinned"] and r["title"] == "12x15 room" for r in rows)
    detail = client.get(f"/api/v1/assistant/conversations/{conv.id}").json()
    assert [x["role"] for x in detail["messages"]] == ["user", "assistant"]
    assert "180 sq ft" in detail["messages"][1]["content"]

    # search matches message bodies, not only titles
    found = client.get("/api/v1/assistant/conversations", params={"q": "12 x 15"}).json()
    assert any(r["id"] == conv.id for r in found)

    foreign = conversations.create(db, user.id, None, "Someone else")
    _register(client, db)          # switch the browser session to another account
    assert client.get(f"/api/v1/assistant/conversations/{foreign.id}").status_code == 404
    client.post("/api/v1/auth/logout")
    assert client.get(f"/api/v1/assistant/conversations/{conv.id}").status_code == 401


def test_approval_executes_exactly_once_and_rejects(client, db):
    user = _register(client, db)
    pid = client.post("/api/v1/projects", json={"name": "Approval room", "budget": 50000}).json()["id"]
    row = approvals.create(db, user, action="record_expense", project_id=pid,
                           payload={"category": "Materials", "amount": 1200, "invoice_no": "AP-1"},
                           title="Record expense")
    first = client.post(f"/api/v1/approvals/{row.id}/decide", json={"approve": True})
    assert first.status_code == 200 and first.json()["executed"] is True
    assert db.query(m.Expense).filter_by(project_id=pid, invoice_no="AP-1").count() == 1
    again = client.post(f"/api/v1/approvals/{row.id}/decide", json={"approve": True})
    assert again.status_code == 409
    assert db.query(m.Expense).filter_by(project_id=pid).count() == 1

    rej = approvals.create(db, user, action="record_expense", project_id=pid,
                           payload={"category": "Labour", "amount": 900, "invoice_no": "AP-2"})
    out = client.post(f"/api/v1/approvals/{rej.id}/decide", json={"approve": False})
    assert out.status_code == 200 and out.json()["status"] == "rejected"
    assert db.query(m.Expense).filter_by(project_id=pid).count() == 1


def test_mail_draft_validation_and_approval_send_once(client, db, monkeypatch):
    _register(client, db)
    status = client.get("/api/v1/mail/status").json()
    assert status["gmail"]["implemented"] is False and status["provider"]["inbox_sync"] is False

    no_to = client.post("/api/v1/mail/drafts", json={"to": "", "subject": "Hello", "body": "x"}).json()
    assert client.post(f"/api/v1/mail/{no_to['id']}/request-approval").status_code == 422

    draft = client.post("/api/v1/mail/drafts",
                        json={"to": "pm@example.com", "subject": "Budget warning", "body": "Over budget"}).json()
    blocked = client.post(f"/api/v1/mail/{draft['id']}/request-approval")
    assert blocked.status_code == 409 and "disabled" in blocked.json()["detail"].lower()
    assert client.get(f"/api/v1/mail/{draft['id']}").json()["status"] == "draft"

    sent = []

    class FakeProvider:
        name = "fake"

        def available(self):
            return True, ""

        def send(self, msg):
            sent.append(msg["To"])
            return "<fake@buildbudget.test>"

    monkeypatch.setattr(settings, "email_enabled", True)
    monkeypatch.setattr(mail, "get_provider", lambda: FakeProvider())
    requested = client.post(f"/api/v1/mail/{draft['id']}/request-approval")
    assert requested.status_code == 200
    approval_id = requested.json()["approval_id"]
    assert client.get(f"/api/v1/mail/{draft['id']}").json()["status"] == "pending_approval"
    decided = client.post(f"/api/v1/approvals/{approval_id}/decide", json={"approve": True})
    assert decided.status_code == 200 and decided.json()["executed"] is True
    assert sent == ["pm@example.com"]
    assert client.get(f"/api/v1/mail/{draft['id']}").json()["status"] == "sent"
    assert client.post(f"/api/v1/approvals/{approval_id}/decide", json={"approve": True}).status_code == 409
    assert sent == ["pm@example.com"]          # exactly one provider send


def test_hybrid_rag_dedupe_and_delete(client, db):
    _register(client, db)
    body = (b"# Paint coverage\n\nInterior emulsion covers about 100 sq ft per litre "
            b"per coat according to this demonstration datasheet.")
    first = client.post("/api/v1/documents", files={"file": ("demo_notes.md", body)},
                        data={"category": "estimation_guidelines"})
    assert first.status_code == 201
    dup = client.post("/api/v1/documents", files={"file": ("demo_notes.md", body)},
                      data={"category": "estimation_guidelines"})
    assert dup.status_code == 422 and "already indexed" in dup.json()["detail"]

    hits = client.get("/api/v1/documents/search", params={"q": "emulsion coverage litre"}).json()
    assert hits and hits[0]["document"] == "demo_notes.md"
    assert hits[0]["retrieval"].startswith("hybrid")
    assert 0 < hits[0]["confidence"] <= 1 and hits[0]["page"] is None

    doc_id = first.json()["id"]
    assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 200
    assert client.get("/api/v1/documents/search", params={"q": "emulsion coverage"}).json() == []
    assert db.query(m.Chunk).filter_by(document_id=doc_id).count() == 0


def test_analytics_is_honest_about_insufficient_history(client, db):
    _register(client, db)
    pid = client.post("/api/v1/projects", json={"name": "New analytics room"}).json()["id"]
    out = client.get("/api/v1/analytics", params={"project_id": pid}).json()
    assert out["trend"]["sufficient"] is False
    assert out["forecast"]["sufficient"] is False
    assert "Insufficient data" in out["trend"]["message"]
    assert out["anomalies"]["sufficient"] is False
    assert out["method_notes"]


def test_every_page_renders_with_strict_csp(client, db):
    _register(client, db)
    for slug in PAGES:
        r = client.get(f"/{slug}")
        assert r.status_code == 200, slug
        assert "{{" not in r.text and "{%" not in r.text, slug
        assert "default-src 'self'" in r.headers.get("content-security-policy", ""), slug
    for alias in ("/expenses", "/tasks", "/documents"):
        assert client.get(alias).status_code == 200, alias
    assert client.get("/health").status_code == 200
