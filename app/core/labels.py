"""Human-readable labels for every internal identifier shown in the UI.

One source of truth shared by Jinja templates, the REST API (`/meta/labels`)
and the JavaScript renderers, so no screen shows `over_budget` or `single_room`.
"""
from __future__ import annotations

PROJECT_TYPES = {
    "single_room": "Single Room",
    "residential_house": "Residential House",
    "apartment_renovation": "Apartment Renovation",
    "interior_painting": "Interior Painting",
    "painting": "Interior Painting",
    "kitchen_renovation": "Kitchen Renovation",
    "bathroom_renovation": "Bathroom Renovation",
    "flooring": "Flooring",
    "boundary_wall": "Boundary Wall",
    "commercial_renovation": "Commercial Renovation",
    "house_renovation": "House Renovation",
    "interior_finishing": "Interior Finishing",
    "custom": "Custom Project",
}

PROJECT_STATUS = {
    "planning": "Planning",
    "active": "Active",
    "on_hold": "On Hold",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "archived": "Archived",
}

HEALTH_STATUS = {
    "ok": "On Track",
    "warning": "Watch",
    "critical": "At Risk",
    "over_budget": "Over Budget",
    "no_budget": "No Budget Set",
}

APPROVAL_STATUS = {
    "pending": "Pending Review",
    "approved": "Approved",
    "rejected": "Rejected",
    "expired": "Expired",
    "cancelled": "Cancelled",
}

APPROVAL_ACTIONS = {
    "record_expense": "Record Expense",
    "create_project": "Create Project",
    "update_project": "Update Project Details",
    "approve_boq": "Approve Bill of Quantities",
    "create_purchase_order": "Create Purchase Order",
    "stock_adjustment": "Adjust Inventory",
    "send_email": "Send External Email",
    "import_quotation": "Import Supplier Quotation",
    "delete_records": "Delete Records",
    "create_automation": "Enable Automatic Mailing",
}

EMAIL_STATUS = {
    "draft": "Draft",
    "pending_approval": "Pending Approval",
    "scheduled": "Scheduled",
    "sending": "Sending",
    "sent": "Sent",
    "failed": "Failed",
    "cancelled": "Cancelled",
}

NOTIFICATION_KINDS = {
    "budget": "Budget Alert",
    "inventory": "Low Stock",
    "deadline": "Overdue Activity",
    "quotation": "Supplier Quotation",
    "approval": "Approval Request",
    "report": "Report Ready",
    "email": "Email Update",
    "email_failed": "Email Failed",
    "weather": "Weather Advisory",
    "automation": "Automation",
    "test": "Test Message",
    "system": "System",
}

PRIORITY = {"low": "Low", "normal": "Normal", "high": "High", "urgent": "Urgent"}

ROLES = {
    "admin": "Administrator",
    "project_manager": "Project Manager",
    "site_engineer": "Site Engineer",
    "accountant": "Accountant",
    "procurement_manager": "Procurement Manager",
    "viewer": "Viewer",
    "homeowner": "Homeowner",
    "contractor": "Contractor",
    "estimator": "Quantity Surveyor / Estimator",
    "analyst": "Read-only Analyst",
}

ROLE_LABELS = ROLES   # alias used by the page shell

TOOL_LABELS = {
    "list_projects": "List Projects",
    "find_project": "Find Project",
    "get_project_details": "Project Details",
    "get_project_status": "Project Status",
    "get_project_budget": "Retrieve Project Budget",
    "calculate_budget_utilization": "Budget Utilisation",
    "calculate_budget_variance": "Budget Variance",
    "get_project_activity": "Project Activity",
    "calculate_floor_area": "Floor Area",
    "calculate_net_wall_area": "Wall & Ceiling Area",
    "convert_measurement_units": "Unit Conversion",
    "estimate_tile_quantity": "Tile Quantity",
    "estimate_paint_quantity": "Paint Quantity",
    "estimate_brick_quantity": "Brick Quantity",
    "estimate_plaster_materials": "Plaster Materials",
    "estimate_tile_adhesive": "Tile Adhesive",
    "calculate_labour_cost": "Labour Cost",
    "create_boq_draft": "Draft Bill of Quantities",
    "get_boq": "Retrieve Bill of Quantities",
    "calculate_boq_total": "BOQ Total",
    "record_project_expense": "Record Expense",
    "record_expense_draft": "Draft Expense",
    "detect_duplicate_invoice": "Duplicate Invoice Check",
    "get_expense_history": "Expense History",
    "lookup_material_price": "Material Price Lookup",
    "compare_supplier_prices": "Supplier Comparison",
    "calculate_delivered_cost": "Delivered Cost",
    "calculate_purchase_requirements": "Purchase Requirement",
    "create_draft_purchase_order": "Draft Purchase Order",
    "get_delivery_status": "Delivery Status",
    "get_site_inventory": "Site Inventory",
    "check_low_stock": "Low Stock Check",
    "calculate_reorder_quantity": "Reorder Quantity",
    "get_material_consumption": "Material Consumption",
    "get_project_schedule": "Project Schedule",
    "calculate_critical_path": "Critical Path",
    "identify_overdue_tasks": "Overdue Tasks",
    "get_weather_forecast": "Weather Forecast",
    "create_task_draft": "Draft Task",
    "search_construction_knowledge": "Knowledge Search",
    "retrieve_document_passages": "Document Passages",
    "compare_document_sources": "Compare Sources",
    "analyze_expense_trends": "Expense Trends",
    "forecast_project_expenses": "Expense Forecast",
    "detect_unusual_expenses": "Anomaly Detection",
    "calculate_project_health": "Project Health",
    "analyze_supplier_performance": "Supplier Performance",
    "generate_boq_pdf": "BOQ PDF",
    "generate_budget_report": "Budget Report",
    "generate_inventory_report": "Inventory Report",
    "generate_excel_report": "Excel Report",
    "draft_email": "Draft Email",
    "draft_project_email": "Draft Project Email",
    "get_email_status": "Email Status",
    "draft_supplier_rfq": "Draft Supplier RFQ",
    "list_pending_approvals": "Pending Approvals",
    "create_approval_request": "Create Approval Request",
    "get_notification_history": "Notification History",
    "create_project": "Create Project",
}

