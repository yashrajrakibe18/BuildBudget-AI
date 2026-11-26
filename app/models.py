"""SQLAlchemy models.

Money columns use fixed-precision Numeric/Decimal. All new columns added in 2.0
are nullable or defaulted so an existing database upgrades in place without
data loss (see app/db_migrate.py).
"""
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

Money = Numeric(14, 2)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


ROLES = ["admin", "project_manager", "site_engineer", "accountant",
         "procurement_manager", "viewer", "homeowner", "contractor", "estimator", "analyst"]


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(30), default="project_manager")
    theme: Mapped[str] = mapped_column(String(10), default="system")
    units: Mapped[str] = mapped_column(String(12), default="imperial")
    currency: Mapped[str] = mapped_column(String(5), default="INR")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    project_type: Mapped[str] = mapped_column(String(60), default="single_room")
    location: Mapped[str] = mapped_column(String(200), default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    contractor: Mapped[str] = mapped_column(String(200), default="")
    manager_name: Mapped[str] = mapped_column(String(120), default="")
    manager_email: Mapped[str] = mapped_column(String(255), default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    budget = mapped_column(Money, default=0)
    currency: Mapped[str] = mapped_column(String(5), default="INR")
    description: Mapped[str] = mapped_column(Text, default="")
    assumptions: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="planning")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Room(Base):
    """A measured room inside a project (multi-room estimation)."""
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="Room")
    length: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10), default="ft")
    openings_json: Mapped[str] = mapped_column(Text, default="[]")
    notes: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Estimation(Base):
    """A saved estimation scenario so two options can be compared."""
    __tablename__ = "estimations"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), default="Scenario")
    kind: Mapped[str] = mapped_column(String(40))
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    total_estimate = mapped_column(Money, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    unit: Mapped[str] = mapped_column(String(20))
    specification: Mapped[str] = mapped_column(String(300), default="")
    __table_args__ = (UniqueConstraint("name", "category"),)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(80), default="")
    tax_id: Mapped[str] = mapped_column(String(40), default="")
    notes: Mapped[str] = mapped_column(String(400), default="")
    lead_time_days: Mapped[int] = mapped_column(Integer, default=3)
    payment_terms: Mapped[str] = mapped_column(String(100), default="")
    reliability: Mapped[float] = mapped_column(Float, default=0.8)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MaterialPrice(Base):
    """source_type: demonstration | user_entered | historical | supplier_quotation | live_api"""
    __tablename__ = "material_prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    brand: Mapped[str] = mapped_column(String(100), default="")
    unit_price = mapped_column(Money)
    tax_pct: Mapped[float] = mapped_column(Float, default=18.0)
    delivery_charge = mapped_column(Money, default=0)
    moq: Mapped[float] = mapped_column(Float, default=1)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    quotation_date: Mapped[date] = mapped_column(Date, default=date.today)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), default="user_entered")
    material = relationship("Material")
    supplier = relationship("Supplier")


class LabourRate(Base):
    __tablename__ = "labour_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(80))
    rate_type: Mapped[str] = mapped_column(String(20), default="per_day")
    rate = mapped_column(Money)
    source_type: Mapped[str] = mapped_column(String(30), default="user_entered")


