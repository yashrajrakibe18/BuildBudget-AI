import json

from app import models as m
from app.core.config import settings
from app.services import notifications


def mkproject(c, budget=100000, name="Room", **kw):
    return c.post("/api/v1/projects", json={"name": name, "budget": budget, **kw}).json()["id"]


def test_auth_and_isolation(client):
    assert client.get("/api/v1/projects").status_code == 401
    client.post("/api/v1/auth/register", json={"email": "a1@t.io", "name": "A", "password": "TestPass!234"})
    pid = mkproject(client)
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/register", json={"email": "b1@t.io", "name": "B", "password": "TestPass!234"})
    assert client.get(f"/api/v1/projects/{pid}").status_code == 404   # other user's project
    assert client.post("/api/v1/auth/login", json={"email": "a1@t.io", "password": "wrong-pass"}).status_code == 401


def test_readonly_role_cannot_write(client):
    client.post("/api/v1/auth/register", json={"email": "ro@t.io", "name": "R", "password": "TestPass!234", "role": "analyst"})
    assert client.post("/api/v1/projects", json={"name": "x"}).status_code == 403
    assert client.post("/api/v1/auth/register", json={"email": "ad@t.io", "name": "R", "password": "TestPass!234", "role": "admin"}).status_code == 422


def test_estimate_boq_budget_reports(auth):
    pid = mkproject(auth)
    r = auth.post("/api/v1/estimates/calculate", json={"kind": "tiles", "params": {"area_sqft": 180, "tile_length": 24, "tile_width": 24}})
    assert r.json()["final_quantity"] == 50
    # no price stored and no rate given -> must refuse (never invent a price)
    r = auth.post(f"/api/v1/projects/{pid}/boq/from-estimate", json={"kind": "tiles", "params": {"area_sqft": 180, "tile_length": 24, "tile_width": 24}, "material_name": "Nothing"})
    assert r.status_code == 422
    r = auth.post(f"/api/v1/projects/{pid}/boq/from-estimate", json={"kind": "tiles", "params": {"area_sqft": 180, "tile_length": 24, "tile_width": 24}, "material_name": "Tile", "unit_rate": 60, "tax_pct": 18})
    assert r.status_code == 201 and r.json()["item"]["total"] == 3540.0
    auth.post(f"/api/v1/projects/{pid}/expenses", json={"category": "Materials", "amount": 91000, "vendor": "V", "invoice_no": "I1"})
    dup = auth.post(f"/api/v1/projects/{pid}/expenses", json={"category": "Materials", "amount": 5, "vendor": "V", "invoice_no": "I1"})
    assert dup.status_code == 409
    b = auth.get(f"/api/v1/projects/{pid}/budget").json()
    assert b["actual_expenses"] == 91000 and b["remaining_budget"] == 9000 and b["status"] == "critical"
    for name, fmt, magic in (("boq", "xlsx", b"PK"), ("boq", "pdf", b"%PDF"), ("boq", "csv", b"item_no"), ("expenses", "xlsx", b"PK")):
        rr = auth.get(f"/api/v1/projects/{pid}/reports/{name}.{fmt}")
        assert rr.status_code == 200 and rr.content.startswith(magic)


def test_inventory_never_negative_and_schedule(auth):
    pid = mkproject(auth)
    i = auth.post(f"/api/v1/projects/{pid}/inventory", json={"material_name": "Cement", "unit": "bag", "available": 5, "reorder_level": 10}).json()["id"]
    assert auth.post(f"/api/v1/projects/{pid}/inventory/{i}/transactions", json={"kind": "consumed", "quantity": 6}).status_code == 422
    assert auth.post(f"/api/v1/projects/{pid}/inventory/{i}/transactions", json={"kind": "consumed", "quantity": 2}).json()["available"] == 3
    t1 = auth.post(f"/api/v1/projects/{pid}/tasks", json={"name": "A", "duration_days": 3}).json()["id"]
    auth.post(f"/api/v1/projects/{pid}/tasks", json={"name": "B", "duration_days": 2, "depends_on": [t1]})
    assert auth.get(f"/api/v1/projects/{pid}/tasks").json()["cpm"]["total_duration_days"] == 5


def test_price_import_and_compare(auth):
    csvb = b"material_name,category,unit,unit_price,tax_pct,delivery_charge,moq,valid_until\nCement OPC,Cement,bag,400,18,500,10,2099-01-01\nCement OPC,Cement,bag,390,18,900,20,2000-01-01\n"
    r = auth.post("/api/v1/material-prices/import-csv", files={"file": ("p.csv", csvb)})
    assert r.json()["imported"] == 2
    rows = auth.get("/api/v1/suppliers/compare", params={"material": "Cement", "quantity": 4}).json()
    assert rows[0]["unit_price" if False else "total"] == 5220.0 and rows[-1]["expired"] is True


