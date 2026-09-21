"""
AI Agent Tool Registry for Inventory & Sales Management System.

Provides a single `execute_tool(name, user, params)` entry point that the
AI orchestration loop will call. The registry maps tool names to callables
and enforces that only registered, explicitly whitelisted tools can be invoked.

The LLM CANNOT call arbitrary Python. It can only request execution of a
named tool from this registry.
"""

import logging
from typing import Any

from .agent_tools import (
    check_low_stock_products,
    create_draft_purchase_order,
    get_inventory_summary,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Tool Registry — Explicit Whitelist
# ==============================================================================

_TOOL_REGISTRY: dict[str, dict] = {
    "check_low_stock_products": {
        "callable": check_low_stock_products,
        "description": (
            "Identify products where current stock is at or below the reorder level. "
            "Returns structured data including product details, stock levels, reorder "
            "deficits, and supplier contact information."
        ),
        "required_role": "any_authenticated",
        "params_schema": {
            "limit": "int (1–100, default 50) — Maximum number of results to return.",
            "include_out_of_stock": "bool (default true) — Whether to include products with zero stock.",
        },
    },
    "create_draft_purchase_order": {
        "callable": create_draft_purchase_order,
        "description": (
            "Create a new purchase order with status DRAFT for a specified supplier "
            "and line items. Calculates all totals on the backend. "
            "Requires Manager or Admin role."
        ),
        "required_role": "MANAGER or ADMIN",
        "params_schema": {
            "supplier_id": "int (required) — ID of an existing active supplier.",
            "items": (
                "list (required) — Array of line item objects: "
                "[{product_id: int, quantity: int, unit_cost: float}, ...]"
            ),
            "notes": "str (optional, max 500 chars) — Notes or instructions for the PO.",
        },
    },
    "get_inventory_summary": {
        "callable": get_inventory_summary,
        "description": (
            "Retrieve system-wide inventory KPIs: total products, active products, "
            "low-stock count, out-of-stock count, total stock units, total valuation, "
            "and attention count. No parameters required."
        ),
        "required_role": "any_authenticated",
        "params_schema": {},
    },
}


# ==============================================================================
# Public API
# ==============================================================================

def execute_tool(tool_name: str, user, params: dict | None = None) -> dict:
    """
    Execute a named tool from the registry with governance and audit logging.

    This is the single entry point for the AI orchestration loop.
    The LLM passes a tool_name and a params dict; this function looks up
    the tool, validates the name, enforces RBAC, and delegates to the tool function.

    Security properties guaranteed here (in addition to per-tool checks):
      - Only explicitly registered tool names are accepted.
      - Unknown tool names return a controlled error — no arbitrary execution.
      - Enforces strict RBAC: Standard Users are limited to read-only queries.
      - Intercepts and records an AgentAuditLog entry for every execution.

    Args:
        tool_name: The exact name of the tool to execute (from _TOOL_REGISTRY).
        user:      The authenticated Django user object (or AnonymousUser).
        params:    A plain dict of parameters for the tool (may be None or {}).

    Returns:
        A ToolResult dict: {"success": bool, "data": ..., "error": ..., "message": ...}
    """
    from .tools import can_user_execute_tool, record_tool_audit_log

    if not isinstance(tool_name, str) or not tool_name.strip():
        return {
            "success": False,
            "data": None,
            "error": {
                "code": "INVALID_TOOL_NAME",
                "detail": "tool_name must be a non-empty string.",
            },
        }

    tool_name = tool_name.strip()

    if tool_name not in _TOOL_REGISTRY:
        available = ", ".join(sorted(_TOOL_REGISTRY.keys()))
        logger.warning("execute_tool: unknown tool requested: %r", tool_name)
        return {
            "success": False,
            "data": None,
            "error": {
                "code": "UNKNOWN_TOOL",
                "detail": (
                    f"Tool '{tool_name}' is not registered. "
                    f"Available tools: {available}."
                ),
            },
        }

    # 1. RBAC Governance Check
    allowed, denial_reason = can_user_execute_tool(user, tool_name)
    if not allowed:
        logger.warning(
            "execute_tool: RBAC denied '%s' for user '%s': %s",
            tool_name,
            getattr(user, "username", "<anonymous>"),
            denial_reason,
        )
        record_tool_audit_log(
            user=user,
            tool_name=tool_name,
            parameters=params or {},
            status="DENIED",
            response_summary=denial_reason,
        )
        return {
            "success": False,
            "data": None,
            "error": {
                "code": "PERMISSION_DENIED",
                "detail": denial_reason,
            },
            "message": denial_reason,
        }

    tool_fn = _TOOL_REGISTRY[tool_name]["callable"]
    logger.info(
        "execute_tool: invoking '%s' for user '%s'",
        tool_name,
        getattr(user, "username", "<anonymous>"),
    )

    try:
        tool_result = tool_fn(user=user, params=params or {})
    except Exception as exc:
        logger.exception("execute_tool: unhandled exception in tool '%s': %s", tool_name, exc)
        error_msg = f"Unhandled error executing tool '{tool_name}': {exc}"
        record_tool_audit_log(
            user=user,
            tool_name=tool_name,
            parameters=params or {},
            status="FAILED",
            response_summary=error_msg,
        )
        return {
            "success": False,
            "data": None,
            "error": {
                "code": "EXECUTION_ERROR",
                "detail": error_msg,
            },
            "message": error_msg,
        }

    # 2. Persist Audit Log for tool outcome
    if tool_result.get("success"):
        summary = tool_result.get("message") or f"Tool '{tool_name}' executed successfully."
        record_tool_audit_log(
            user=user,
            tool_name=tool_name,
            parameters=params or {},
            status="SUCCESS",
            response_summary=summary,
        )
    else:
        err_obj = tool_result.get("error") or {}
        err_code = err_obj.get("code") if isinstance(err_obj, dict) else ""
        err_detail = (err_obj.get("detail") if isinstance(err_obj, dict) else str(err_obj)) or tool_result.get("message", "")
        status = "DENIED" if err_code in ("PERMISSION_DENIED", "UNAUTHENTICATED") else "FAILED"
        record_tool_audit_log(
            user=user,
            tool_name=tool_name,
            parameters=params or {},
            status=status,
            response_summary=str(err_detail),
        )

    return tool_result


def list_tools() -> list[dict]:
    """
    Returns a list of available tool definitions (name, description, params schema).
    Useful for generating LLM system prompts at runtime.
    Does NOT require authentication — it returns only metadata, no data.
    """
    return [
        {
            "name": name,
            "description": meta["description"],
            "required_role": meta["required_role"],
            "params": meta["params_schema"],
        }
        for name, meta in _TOOL_REGISTRY.items()
    ]