class LabourEntry(Base):
    """Actual labour used on site: workers x days x agreed rate."""
    __tablename__ = "labour_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    category: Mapped[str] = mapped_column(String(80))
    contractor: Mapped[str] = mapped_column(String(160), default="")
    workers: Mapped[int] = mapped_column(Integer, default=1)
    days: Mapped[float] = mapped_column(Float, default=1)
    hours_per_day: Mapped[float] = mapped_column(Float, default=8)
    rate = mapped_column(Money, default=0)
    rate_type: Mapped[str] = mapped_column(String(20), default="per_day")
    work_date: Mapped[date] = mapped_column(Date, default=date.today)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class BOQItem(Base):
    __tablename__ = "boq_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    item_no: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(String(300))
    unit: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[float] = mapped_column(Float)
    unit_rate = mapped_column(Money)
    material_cost = mapped_column(Money, default=0)
    labour_cost = mapped_column(Money, default=0)
    transport_cost = mapped_column(Money, default=0)
    discount_pct: Mapped[float] = mapped_column(Float, default=0)
    wastage_pct: Mapped[float] = mapped_column(Float, default=0)
    tax_pct: Mapped[float] = mapped_column(Float, default=0)
    total = mapped_column(Money, default=0)
    rate_source: Mapped[str] = mapped_column(String(40), default="user_entered")
    source_reference: Mapped[str] = mapped_column(String(300), default="")
    price_valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    assumptions: Mapped[str] = mapped_column(Text, default="")
    approval_status: Mapped[str] = mapped_column(String(20), default="draft")


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(300), default="")
    amount = mapped_column(Money)
    expense_date: Mapped[date] = mapped_column(Date, default=date.today)
    vendor: Mapped[str] = mapped_column(String(200), default="")
    invoice_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(20), default="paid")
    approval_status: Mapped[str] = mapped_column(String(20), default="recorded")
    receipt_name: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("project_id", "vendor", "invoice_no", name="uq_invoice"),
                      Index("ix_expense_project_date", "project_id", "expense_date"))


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    material_name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(20))
    available: Mapped[float] = mapped_column(Float, default=0)
    reserved: Mapped[float] = mapped_column(Float, default=0)
    incoming: Mapped[float] = mapped_column(Float, default=0)
    damaged: Mapped[float] = mapped_column(Float, default=0)
    reorder_level: Mapped[float] = mapped_column(Float, default=0)
    location: Mapped[str] = mapped_column(String(100), default="")
    __table_args__ = (UniqueConstraint("project_id", "material_name"),)


class InventoryTxn(Base):
    __tablename__ = "inventory_txns"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # received|consumed|damaged|wasted|returned|adjust
    quantity: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    number: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|ordered|partially_delivered|received|cancelled
    notes: Mapped[str] = mapped_column(String(500), default="")
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total = mapped_column(Money, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    items = relationship("POItem", cascade="all, delete-orphan")
    supplier = relationship("Supplier")


class POItem(Base):
    __tablename__ = "po_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    material_name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[float] = mapped_column(Float)
    unit_price = mapped_column(Money)
    line_total = mapped_column(Money)
    received_qty: Mapped[float] = mapped_column(Float, default=0)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    duration_days: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0)
    actual_completion: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    assignee: Mapped[str] = mapped_column(String(120), default="")
    milestone: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(String(500), default="")
    deps = relationship("TaskDep", cascade="all, delete-orphan", foreign_keys="TaskDep.task_id")


class TaskDep(Base):
    __tablename__ = "task_deps"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    depends_on_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(60), default="general")
    version: Mapped[str] = mapped_column(String(40), default="1")
    source: Mapped[str] = mapped_column(String(300), default="uploaded")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    index_status: Mapped[str] = mapped_column(String(20), default="indexed")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    published_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    location_scope: Mapped[str] = mapped_column(String(120), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[str] = mapped_column(Text)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    alert_key: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(40), default="system")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(300), default="")
    recipient: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|sent|failed|disabled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    tool: Mapped[str] = mapped_column(String(80))
    args: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(10))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[str] = mapped_column(Text)
    before_state: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(15), default="pending")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    execution_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    messages = relationship("ChatMessage", cascade="all, delete-orphan",
                            order_by="ChatMessage.id", back_populates="conversation")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, default="")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")  # agents, tools, citations, status
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    conversation = relationship("Conversation", back_populates="messages")


class EmailDraft(Base):
    """An outgoing email. Never sent by the model directly: approval is required."""
    __tablename__ = "email_drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_addr: Mapped[str] = mapped_column(String(500), default="")
    cc_addr: Mapped[str] = mapped_column(String(500), default="")
    bcc_addr: Mapped[str] = mapped_column(String(500), default="")
    subject: Mapped[str] = mapped_column(String(300), default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    attachments_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    provider: Mapped[str] = mapped_column(String(20), default="smtp")
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    message_id: Mapped[str] = mapped_column(String(200), default="")
    idempotency_key: Mapped[str] = mapped_column(String(80), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    trigger: Mapped[str] = mapped_column(String(40))
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    recipients: Mapped[str] = mapped_column(String(500), default="")
    template: Mapped[str] = mapped_column(String(60), default="project_summary")
    schedule: Mapped[str] = mapped_column(String(40), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AutomationRun(Base):
    __tablename__ = "automation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("automation_rules.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt: Mapped[str] = mapped_column(Text)
    agents: Mapped[str] = mapped_column(String(300), default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
