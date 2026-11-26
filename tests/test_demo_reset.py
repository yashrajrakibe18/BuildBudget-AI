"""Demo reset must remove synthetic rows only and never touch real projects."""
import uuid

from app import models as m
from app.services.demo_reset import delete_demo_projects


def _user(db):
    u = m.User(email=f"{uuid.uuid4().hex[:8]}@reset.io", name="R", password_hash="x", role="homeowner")
    db.add(u)
    db.commit()
    return u


def test_demo_reset_only_removes_demo_rows(db):
    user = _user(db)
    demo = m.Project(owner_id=user.id, name="Demo reset target", is_demo=True, budget=1000)
    real = m.Project(owner_id=user.id, name="Real project", is_demo=False, budget=5000)
    db.add_all([demo, real])
    db.commit()
    demo_id, real_id = demo.id, real.id

    db.add_all([
        m.Expense(project_id=demo.id, category="Materials", amount=10, invoice_no="RESET-1"),
        m.Expense(project_id=real.id, category="Materials", amount=20, invoice_no="REAL-1"),
        m.BOQItem(project_id=demo.id, description="Demo line", unit="pcs", quantity=1, unit_rate=10, total=10),
        m.Task(project_id=demo.id, name="Demo task", duration_days=1),
        m.InventoryItem(project_id=demo.id, material_name="Demo cement", unit="bag", available=1),
        m.Notification(owner_id=user.id, project_id=demo.id, alert_key=f"reset:{uuid.uuid4().hex}",
                       kind="budget", subject="Demo alert", body="x"),
    ])
    db.commit()
    demo_task = db.query(m.Task).filter_by(project_id=demo.id).one()
    db.add(m.TaskDep(task_id=demo_task.id, depends_on_id=demo_task.id))

    audit = m.ToolExecution(user_id=user.id, project_id=demo.id, tool="x", status="ok")
    chat = m.Conversation(user_id=user.id, project_id=demo.id, title="Demo chat")
    db.add_all([audit, chat])
    db.commit()

    counts = delete_demo_projects(db)
    assert counts["projects"] == 1
    assert db.get(m.Project, demo_id) is None
    assert db.get(m.Project, real_id) is not None
    assert db.query(m.Expense).filter_by(project_id=demo_id).count() == 0
    assert db.query(m.Expense).filter_by(project_id=real_id).count() == 1
    assert db.query(m.BOQItem).filter_by(project_id=demo_id).count() == 0
    assert db.query(m.Task).filter_by(project_id=demo_id).count() == 0
    assert db.query(m.InventoryItem).filter_by(project_id=demo_id).count() == 0
    assert db.query(m.Notification).filter_by(project_id=demo_id).count() == 0

    # History is kept, but detached from the deleted project.
    db.refresh(audit); db.refresh(chat)
    assert audit.project_id is None and chat.project_id is None

    # A second run is a no-op.
    assert delete_demo_projects(db) == {"projects": 0}
