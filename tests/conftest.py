import os
import tempfile

_d = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_d}/test.db"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["EMAIL_ENABLED"] = "false"
os.environ["SCHEDULER_ENABLED"] = "false"
import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal, init_db
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _db():
    init_db()


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth(client):
    import uuid
    email = f"{uuid.uuid4().hex[:8]}@test.io"
    r = client.post("/api/v1/auth/register", json={"email": email, "name": "T", "password": "TestPass!234"})
    assert r.status_code == 201, r.text
    return client