def test_rag_citations_and_isolation(auth, db):
    r = auth.post("/api/v1/documents", files={"file": ("guide.md", b"Paint coverage is 100 sq ft per litre per coat per datasheet.")}, data={"category": "estimation_guidelines"})
    assert r.status_code == 201
    hits = auth.get("/api/v1/documents/search", params={"q": "paint coverage"}).json()
    assert hits and hits[0]["document"] == "guide.md" and "100 sq ft" in hits[0]["excerpt"]
    assert auth.get("/api/v1/documents/search", params={"q": "zzzunknownzzz"}).json() == []
    assert auth.post("/api/v1/documents", files={"file": ("x.exe", b"abc")}).status_code == 422


def test_notifications_dedupe_retry_and_disabled(auth, db, monkeypatch):
    pid = mkproject(auth, budget=100000, name="NotifyProj-XYZ")
    auth.post(f"/api/v1/projects/{pid}/expenses", json={"category": "Materials", "amount": 95000})
    notifications.check_budgets(db); notifications.check_budgets(db)
    keys = [n.alert_key for n in db.query(m.Notification).filter_by(project_id=pid)]
    assert keys == [f"budget:{pid}:90"]                       # one alert, no duplicate
    assert db.query(m.Notification).filter_by(project_id=pid).one().status == "disabled"
    # enable email with failing then working transport
    monkeypatch.setattr(settings, "email_enabled", True)
    monkeypatch.setattr(settings, "notification_email", "me@example.com")
    sent = []
    calls = {"n": 0}
    def flaky(msg):
        if "NotifyProj-XYZ" not in msg.get_content():   # other tests' projects share this DB
            return
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("smtp down")
        sent.append(msg)
    monkeypatch.setattr(notifications, "transport", flaky)
    notifications.check_budgets(db)
    n = db.query(m.Notification).filter_by(project_id=pid).one(); assert n.status == "failed" and "smtp down" in n.error
    notifications.check_budgets(db)
    n = db.query(m.Notification).filter_by(project_id=pid).one(); assert n.status == "sent" and len(sent) == 1
    notifications.check_budgets(db); assert len(sent) == 1   # never re-sent


def test_tools_permissions_and_approval(auth, db):
    from app.ai import tools as T
    pid = mkproject(auth)
    me = db.query(m.User).order_by(m.User.id.desc()).first()
    tl = T.build_tools(db, me, pid)
    out = json.loads(tl["estimate_tile_quantity"].invoke({"area_sqft": 180, "tile_length": 24, "tile_width": 24}))
    assert out["final_quantity"] == 50
    bad = json.loads(tl["estimate_paint_quantity"].invoke({"area_sqft": 100, "coats": 2, "coverage_sqft_per_litre": 100}))
    assert bad["final_quantity"] == 2.1
    appr = json.loads(tl["record_project_expense"].invoke({"category": "Materials", "amount": 500}))
    assert appr["status"] == "approval_required"
    assert db.query(m.Expense).filter_by(project_id=pid).count() == 0      # not committed without approval
    assert db.query(m.ToolExecution).filter_by(project_id=pid).count() >= 3
    ro = m.User(email="ro2@t.io", name="r", password_hash="x", role="analyst"); db.add(ro); db.commit()
    out = json.loads(T.build_tools(db, ro, pid)["record_project_expense"].invoke({"category": "x", "amount": 1}))
    assert "may not perform" in out["error"]


def test_assistant_unavailable_without_llm(auth, monkeypatch):
    """The assistant must degrade honestly when no provider is configured.

    The environment may hold a real key (it does on the developer machine), so the
    key is cleared here: this test is about the *unconfigured* path, not the model.
    """
    from app.core.config import settings
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setitem(settings.api_keys, settings.llm_provider, "")
    r = auth.post("/api/v1/assistant/chat", json={"message": "hi"})
    assert r.status_code == 503 and "unavailable" in r.json()["detail"].lower()


def test_mail_ai_draft_needs_a_brief_and_a_provider(auth, monkeypatch):
    """The AI email writer must fail honestly instead of inventing wording."""
    from app.core.config import settings
    assert auth.post("/api/v1/mail/ai-draft", json={"purpose": "   "}).status_code == 422
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setitem(settings.api_keys, settings.llm_provider, "")
    r = auth.post("/api/v1/mail/ai-draft", json={"purpose": "Ask for a cement delivery date"})
    assert r.status_code == 503 and "unavailable" in r.json()["detail"].lower()
