"""
Tool Definitions, Schema Declarations, Governance & Audit Logging for the AI Agent.

Maps backend inventory tools into native Gemini FunctionDeclaration specifications,
enforces strict Role-Based Access Control (RBAC), parameter sanitization, and
audit log persistence via AgentAuditLog.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import google.generativeai as genai
from google.generativeai import types

from .models import AgentAuditLog
from .tool_registry import _TOOL_REGISTRY

logger = logging.getLogger(__name__)

# Tools that mutate backend state or generate financial commitments (require Manager/Admin privileges)
MUTATION_TOOLS: set[str] = {
    "create_draft_purchase_order",
}

# Tools that require explicit human confirmation before invocation
SENSITIVE_TOOLS: set[str] = {
    "create_draft_purchase_order",
}

# Read-only query tools with zero state mutation (accessible by all authenticated roles)
READ_ONLY_TOOLS: set[str] = {
    "check_low_stock_products",
    "get_inventory_summary",
}

SENSITIVE_PARAM_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "csrfmiddlewaretoken",
    "csrf_token",
    "csrftoken",
    "cookie",
    "session",
    "sessionid",
    "session_key",
    "auth",
    "authorization",
    "bearer",
    "private_key",
    "credential",
    "database_url",
    "db_password",
    "hash",
}


def sanitize_tool_parameters(raw_params: Any) -> Dict[str, Any]:
    """
    Sanitizes raw parameters passed from the LLM or client before audit persistence.

    Guarantees:
    - Always returns a JSON-serializable Python dictionary.
    - Recursively masks any sensitive credential keys in top-level and nested dictionaries.
    - Converts Decimals and custom types to string/number primitives.
    - Scans string values for sensitive credential signatures.
    """
    if not isinstance(raw_params, dict):
        return {"_raw": str(raw_params)}

    sanitized: Dict[str, Any] = {}

    for key, value in raw_params.items():
        # Mask sensitive keys
        if any(secret_word in str(key).lower() for secret_word in SENSITIVE_PARAM_KEYS):
            sanitized[key] = "********"
            continue

        if isinstance(value, dict):
            sanitized[key] = sanitize_tool_parameters(value)
        elif isinstance(value, (list, tuple, set)):
            sanitized[key] = [_sanitize_value(v) for v in value]
        else:
            sanitized[key] = _sanitize_value(value)

    return sanitized


def _sanitize_value(value: Any) -> Any:
    """Recursively converts values to JSON-safe primitives and masks sensitive string patterns."""
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, str):
        val_lower = value.lower()
        # Detect token signatures, API keys, password hashes, and session indicators
        if (
            value.startswith("AIzaSy")
            or value.startswith("sk-")
            or value.startswith("Bearer ")
            or "pbkdf2_sha256$" in value
            or "argon2" in val_lower
            or "sessionid=" in val_lower
            or any(k in val_lower for k in ("db_password", "database_url", "secret_key"))
        ):
            return "********"
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return sanitize_tool_parameters(value)
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(v) for v in value]
    return str(value)


def can_user_execute_tool(user: Any, tool_name: str) -> Tuple[bool, str]:
    """
    Evaluates whether the given user has permission to execute the specified tool.

    RBAC Policy:
    - Unauthenticated users cannot execute any tools.
    - Standard Users are restricted to read-only query tools (check_low_stock_products, get_inventory_summary).
    - Only Manager or Admin users (or superusers) can execute mutation tools (create_draft_purchase_order).

    Returns:
        (allowed: bool, reason: str)
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False, "Authentication required. You must be logged in to execute AI agent tools."

    if not is_tool_registered(tool_name):
        return False, f"Tool '{tool_name}' is not registered or recognized by the system."

    # Mutation tools require elevated Manager or Admin role
    if tool_name in MUTATION_TOOLS:
        is_admin = getattr(user, "role", None) == "ADMIN" or getattr(user, "is_superuser", False)
        is_manager = getattr(user, "role", None) == "MANAGER"

        if hasattr(user, "has_role"):
            has_permission = user.has_role("ADMIN", "MANAGER")
        else:
            has_permission = is_admin or is_manager

        if not has_permission:
            role_display = getattr(user, "get_role_display", lambda: getattr(user, "role", "Standard User"))()
            return False, (
                f"Permission denied: executing '{tool_name}' requires Manager or Admin privileges. "
                f"Your current role is: {role_display}. Standard users can only perform read-only inventory queries."
            )

    return True, ""


