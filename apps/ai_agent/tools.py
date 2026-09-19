"""
Tool Definitions and Schema Declarations for the AI Agent.

Maps existing backend inventory tools from `apps.ai_agent.tool_registry` into
native Gemini `FunctionDeclaration` specifications for structured LLM function calling.
"""

from __future__ import annotations

from typing import Any, Dict, List
import google.generativeai as genai
from google.generativeai import types

from .tool_registry import _TOOL_REGISTRY

# Set of tool names that modify state or initiate financial/procurement obligations.
# These actions require explicit user confirmation before execution unless pre-authorized.
SENSITIVE_TOOLS: set[str] = {
    "create_draft_purchase_order",
}

# Read-only query tools with no state mutation.
READ_ONLY_TOOLS: set[str] = {
    "check_low_stock_products",
    "get_inventory_summary",
}


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
