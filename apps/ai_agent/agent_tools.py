"""
AI Agent Backend Tools for Inventory & Sales Management System.

This module exposes callable Python functions ("tools") that the AI agent
orchestration layer will invoke. These tools act as a security and validation
gateway — they are NOT Django views and have no HTTP context.

Security Architecture (enforced in every tool):
  1. Authentication  — Rejects anonymous callers immediately.
  2. RBAC            — Checks the minimum required role before any DB access.
  3. Input Validation — Coerces and validates all params via ToolParams dataclasses.
  4. Service Delegation — All writes go through @transaction.atomic services.
  5. Read Delegation  — All reads go through optimized selectors.
  6. Structured Output — Returns a consistent ToolResult dict; the LLM sees only this.

The AI loop MUST NOT:
  - Execute raw SQL.
  - Access Django models directly.
  - Select arbitrary model fields.
  - Bypass this module's authentication or RBAC guards.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.domain_app import selectors, services
from apps.domain_app.models import Product, PurchaseOrder, Supplier

logger = logging.getLogger(__name__)


# ==============================================================================
# Shared Result Type
# ==============================================================================

def _ok(data: Any, message: str = "") -> dict:
    """Constructs a successful ToolResult."""
    return {"success": True, "data": data, "error": None, "message": message}


def _err(message: str, code: str = "TOOL_ERROR") -> dict:
    """Constructs a failed ToolResult."""
    return {"success": False, "data": None, "error": {"code": code, "detail": message}}


# ==============================================================================
# Permission Helpers
# ==============================================================================

def _require_authenticated(user) -> dict | None:
    """
    Returns an error ToolResult if the user is not authenticated.
    Returns None if authentication check passes.
    """
    if user is None or not user.is_authenticated:
        return _err(
            "Authentication required. You must be logged in to use this tool.",
            code="UNAUTHENTICATED",
        )
    return None


def _require_role(user, *allowed_roles) -> dict | None:
    """
    Returns an error ToolResult if the user does not hold one of the allowed roles.
    Returns None if the role check passes.
    Must only be called after _require_authenticated passes.
    """
    if not user.has_role(*allowed_roles):
        role_labels = ", ".join(str(r) for r in allowed_roles)
        return _err(
            f"Permission denied. This action requires one of the following roles: "
            f"{role_labels}. Your current role is: {user.get_role_display()}.",
            code="PERMISSION_DENIED",
        )
    return None


# ==============================================================================
# Tool 1: check_low_stock_products
# ==============================================================================

@dataclass
class CheckLowStockParams:
    """
    Validated parameter schema for check_low_stock_products.

    limit               — Maximum number of results (1–100). Default: 50.
    include_out_of_stock — Whether to include products with zero stock. Default: True.
    """
    limit: int = 50
    include_out_of_stock: bool = True

    @classmethod
    def from_dict(cls, raw: dict) -> "CheckLowStockParams":
        """
        Constructs and validates params from an arbitrary dict (e.g. from the LLM).
        Raises ValueError with a human-readable message on any invalid input.
        """
        errors = []

        # Check for unexpected top-level arguments
        allowed_keys = {"limit", "include_out_of_stock"}
        unexpected_keys = set(raw.keys()) - allowed_keys
        if unexpected_keys:
            errors.append(f"Unexpected argument(s) not permitted: {', '.join(sorted(unexpected_keys))}")

        # --- limit ---
        limit_raw = raw.get("limit", 50)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            errors.append(f"'limit' must be an integer, got: {limit_raw!r}")
            limit = 50  # placeholder; errors list will prevent use

        if not errors and not (1 <= limit <= 100):
            errors.append(f"'limit' must be between 1 and 100, got: {limit}")

        # --- include_out_of_stock ---
        ios_raw = raw.get("include_out_of_stock", True)
        if isinstance(ios_raw, bool):
            include_out_of_stock = ios_raw
        elif isinstance(ios_raw, str) and ios_raw.lower() in ("true", "false"):
            include_out_of_stock = ios_raw.lower() == "true"
        else:
            errors.append(
                f"'include_out_of_stock' must be a boolean (true/false), got: {ios_raw!r}"
            )
            include_out_of_stock = True

        if errors:
            raise ValueError("; ".join(errors))

        return cls(limit=limit, include_out_of_stock=include_out_of_stock)


def check_low_stock_products(user, params: dict) -> dict:
    """
    Tool: check_low_stock_products

    Identifies all products where current_stock <= reorder_level.
    Returns structured, serializable data suitable for the AI agent.

    Minimum required role: Any authenticated user (read-only operation).

    Params (optional):
      limit               (int, 1–100, default 50)
      include_out_of_stock (bool, default true)

    Returns:
      {
        "success": true,
        "data": {
          "count": <int>,
          "items": [
            {
              "product_id": <int>,
              "name": <str>,
              "sku": <str>,
              "current_stock": <int>,
              "reorder_level": <int>,
              "deficit_to_reorder": <int>,
              "suggested_reorder_qty": <int>,
              "urgency": "CRITICAL" | "HIGH",
              "supplier_id": <int | null>,
              "supplier_name": <str | null>,
              "supplier_email": <str | null>,
              "unit_price": <float>
            }, ...
          ]
        }
      }
    """
    # ── 1. Authentication gate ──────────────────────────────────────────────
    auth_err = _require_authenticated(user)
    if auth_err:
        return auth_err

    # ── 2. Parameter validation ─────────────────────────────────────────────
    try:
        validated = CheckLowStockParams.from_dict(params or {})
    except ValueError as exc:
        logger.warning("check_low_stock_products: invalid params: %s", exc)
        return _err(str(exc), code="INVALID_PARAMS")

    # ── 3. Delegate to selector (read-only, no RBAC restriction) ───────────
    try:
        report = selectors.get_low_stock_report(
            user=user,
            include_out_of_stock=validated.include_out_of_stock,
        )
    except Exception as exc:
        logger.exception("check_low_stock_products: unexpected error: %s", exc)
        return _err("An unexpected internal error occurred while retrieving low-stock products.", code="INTERNAL_ERROR")

    # ── 4. Apply limit post-query (selector doesn't accept limit) ──────────
    sliced = report[: validated.limit]

    return _ok(
        data={"count": len(sliced), "total_low_stock": len(report), "items": sliced},
        message=(
            f"Found {len(report)} low-stock product(s). "
            f"Returning {len(sliced)} item(s)."
        ),
    )


# ==============================================================================
# Tool 2: create_draft_purchase_order
# ==============================================================================

@dataclass
class POLineItem:
    """A single validated line item for a purchase order."""
    product_id: int
    quantity: int
    unit_cost: Decimal


@dataclass
class CreateDraftPOParams:
    """
    Validated parameter schema for create_draft_purchase_order.

    supplier_id — ID of an existing active Supplier.
    items       — List of line items: [{product_id, quantity, unit_cost}]
    notes       — Optional free-text notes for the PO.
    """
    supplier_id: int
    items: list[POLineItem]
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "CreateDraftPOParams":
        """
        Constructs and validates params from an arbitrary dict.
        Raises ValueError with a human-readable message on any invalid input.
        """
        errors = []

        # Check for unexpected top-level arguments
        allowed_keys = {"supplier_id", "items", "notes"}
        unexpected_keys = set(raw.keys()) - allowed_keys
        if unexpected_keys:
            errors.append(f"Unexpected argument(s) not permitted: {', '.join(sorted(unexpected_keys))}")

        # --- supplier_id ---
        supplier_id_raw = raw.get("supplier_id")
        if supplier_id_raw is None:
            errors.append("'supplier_id' is required")
            supplier_id = 0  # placeholder
        else:
            try:
                supplier_id = int(supplier_id_raw)
                if supplier_id <= 0:
                    errors.append(f"'supplier_id' must be a positive integer, got: {supplier_id}")
            except (TypeError, ValueError):
                errors.append(f"'supplier_id' must be an integer, got: {supplier_id_raw!r}")
                supplier_id = 0

        # --- items ---
        items_raw = raw.get("items")
        if not items_raw or not isinstance(items_raw, list):
            errors.append("'items' must be a non-empty list of line item objects")
            items = []
        else:
            items = []
            for idx, item in enumerate(items_raw):
                item_errors = []

                if not isinstance(item, dict):
                    item_errors.append("each line item must be a JSON object")
                    errors.append(f"Item #{idx + 1}: " + "; ".join(item_errors))
                    continue

                allowed_item_keys = {"product_id", "quantity", "unit_cost"}
                unexpected_item = set(item.keys()) - allowed_item_keys
                if unexpected_item:
                    item_errors.append(f"Unexpected item field(s): {', '.join(sorted(unexpected_item))}")

                # product_id
                pid_raw = item.get("product_id")
                if pid_raw is None:
                    item_errors.append("'product_id' is required")
                    pid = 0
                else:
                    try:
                        pid = int(pid_raw)
                        if pid <= 0:
                            item_errors.append(f"'product_id' must be positive, got: {pid}")
                    except (TypeError, ValueError):
                        item_errors.append(f"'product_id' must be an integer, got: {pid_raw!r}")
                        pid = 0

                # quantity
                qty_raw = item.get("quantity")
                if qty_raw is None:
                    item_errors.append("'quantity' is required")
                    qty = 0
                else:
                    try:
                        qty = int(qty_raw)
                        if qty < 1:
                            item_errors.append(f"'quantity' must be >= 1, got: {qty}")
                        elif qty > 1_000_000:
                            item_errors.append(f"'quantity' exceeds maximum allowed limit (1,000,000), got: {qty}")
                    except (TypeError, ValueError):
                        item_errors.append(f"'quantity' must be an integer, got: {qty_raw!r}")
                        qty = 0

                # unit_cost
                cost_raw = item.get("unit_cost")
                if cost_raw is None:
                    item_errors.append("'unit_cost' is required")
                    cost = Decimal("0.00")
                else:
                    try:
                        cost = Decimal(str(cost_raw))
                        if cost < Decimal("0.00"):
                            item_errors.append(
                                f"'unit_cost' must be >= 0.00, got: {cost}"
                            )
                        elif cost > Decimal("999999999.99"):
                            item_errors.append(
                                f"'unit_cost' exceeds maximum allowed limit (999,999,999.99), got: {cost}"
                            )
                    except InvalidOperation:
                        item_errors.append(
                            f"'unit_cost' must be a decimal number, got: {cost_raw!r}"
                        )
                        cost = Decimal("0.00")

                if item_errors:
                    errors.append(f"Item #{idx + 1}: " + "; ".join(item_errors))
                else:
                    items.append(POLineItem(product_id=pid, quantity=qty, unit_cost=cost))

            if not items and not errors:
                errors.append("'items' list must contain at least one valid line item")

        # --- notes ---
        notes_raw = raw.get("notes", "")
        if not isinstance(notes_raw, str):
            notes_raw = str(notes_raw)
        notes = notes_raw.strip()[:500]  # enforce max length

        if errors:
            raise ValueError("; ".join(errors))

        return cls(supplier_id=supplier_id, items=items, notes=notes)


def create_draft_purchase_order(user, params: dict) -> dict:
    """
    Tool: create_draft_purchase_order

    Creates a new PurchaseOrder with status=DRAFT for the specified supplier
    and line items. Calculates totals on the backend.

    Minimum required role: MANAGER or ADMIN.

    Required params:
      supplier_id (int)  — ID of an existing active Supplier
      items       (list) — [{"product_id": int, "quantity": int, "unit_cost": float}, ...]

    Optional params:
      notes (str, max 500 chars)

    Returns:
      {
        "success": true,
        "data": {
          "order_number": <str>,
          "purchase_order_id": <int>,
          "supplier_name": <str>,
          "status": "DRAFT",
          "total_amount": <str>,
          "line_items_count": <int>,
          "items": [{"product_name": str, "sku": str, "quantity": int,
                     "unit_cost": str, "subtotal": str}, ...]
        }
      }
    """
    from apps.authentication.models import User as UserModel

    # ── 1. Authentication gate ──────────────────────────────────────────────
    auth_err = _require_authenticated(user)
    if auth_err:
        return auth_err

    # ── 2. RBAC gate (MANAGER or ADMIN required) ────────────────────────────
    role_err = _require_role(user, UserModel.Role.ADMIN, UserModel.Role.MANAGER)
    if role_err:
        return role_err

    # ── 3. Parameter validation ─────────────────────────────────────────────
    try:
        validated = CreateDraftPOParams.from_dict(params or {})
    except ValueError as exc:
        logger.warning("create_draft_purchase_order: invalid params: %s", exc)
        return _err(str(exc), code="INVALID_PARAMS")

    # ── 4. Existence & active checks (read-only, before write) ─────────────
    try:
        supplier = Supplier.objects.get(pk=validated.supplier_id)
    except Supplier.DoesNotExist:
        return _err(
            f"Supplier with ID {validated.supplier_id} does not exist.",
            code="NOT_FOUND",
        )

    if not supplier.is_active:
        return _err(
            f"Supplier '{supplier.name}' (ID: {supplier.pk}) is inactive and cannot "
            f"receive new purchase orders.",
            code="INACTIVE_SUPPLIER",
        )

    # Verify every product exists and is active before delegating to service
    product_ids = [item.product_id for item in validated.items]
    existing_products = {
        p.pk: p for p in Product.objects.filter(pk__in=product_ids)
    }
    product_errors = []
    for item in validated.items:
        if item.product_id not in existing_products:
            product_errors.append(
                f"Product with ID {item.product_id} does not exist."
            )
        elif not existing_products[item.product_id].is_active:
            p = existing_products[item.product_id]
            product_errors.append(
                f"Product '{p.name}' (ID: {p.pk}, SKU: {p.sku}) is inactive."
            )
        elif existing_products[item.product_id].supplier_id and existing_products[item.product_id].supplier_id != supplier.pk:
            p = existing_products[item.product_id]
            product_errors.append(
                f"Product '{p.name}' (ID: {p.pk}, SKU: {p.sku}) belongs to supplier "
                f"ID {p.supplier_id}, not requested supplier '{supplier.name}' (ID: {supplier.pk})."
            )

    if product_errors:
        return _err("; ".join(product_errors), code="INVALID_PRODUCT")

    # ── 4.5. Duplicate Draft PO Protection (Idempotency) ───────────────────
    cutoff = timezone.now() - datetime.timedelta(minutes=5)
    recent_draft_pos = PurchaseOrder.objects.filter(
        supplier=supplier,
        created_by=user,
        status=PurchaseOrder.Status.DRAFT,
        created_at__gte=cutoff,
    ).prefetch_related("items", "items__product")

    target_items_sig = sorted([(item.product_id, item.quantity, item.unit_cost) for item in validated.items])

    duplicate_po = None
    for draft_po in recent_draft_pos:
        existing_sig = sorted([
            (poi.product_id, poi.quantity, poi.unit_cost)
            for poi in draft_po.items.all()
        ])
        if existing_sig == target_items_sig:
            duplicate_po = draft_po
            break

    if duplicate_po:
        logger.info(
            "create_draft_purchase_order: duplicate draft PO prevented for supplier %s (existing PO %s)",
            supplier.pk,
            duplicate_po.order_number,
        )
        items_out = [
            {
                "product_id": poi.product_id,
                "product_name": poi.product.name,
                "sku": poi.product.sku,
                "quantity": poi.quantity,
                "unit_cost": str(poi.unit_cost),
                "subtotal": str(poi.subtotal),
            }
            for poi in duplicate_po.items.select_related("product").all()
        ]
        return _ok(
            data={
                "purchase_order_id": duplicate_po.pk,
                "order_number": duplicate_po.order_number,
                "supplier_id": supplier.pk,
                "supplier_name": supplier.name,
                "status": duplicate_po.status,
                "status_label": duplicate_po.get_status_display(),
                "total_amount": str(duplicate_po.total_amount),
                "line_items_count": len(items_out),
                "notes": duplicate_po.notes,
                "created_by": user.username,
                "items": items_out,
                "duplicate_prevented": True,
            },
            message=(
                f"Existing draft purchase order {duplicate_po.order_number} returned (duplicate prevented). "
                f"A matching draft order was recently created for supplier '{supplier.name}' with total ${duplicate_po.total_amount}."
            ),
        )

    # ── 5. Delegate to service (atomic write) ───────────────────────────────
    items_data = [
        {
            "product_id": item.product_id,
            "quantity": item.quantity,
            "unit_cost": item.unit_cost,
        }
        for item in validated.items
    ]

    try:
        po = services.create_purchase_order(
            supplier=supplier,
            items_data=items_data,
            status="DRAFT",
            notes=validated.notes,
            user=user,
        )
    except (ValidationError, services.PurchaseOrderError) as exc:
        detail = str(exc)
        logger.warning("create_draft_purchase_order: service error: %s", detail)
        return _err(detail, code="VALIDATION_ERROR")
    except Exception as exc:
        logger.exception("create_draft_purchase_order: unexpected error: %s", exc)
        return _err("An unexpected internal error occurred while creating the draft purchase order.", code="INTERNAL_ERROR")

    # ── 6. Serialize response (no model instances in result) ─────────────────
    items_out = [
        {
            "product_id": poi.product_id,
            "product_name": poi.product.name,
            "sku": poi.product.sku,
            "quantity": poi.quantity,
            "unit_cost": str(poi.unit_cost),
            "subtotal": str(poi.subtotal),
        }
        for poi in po.items.select_related("product").all()
    ]

    return _ok(
        data={
            "purchase_order_id": po.pk,
            "order_number": po.order_number,
            "supplier_id": supplier.pk,
            "supplier_name": supplier.name,
            "status": po.status,
            "status_label": po.get_status_display(),
            "total_amount": str(po.total_amount),
            "line_items_count": len(items_out),
            "notes": po.notes,
            "created_by": user.username,
            "items": items_out,
        },
        message=(
            f"Draft purchase order {po.order_number} created successfully for "
            f"supplier '{supplier.name}' with {len(items_out)} line item(s). "
            f"Total: ${po.total_amount}."
        ),
    )


# ==============================================================================
# Tool 3: get_inventory_summary
# ==============================================================================

def get_inventory_summary(user, params: dict) -> dict:
    """
    Tool: get_inventory_summary

    Returns system-wide inventory headline KPIs in a single efficient query.

    Minimum required role: Any authenticated user (read-only operation).

    Params: none required.

    Returns:
      {
        "success": true,
        "data": {
          "total_products": <int>,
          "active_products": <int>,
          "low_stock_count": <int>,
          "out_of_stock_count": <int>,
          "total_stock_units": <int>,
          "total_valuation": <str>,
          "attention_count": <int>
        }
      }
    """
    # ── 1. Authentication gate ──────────────────────────────────────────────
    auth_err = _require_authenticated(user)
    if auth_err:
        return auth_err

    # ── 2. No additional params needed — no validation step required ────────

    # ── 3. Delegate to selector ─────────────────────────────────────────────
    try:
        kpis = selectors.get_inventory_kpis(user=user)
    except Exception as exc:
        logger.exception("get_inventory_summary: unexpected error: %s", exc)
        return _err("An unexpected internal error occurred while retrieving inventory summary.", code="INTERNAL_ERROR")

    return _ok(
        data={
            "total_products": kpis.get("total_products", 0),
            "active_products": kpis.get("active_products", 0),
            "low_stock_count": kpis.get("low_stock_count", 0),
            "out_of_stock_count": kpis.get("out_of_stock_count", 0),
            "total_stock_units": kpis.get("total_units", 0),
            "total_valuation": str(kpis.get("total_valuation", "0.00")),
            "attention_count": kpis.get("attention_count", 0),
        },
        message="Inventory summary retrieved successfully.",
    )