EXPORT_CATEGORIES = {
    "demonstration": "Synthetic demo data",
    "user_entered": "User entered",
    "supplier_quotation": "Supplier quotation",
    "historical": "Historical reference",
    "live_api": "Live provider data",
    "engineer_approved": "Engineer approved",
}

DOCUMENT_CATEGORIES = {
    "estimation_guidelines": "Estimation Guidelines",
    "material_specifications": "Material Specifications",
    "schedule_of_rates": "Schedule of Rates",
    "approved_specifications": "Approved Specifications",
    "supplier_quotation": "Supplier Quotation",
    "manufacturer_datasheet": "Manufacturer Datasheet",
    "government_guideline": "Government Guideline",
    "project_document": "Project Document",
    "general": "General",
}

EXPENSE_CATEGORIES = [
    "Materials", "Labour", "Equipment", "Transportation", "Professional fees",
    "Permits", "Taxes", "Finishing", "Contingency", "Other",
]

INVENTORY_TXN_KINDS = {
    "received": "Stock In",
    "consumed": "Stock Out (Used)",
    "damaged": "Damaged",
    "wasted": "Wastage",
    "returned": "Returned to Supplier",
    "adjust": "Adjustment",
}

TASK_PRIORITY = {"low": "Low", "normal": "Normal", "high": "High", "critical": "Critical"}

MAIL_FOLDERS = {
    "drafts": "Drafts",
    "pending_approval": "Pending Approval",
    "scheduled": "Scheduled",
    "sent": "Sent",
    "failed": "Failed",
}

AUTOMATION_TRIGGERS = {
    "budget_threshold": "Budget utilisation reaches threshold",
    "over_budget": "Project exceeds approved budget",
    "low_stock": "Material stock below reorder level",
    "overdue_task": "Project task becomes overdue",
    "quotation_expiring": "Supplier quotation about to expire",
    "daily_summary": "Daily project summary",
    "weekly_summary": "Weekly project summary",
    "monthly_expense_report": "Monthly expense report",
    "project_completed": "Project completed",
    "weather_risk": "Weather may disrupt schedule",
}


def label(mapping: dict, key, fallback: str | None = None) -> str:
    if key is None:
        return fallback or "—"
    k = str(key)
    if k in mapping:
        return mapping[k]
    if fallback is not None:
        return fallback
    return k.replace("_", " ").replace("-", " ").strip().title() or "—"


def project_type_label(v) -> str:
    return label(PROJECT_TYPES, v, "Custom Project")


def all_labels() -> dict:
    """Payload for the frontend so labels are never duplicated in JS."""
    return {
        "project_types": PROJECT_TYPES,
        "project_status": PROJECT_STATUS,
        "health_status": HEALTH_STATUS,
        "approval_status": APPROVAL_STATUS,
        "approval_actions": APPROVAL_ACTIONS,
        "email_status": EMAIL_STATUS,
        "notification_kinds": NOTIFICATION_KINDS,
        "priority": PRIORITY,
        "roles": ROLES,
        "tools": TOOL_LABELS,
        "sources": EXPORT_CATEGORIES,
        "document_categories": DOCUMENT_CATEGORIES,
        "expense_categories": EXPENSE_CATEGORIES,
        "inventory_txn_kinds": INVENTORY_TXN_KINDS,
        "task_priority": TASK_PRIORITY,
        "mail_folders": MAIL_FOLDERS,
        "automation_triggers": AUTOMATION_TRIGGERS,
    }