def record_tool_audit_log(
    user: Any,
    tool_name: str,
    parameters: Any,
    status: str,
    response_summary: str = "",
) -> Optional[AgentAuditLog]:
    """
    Persists an immutable audit log entry for a tool execution attempt.

    Safely handles unauthenticated users, exceptions, and parameter sanitization.
    """
    try:
        authenticated_user = user if (user and getattr(user, "is_authenticated", False)) else None
        sanitized_params = sanitize_tool_parameters(parameters)

        # Normalize status to valid choices
        valid_statuses = {AgentAuditLog.Status.SUCCESS, AgentAuditLog.Status.DENIED, AgentAuditLog.Status.FAILED}
        normalized_status = status if status in valid_statuses else AgentAuditLog.Status.FAILED

        # Clean response summary text
        clean_summary = str(response_summary or "").strip()

        log_entry = AgentAuditLog.objects.create(
            user=authenticated_user,
            tool_name=str(tool_name)[:100],
            parameters=sanitized_params,
            status=normalized_status,
            response_summary=clean_summary[:4000],
        )
        return log_entry
    except Exception as exc:
        logger.exception("Failed to persist AgentAuditLog for tool '%s': %s", tool_name, exc)
        return None


def get_gemini_function_declarations() -> List[types.FunctionDeclaration]:
    """
    Constructs and returns native Gemini FunctionDeclaration objects for all
    registered tools in the AI Agent tool registry.
    """
    declarations = [
        types.FunctionDeclaration(
            name="check_low_stock_products",
            description=(
                "Identify and return products whose current physical stock is at or below "
                "their reorder level threshold. Includes deficit calculations, suggested "
                "reorder quantities, and supplier association."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "limit": {
                        "type": "INTEGER",
                        "description": "Maximum number of deficit products to return (1-100). Default is 50.",
                    },
                    "include_out_of_stock": {
                        "type": "BOOLEAN",
                        "description": "Whether to include products that are completely out of stock (stock_quantity=0). Default is True.",
                    },
                },
            },
        ),
        types.FunctionDeclaration(
            name="create_draft_purchase_order",
            description=(
                "Create a new purchase order with status DRAFT for an active supplier with "
                "specified line items. Calculates subtotals and total amounts safely on the backend. "
                "Requires Manager or Admin privileges."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "supplier_id": {
                        "type": "INTEGER",
                        "description": "The unique database ID of the active Supplier.",
                    },
                    "items": {
                        "type": "ARRAY",
                        "description": "List of line items to order from this supplier.",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "product_id": {
                                    "type": "INTEGER",
                                    "description": "The unique database ID of the product to order.",
                                },
                                "quantity": {
                                    "type": "INTEGER",
                                    "description": "Quantity to order (must be positive integer >= 1).",
                                },
                                "unit_cost": {
                                    "type": "NUMBER",
                                    "description": "Negotiated or catalog unit cost per product unit (e.g. 12.50).",
                                },
                            },
                            "required": ["product_id", "quantity", "unit_cost"],
                        },
                    },
                    "notes": {
                        "type": "STRING",
                        "description": "Optional notes or reason for this purchase order (e.g. 'Draft generated for low-stock replenishment').",
                    },
                },
                "required": ["supplier_id", "items"],
            },
        ),
        types.FunctionDeclaration(
            name="get_inventory_summary",
            description=(
                "Retrieve high-level system-wide inventory KPIs: total products, active catalog items, "
                "count of low-stock items, out-of-stock items, total units on hand, and total inventory valuation."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {},
            },
        ),
    ]

    return declarations


def is_tool_sensitive(tool_name: str) -> bool:
    """Returns True if the tool performs state mutation or requires user confirmation."""
    return tool_name in SENSITIVE_TOOLS


def is_tool_registered(tool_name: str) -> bool:
    """Returns True if the tool exists in the application's tool registry."""
    return tool_name in _TOOL_REGISTRY
