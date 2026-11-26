"""Delete synthetic demonstration projects and their child records only.

Real projects are never touched: selection is strictly `Project.is_demo == True`.
Shared catalog data (suppliers, materials, prices, labour rates) and the demo user
account are kept so a reset can reseed projects without recreating credentials.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import models as m


def demo_project_ids(db: Session) -> list[int]:
    return [row[0] for row in db.query(m.Project.id).filter(m.Project.is_demo.is_(True)).all()]


def delete_demo_projects(db: Session) -> dict:
    """Remove demo projects and dependent rows in FK-safe order. Returns counts."""
    pids = demo_project_ids(db)
    if not pids:
        return {"projects": 0}

    item_ids = [row[0] for row in db.query(m.InventoryItem.id)
                .filter(m.InventoryItem.project_id.in_(pids)).all()]
    po_ids = [row[0] for row in db.query(m.PurchaseOrder.id)
              .filter(m.PurchaseOrder.project_id.in_(pids)).all()]
    task_ids = [row[0] for row in db.query(m.Task.id)
                .filter(m.Task.project_id.in_(pids)).all()]
    rule_ids = [row[0] for row in db.query(m.AutomationRule.id)
                .filter(m.AutomationRule.project_id.in_(pids)).all()]

    if item_ids:
        db.query(m.InventoryTxn).filter(m.InventoryTxn.item_id.in_(item_ids)).delete(synchronize_session=False)
    if po_ids:
        db.query(m.POItem).filter(m.POItem.po_id.in_(po_ids)).delete(synchronize_session=False)
    if task_ids:
        db.query(m.TaskDep).filter(m.TaskDep.task_id.in_(task_ids)).delete(synchronize_session=False)
        db.query(m.TaskDep).filter(m.TaskDep.depends_on_id.in_(task_ids)).delete(synchronize_session=False)
    if rule_ids:
        db.query(m.AutomationRun).filter(m.AutomationRun.rule_id.in_(rule_ids)).delete(synchronize_session=False)
        db.query(m.AutomationRule).filter(m.AutomationRule.id.in_(rule_ids)).delete(synchronize_session=False)

    db.query(m.EmailDraft).filter(m.EmailDraft.project_id.in_(pids)).update(
        {m.EmailDraft.approval_id: None}, synchronize_session=False)

    for model in (m.InventoryItem, m.PurchaseOrder, m.Task, m.LabourEntry, m.BOQItem,
                  m.Expense, m.Room, m.Estimation, m.Notification, m.ApprovalRequest):
        db.query(model).filter(model.project_id.in_(pids)).delete(synchronize_session=False)

    # Keep audit, chat and mail history, but detach it from the deleted projects.
    for model in (m.ToolExecution, m.AgentRun, m.ActivityLog, m.Conversation,
                  m.Document, m.EmailDraft):
        db.query(model).filter(model.project_id.in_(pids)).update(
            {model.project_id: None}, synchronize_session=False)

    db.query(m.Project).filter(m.Project.id.in_(pids)).delete(synchronize_session=False)
    db.commit()
    db.expire_all()   # drop deleted objects from the identity map for callers
    return {"projects": len(pids)}
