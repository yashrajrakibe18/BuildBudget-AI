"""Report content checks: readable PDF text and a genuinely formatted workbook."""
import io
import uuid

import pytest
from openpyxl import load_workbook

from app import models as m
from app.core.security import hash_password


def _login(client, db):
    email = f"{uuid.uuid4().hex[:8]}@report.io"
    user = m.User(email=email, name="Report", password_hash=hash_password("TestPass!234"), role="homeowner")
    db.add(user)
    db.commit()
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass!234"})
    assert r.status_code == 200, r.text
    return user


def test_boq_pdf_and_xlsx_are_readable_and_formatted(client, db):
    _login(client, db)
    pid = client.post("/api/v1/projects", json={"name": "Report Room", "budget": 90000,
                                                "location": "Nashik"}).json()["id"]
    line = client.post(f"/api/v1/projects/{pid}/boq/items", json={
        "category": "Flooring", "description": "Vitrified tiles", "unit": "pcs",
        "quantity": 50, "unit_rate": 720, "tax_pct": 18,
    })
    assert line.status_code in (200, 201), line.text

    pdf = client.get(f"/api/v1/projects/{pid}/reports/boq.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open(stream=pdf.content, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    assert doc.page_count >= 1
    assert "BuildBudget AI" in text
    assert "Report Room" in text
    assert "Vitrified tiles" in text
    assert "engineer-approved" in text.lower()

    xlsx = client.get(f"/api/v1/projects/{pid}/reports/boq.xlsx")
    assert xlsx.status_code == 200
    wb = load_workbook(io.BytesIO(xlsx.content))
    assert {"BOQ", "Notes"}.issubset(set(wb.sheetnames))
    ws = wb["BOQ"]
    assert ws.freeze_panes is not None
    assert ws.column_dimensions["C"].width >= 40          # descriptions are not squeezed
    flat = [str(c.value).lower() for row in ws.iter_rows() for c in row if c.value is not None]
    assert "description" in flat and any(v.startswith("rate") for v in flat)
    totals = [c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=SUM(")]
    assert totals, "the total row should use a formula"
    money = [c for row in ws.iter_rows() for c in row if c.number_format and "₹" in c.number_format]
    assert money, "currency cells should use an INR number format"
