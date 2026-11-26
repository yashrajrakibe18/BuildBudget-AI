"""Pydantic request models for the REST API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

PROJECT_TYPE_KEYS = Literal[
    "single_room", "residential_house", "apartment_renovation", "interior_painting",
    "painting", "kitchen_renovation", "bathroom_renovation", "flooring", "boundary_wall",
    "commercial_renovation", "house_renovation", "interior_finishing", "custom",
]


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: str = "project_manager"
    remember: bool = False


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    remember: bool = False


class ProfileIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    theme: Optional[Literal["light", "dark", "system"]] = None
    units: Optional[Literal["imperial", "metric"]] = None
    currency: Optional[str] = Field(None, max_length=5)
    timezone: Optional[str] = Field(None, max_length=64)
    notify_email: Optional[bool] = None


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=10)
    password: str = Field(min_length=8, max_length=128)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    project_type: PROJECT_TYPE_KEYS = "single_room"
    location: str = Field("", max_length=200)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    contractor: str = Field("", max_length=200)
    manager_name: str = Field("", max_length=120)
    manager_email: str = Field("", max_length=255)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: float = Field(0, ge=0)
    description: str = ""
    assumptions: str = ""
    status: Literal["planning", "active", "on_hold", "completed", "cancelled"] = "planning"

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v, info):
        start = info.data.get("start_date")
        if v and start and v < start:
            raise ValueError("Expected completion date cannot be before the start date")
        return v


class ProjectPatch(ProjectIn):
    name: Optional[str] = Field(None, min_length=1, max_length=200)  # type: ignore[assignment]


class EstimateIn(BaseModel):
    kind: str
    params: dict


class RoomIn(BaseModel):
    name: str = Field("Room", max_length=120)
    length: float = Field(gt=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Literal["ft", "m", "in", "cm"] = "ft"
    openings: list[dict] = []
    notes: str = ""


class ScenarioIn(BaseModel):
    name: str = Field("Scenario", max_length=160)
    kind: str
    params: dict
    unit_rate: Optional[float] = Field(None, ge=0)


class BoqFromEstimate(BaseModel):
    kind: str
    params: dict
    material_name: str = Field(min_length=1)
    category: str = "Finishing"
    unit_rate: Optional[float] = Field(None, ge=0)
    labour_cost: float = Field(0, ge=0)
    transport_cost: float = Field(0, ge=0)
    discount_pct: float = Field(0, ge=0, le=100)
    tax_pct: Optional[float] = Field(None, ge=0, le=100)


class BoqItemIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    category: str = Field("Other", max_length=80)
    unit: str = Field(min_length=1, max_length=20)
    quantity: float = Field(gt=0)
    unit_rate: float = Field(ge=0)
    labour_cost: float = Field(0, ge=0)
    transport_cost: float = Field(0, ge=0)
    discount_pct: float = Field(0, ge=0, le=100)
    tax_pct: float = Field(0, ge=0, le=100)
    assumptions: str = ""


class ExpenseIn(BaseModel):
    category: str
    amount: float = Field(gt=0)
    description: str = ""
    vendor: str = ""
    invoice_no: Optional[str] = None
    expense_date: Optional[date] = None
    payment_status: Literal["paid", "pending", "partial"] = "paid"
    receipt_name: str = ""


class ExpensePatch(BaseModel):
    category: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    description: Optional[str] = None
    vendor: Optional[str] = None
    expense_date: Optional[date] = None
    payment_status: Optional[Literal["paid", "pending", "partial"]] = None


class InventoryIn(BaseModel):
    material_name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=20)
    available: float = Field(0, ge=0)
    reorder_level: float = Field(0, ge=0)
    reserved: float = Field(0, ge=0)
    location: str = ""


class InventoryTxnIn(BaseModel):
    kind: Literal["received", "consumed", "damaged", "wasted", "returned", "adjust"]
    quantity: float = Field(gt=0)
    note: str = ""


class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    duration_days: int = Field(gt=0, le=3650)
    start_date: Optional[date] = None
    depends_on: list[int] = []
    progress: float = Field(0, ge=0, le=100)
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    assignee: str = ""
    milestone: bool = False
    notes: str = ""


class TaskPatch(BaseModel):
    name: Optional[str] = None
    duration_days: Optional[int] = Field(None, gt=0)
    start_date: Optional[date] = None
    progress: Optional[float] = Field(None, ge=0, le=100)
    priority: Optional[Literal["low", "normal", "high", "critical"]] = None
    assignee: Optional[str] = None
    milestone: Optional[bool] = None
    notes: Optional[str] = None
    depends_on: Optional[list[int]] = None


class SupplierIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    location: str = Field("", max_length=200)
    category: str = Field("", max_length=80)
    tax_id: str = Field("", max_length=40)
    notes: str = Field("", max_length=400)
    lead_time_days: int = Field(3, ge=0, le=365)
    payment_terms: str = Field("", max_length=100)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Supplier name is required")
        return v.strip()


class PriceIn(BaseModel):
    material_name: str = Field(min_length=1, max_length=200)
    category: str = "Other"
    unit: str = Field(min_length=1, max_length=20)
    unit_price: float = Field(ge=0)
    tax_pct: float = Field(18, ge=0, le=100)
    delivery_charge: float = Field(0, ge=0)
    moq: float = Field(1, ge=0)
    supplier_id: Optional[int] = None
    valid_until: Optional[date] = None
    source_type: Literal["user_entered", "supplier_quotation", "historical"] = "user_entered"
    brand: str = ""


class LabourRateIn(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    rate: float = Field(ge=0)
    rate_type: Literal["per_day", "per_hour", "per_sqft"] = "per_day"


class LabourEntryIn(BaseModel):
    category: str
    contractor: str = ""
    workers: int = Field(1, ge=1, le=500)
    days: float = Field(1, gt=0, le=366)
    hours_per_day: float = Field(8, gt=0, le=24)
    rate: float = Field(ge=0)
    rate_type: Literal["per_day", "per_hour", "per_sqft"] = "per_day"
    work_date: Optional[date] = None
    note: str = ""


class POIn(BaseModel):
    supplier_id: Optional[int] = None
    expected_date: Optional[date] = None
    notes: str = ""
    items: list[dict] = Field(min_length=1)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=6000)
    project_id: Optional[int] = None
    conversation_id: Optional[int] = None
    document_id: Optional[int] = None


class ConversationPatch(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    pinned: Optional[bool] = None


class DecideIn(BaseModel):
    approve: bool


class DraftIn(BaseModel):
    to: str = ""
    cc: str = ""
    bcc: str = ""
    subject: str = ""
    body: str = ""
    project_id: Optional[int] = None
    supplier_id: Optional[int] = None


class DraftPatch(BaseModel):
    to_addr: Optional[str] = None
    cc_addr: Optional[str] = None
    bcc_addr: Optional[str] = None
    subject: Optional[str] = None
    body_text: Optional[str] = None


class AiMailIn(BaseModel):
    purpose: str = Field(min_length=1, max_length=1200,
                         description="What the email should say or achieve")
    project_id: Optional[int] = None
    tone: str = "professional"
    recipient: str = ""
    subject_hint: str = ""


class ScheduleIn(BaseModel):
    when: datetime


class AutomationIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    trigger: str
    project_id: Optional[int] = None
    threshold: Optional[float] = None
    recipients: str = ""
    template: str = "project_summary"
    schedule: str = ""
    timezone: str = "Asia/Kolkata"
    require_approval: bool = True
    enabled: bool = True


class MarkReadIn(BaseModel):
    ids: list[int] = []
