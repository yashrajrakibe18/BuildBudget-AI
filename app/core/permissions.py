"""Role based access control (enforced on the server for every write).

Capabilities are granular; roles map to capability sets. Legacy role names that
already exist in databases keep working through ROLE_ALIASES.
"""
from __future__ import annotations

READ = "read"

CAPABILITIES: dict[str, set[str]] = {
    "admin": {
        "project.create", "project.edit", "project.delete", "project.archive",
        "boq.write", "expense.write", "inventory.write", "supplier.write",
        "schedule.write", "labour.write", "document.write", "approval.decide",
        "mail.send", "mail.configure", "report.read", "analytics.read",
        "notification.manage", "automation.manage", "settings.manage", "activity.read",
    },
    "project_manager": {
        "project.create", "project.edit", "project.archive", "boq.write", "expense.write",
        "inventory.write", "supplier.write", "schedule.write", "labour.write",
        "document.write", "approval.decide", "mail.send", "report.read",
        "analytics.read", "notification.manage", "automation.manage", "activity.read",
    },
    "site_engineer": {
        "project.edit", "inventory.write", "schedule.write", "labour.write",
        "expense.write", "document.write", "report.read", "activity.read",
    },
    "accountant": {
        "expense.write", "boq.write", "approval.decide", "report.read",
        "analytics.read", "mail.send", "activity.read",
    },
    "procurement_manager": {
        "supplier.write", "inventory.write", "boq.write", "approval.decide",
        "mail.send", "report.read", "analytics.read", "activity.read",
    },
    "viewer": {"report.read"},
}

ROLE_LABELS = {
    "admin": "Administrator",
    "project_manager": "Project Manager",
    "site_engineer": "Site Engineer",
    "accountant": "Accountant",
    "procurement_manager": "Procurement Manager",
    "viewer": "Viewer",
    # legacy roles kept for existing databases
    "homeowner": "Homeowner",
    "contractor": "Contractor",
    "estimator": "Quantity Surveyor / Estimator",
    "analyst": "Read-only Analyst",
}

ROLE_ALIASES = {
    "homeowner": "project_manager",   # project owner: full control of their own data
    "contractor": "site_engineer",
    "estimator": "project_manager",
    "analyst": "viewer",
}

SELF_SIGNUP_ROLES = [
    "project_manager", "site_engineer", "accountant", "procurement_manager", "viewer",
]

# Roles that may create new projects of their own.
CREATOR_ROLES = {"admin", "project_manager", "homeowner", "estimator"}


def effective_role(role: str | None) -> str:
    role = (role or "viewer").lower()
    return ROLE_ALIASES.get(role, role if role in CAPABILITIES else "viewer")


def capabilities(role: str | None) -> set[str]:
    return CAPABILITIES.get(effective_role(role), set())


def can(user, capability: str) -> bool:
    if user is None:
        return False
    return capability in capabilities(getattr(user, "role", None)) or effective_role(getattr(user, "role", None)) == "admin"


def role_label(role: str | None) -> str:
    return ROLE_LABELS.get((role or "viewer").lower(), (role or "Viewer").replace("_", " ").title())


def assert_can(user, capability: str) -> None:
    if not can(user, capability):
        raise PermissionError(
            f"Role '{role_label(getattr(user, 'role', None))}' may not perform '{capability}'"
        )
