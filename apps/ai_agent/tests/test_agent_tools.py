"""
Tests for AI Agent Backend Tools.

Covers every tool across four security scenarios:
  A. Unauthenticated user (anonymous)    → UNAUTHENTICATED error
  B. Standard user, manager-only tool    → PERMISSION_DENIED error
  C. Valid role, invalid params           → INVALID_PARAMS or NOT_FOUND error
  D. Valid role, valid params             → success with correct structure

All tests use Django's in-memory test database. No real HTTP requests are made.
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.authentication.models import User
from apps.domain_app.models import Category, Supplier, Product, PurchaseOrder
from apps.ai_agent.agent_tools import (
    check_low_stock_products,
    create_draft_purchase_order,
    get_inventory_summary,
    CheckLowStockParams,
    CreateDraftPOParams,
)
from apps.ai_agent.tool_registry import execute_tool, list_tools


# ==============================================================================
# Helpers
# ==============================================================================

def make_user(username, role):
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="testpass123",
        role=role,
    )


class AnonymousUser:
    """Minimal anonymous user stub (mirrors Django's AnonymousUser)."""
    is_authenticated = False
    username = "<anonymous>"


ANON = AnonymousUser()


# ==============================================================================
# Base setUp — shared fixtures
# ==============================================================================

class ToolTestBase(TestCase):
    """Provides shared DB fixtures for all tool tests."""

    @classmethod
    def setUpTestData(cls):
        # Users
        cls.admin = make_user("admin_user", User.Role.ADMIN)
        cls.manager = make_user("manager_user", User.Role.MANAGER)
        cls.standard = make_user("standard_user", User.Role.STANDARD)

        # Domain fixtures
        cls.category = Category.objects.create(name="Electronics")
        cls.supplier = Supplier.objects.create(
            name="Acme Supplies",
            email="procurement@acme.com",
            phone="555-0100",
        )
        cls.inactive_supplier = Supplier.objects.create(
            name="Defunct Co",
            email="defunct@defunct.com",
            phone="555-0200",
            is_active=False,
        )
        cls.product_low = Product.objects.create(
            name="Widget A",
            sku="WGT-A",
            category=cls.category,
            supplier=cls.supplier,
            price=Decimal("9.99"),
            stock_quantity=2,
            reorder_level=10,
            is_active=True,
        )
        cls.product_ok = Product.objects.create(
            name="Widget B",
            sku="WGT-B",
            category=cls.category,
            supplier=cls.supplier,
            price=Decimal("19.99"),
            stock_quantity=100,
            reorder_level=10,
            is_active=True,
        )
        cls.product_out = Product.objects.create(
            name="Widget C",
            sku="WGT-C",
            category=cls.category,
            supplier=cls.supplier,
            price=Decimal("4.99"),
            stock_quantity=0,
            reorder_level=5,
            is_active=True,
        )
        cls.product_inactive = Product.objects.create(
            name="Retired Widget",
            sku="WGT-RET",
            category=cls.category,
            supplier=cls.supplier,
            price=Decimal("1.00"),
            stock_quantity=0,
            reorder_level=5,
            is_active=False,
        )


# ==============================================================================
# Tests: check_low_stock_products
# ==============================================================================

class TestCheckLowStockProducts(ToolTestBase):

    # ── A. Authentication ───────────────────────────────────────────────────

    def test_anon_user_gets_unauthenticated_error(self):
        result = check_low_stock_products(ANON, {})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UNAUTHENTICATED")

    def test_none_user_gets_unauthenticated_error(self):
        result = check_low_stock_products(None, {})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UNAUTHENTICATED")

    # ── B. RBAC — read-only tool, all roles may access ─────────────────────

    def test_standard_user_can_call_read_only_tool(self):
        result = check_low_stock_products(self.standard, {})
        self.assertTrue(result["success"], result)

    def test_manager_can_call_tool(self):
        result = check_low_stock_products(self.manager, {})
        self.assertTrue(result["success"], result)

    def test_admin_can_call_tool(self):
        result = check_low_stock_products(self.admin, {})
        self.assertTrue(result["success"], result)

    # ── C. Invalid params ───────────────────────────────────────────────────

    def test_invalid_limit_type_returns_error(self):
        result = check_low_stock_products(self.manager, {"limit": "banana"})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_limit_zero_returns_error(self):
        result = check_low_stock_products(self.manager, {"limit": 0})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_limit_above_100_returns_error(self):
        result = check_low_stock_products(self.manager, {"limit": 101})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_invalid_include_out_of_stock_returns_error(self):
        result = check_low_stock_products(self.manager, {"include_out_of_stock": "maybe"})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    # ── D. Successful execution ─────────────────────────────────────────────

    def test_returns_low_stock_products(self):
        result = check_low_stock_products(self.manager, {})
        self.assertTrue(result["success"])
        self.assertIn("count", result["data"])
        self.assertIn("items", result["data"])
        # Widget A (stock=2, reorder=10) and Widget C (stock=0, reorder=5)
        # should appear; Widget B (stock=100) should NOT
        skus = {item["sku"] for item in result["data"]["items"]}
        self.assertIn("WGT-A", skus)
        self.assertIn("WGT-C", skus)
        self.assertNotIn("WGT-B", skus)

    def test_each_item_has_required_fields(self):
        result = check_low_stock_products(self.admin, {})
        self.assertTrue(result["success"])
        required_fields = {
            "product_id", "name", "sku", "current_stock",
            "reorder_level", "deficit_to_reorder", "suggested_reorder_qty",
            "urgency", "supplier_id", "supplier_name", "supplier_email", "unit_price",
        }
        for item in result["data"]["items"]:
            self.assertTrue(
                required_fields.issubset(item.keys()),
                f"Missing fields in item: {required_fields - item.keys()}"
            )

    def test_limit_param_truncates_results(self):
        result = check_low_stock_products(self.admin, {"limit": 1})
        self.assertTrue(result["success"])
        self.assertLessEqual(len(result["data"]["items"]), 1)

    def test_exclude_out_of_stock(self):
        result = check_low_stock_products(self.admin, {"include_out_of_stock": False})
        self.assertTrue(result["success"])
        skus = {item["sku"] for item in result["data"]["items"]}
        # WGT-C has stock=0, so it must be excluded when include_out_of_stock=False
        self.assertNotIn("WGT-C", skus)
        # WGT-A has stock=2 <= reorder_level=10, must be included
        self.assertIn("WGT-A", skus)

    def test_string_true_accepted_for_include_out_of_stock(self):
        result = check_low_stock_products(self.admin, {"include_out_of_stock": "true"})
        self.assertTrue(result["success"])

    def test_message_field_present_in_success(self):
        result = check_low_stock_products(self.admin, {})
        self.assertIn("message", result)
        self.assertIsInstance(result["message"], str)


# ==============================================================================
# Tests: get_inventory_summary
# ==============================================================================

class TestGetInventorySummary(ToolTestBase):

    # ── A. Authentication ───────────────────────────────────────────────────

    def test_anon_user_gets_unauthenticated_error(self):
        result = get_inventory_summary(ANON, {})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UNAUTHENTICATED")

    # ── B. RBAC — read-only, all roles may access ───────────────────────────

    def test_standard_user_can_call(self):
        result = get_inventory_summary(self.standard, {})
        self.assertTrue(result["success"], result)

    # ── D. Successful execution ─────────────────────────────────────────────

    def test_returns_all_required_kpi_keys(self):
        result = get_inventory_summary(self.admin, {})
        self.assertTrue(result["success"])
        required = {
            "total_products", "active_products", "low_stock_count",
            "out_of_stock_count", "total_stock_units", "total_valuation",
            "attention_count",
        }
        self.assertTrue(required.issubset(result["data"].keys()))

    def test_values_are_correct_types(self):
        result = get_inventory_summary(self.admin, {})
        data = result["data"]
        self.assertIsInstance(data["total_products"], int)
        self.assertIsInstance(data["active_products"], int)
        self.assertIsInstance(data["total_valuation"], str)

    def test_total_products_matches_db(self):
        result = get_inventory_summary(self.admin, {})
        # admin sees all (active + inactive) — 4 products created in setUpTestData
        self.assertEqual(result["data"]["total_products"], 4)

    def test_active_products_count(self):
        result = get_inventory_summary(self.admin, {})
        # Only 3 active products (WGT-A, WGT-B, WGT-C); WGT-RET is inactive
        self.assertEqual(result["data"]["active_products"], 3)

    def test_extra_params_are_ignored(self):
        # Tool accepts no params; extra keys must not cause errors
        result = get_inventory_summary(self.admin, {"garbage_key": "garbage_value"})
        self.assertTrue(result["success"])


# ==============================================================================
# Tests: create_draft_purchase_order
# ==============================================================================

class TestCreateDraftPurchaseOrder(ToolTestBase):

    def _valid_params(self):
        return {
            "supplier_id": self.supplier.pk,
            "items": [
                {
                    "product_id": self.product_low.pk,
                    "quantity": 20,
                    "unit_cost": "5.50",
                },
            ],
            "notes": "Replenishment order for low-stock Widget A",
        }

    # ── A. Authentication ───────────────────────────────────────────────────

    def test_anon_user_gets_unauthenticated_error(self):
        result = create_draft_purchase_order(ANON, self._valid_params())
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UNAUTHENTICATED")

    # ── B. RBAC — standard user must be denied ──────────────────────────────

    def test_standard_user_gets_permission_denied(self):
        result = create_draft_purchase_order(self.standard, self._valid_params())
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")

    def test_manager_role_is_allowed(self):
        result = create_draft_purchase_order(self.manager, self._valid_params())
        self.assertTrue(result["success"], result)

    def test_admin_role_is_allowed(self):
        result = create_draft_purchase_order(self.admin, self._valid_params())
        self.assertTrue(result["success"], result)

    # ── C. Invalid params ───────────────────────────────────────────────────

    def test_missing_supplier_id_returns_error(self):
        params = self._valid_params()
        del params["supplier_id"]
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")
        self.assertIn("supplier_id", result["error"]["detail"])

    def test_non_integer_supplier_id_returns_error(self):
        params = {**self._valid_params(), "supplier_id": "abc"}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_negative_supplier_id_returns_error(self):
        params = {**self._valid_params(), "supplier_id": -5}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_empty_items_list_returns_error(self):
        params = {**self._valid_params(), "items": []}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_items_not_a_list_returns_error(self):
        params = {**self._valid_params(), "items": "not-a-list"}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_item_missing_product_id_returns_error(self):
        params = {**self._valid_params(), "items": [{"quantity": 5, "unit_cost": "2.00"}]}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_item_zero_quantity_returns_error(self):
        params = {**self._valid_params(), "items": [
            {"product_id": self.product_low.pk, "quantity": 0, "unit_cost": "2.00"}
        ]}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_item_negative_quantity_returns_error(self):
        params = {**self._valid_params(), "items": [
            {"product_id": self.product_low.pk, "quantity": -3, "unit_cost": "2.00"}
        ]}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_item_negative_unit_cost_returns_error(self):
        params = {**self._valid_params(), "items": [
            {"product_id": self.product_low.pk, "quantity": 5, "unit_cost": "-1.00"}
        ]}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_invalid_unit_cost_string_returns_error(self):
        params = {**self._valid_params(), "items": [
            {"product_id": self.product_low.pk, "quantity": 5, "unit_cost": "twelve"}
        ]}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMS")

    def test_nonexistent_supplier_returns_not_found(self):
        params = {**self._valid_params(), "supplier_id": 99999}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "NOT_FOUND")

    def test_inactive_supplier_returns_error(self):
        params = {**self._valid_params(), "supplier_id": self.inactive_supplier.pk}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INACTIVE_SUPPLIER")

    def test_nonexistent_product_returns_error(self):
        params = {**self._valid_params(), "items": [
            {"product_id": 99999, "quantity": 5, "unit_cost": "2.00"}
        ]}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PRODUCT")

    def test_inactive_product_returns_error(self):
        params = {**self._valid_params(), "items": [
            {
                "product_id": self.product_inactive.pk,
                "quantity": 5,
                "unit_cost": "2.00",
            }
        ]}
        result = create_draft_purchase_order(self.manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PRODUCT")

    # ── D. Successful execution ─────────────────────────────────────────────

    def test_successful_creation_returns_draft_status(self):
        result = create_draft_purchase_order(self.manager, self._valid_params())
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["status"], "DRAFT")

    def test_successful_creation_persists_to_db(self):
        result = create_draft_purchase_order(self.manager, self._valid_params())
        self.assertTrue(result["success"])
        po_id = result["data"]["purchase_order_id"]
        po = PurchaseOrder.objects.get(pk=po_id)
        self.assertEqual(po.status, PurchaseOrder.Status.DRAFT)

    def test_successful_creation_calculates_correct_total(self):
        params = {
            "supplier_id": self.supplier.pk,
            "items": [
                {"product_id": self.product_low.pk, "quantity": 10, "unit_cost": "3.00"},
                {"product_id": self.product_ok.pk, "quantity": 5, "unit_cost": "7.00"},
            ],
        }
        result = create_draft_purchase_order(self.admin, params)
        self.assertTrue(result["success"], result)
        # 10 * 3.00 + 5 * 7.00 = 30.00 + 35.00 = 65.00
        self.assertEqual(result["data"]["total_amount"], "65.00")

    def test_successful_result_has_all_required_fields(self):
        result = create_draft_purchase_order(self.manager, self._valid_params())
        self.assertTrue(result["success"])
        required_fields = {
            "purchase_order_id", "order_number", "supplier_id", "supplier_name",
            "status", "status_label", "total_amount", "line_items_count",
            "notes", "created_by", "items",
        }
        self.assertTrue(required_fields.issubset(result["data"].keys()))

    def test_line_items_have_required_fields(self):
        result = create_draft_purchase_order(self.manager, self._valid_params())
        self.assertTrue(result["success"])
        item_fields = {"product_id", "product_name", "sku", "quantity", "unit_cost", "subtotal"}
        for item in result["data"]["items"]:
            self.assertTrue(item_fields.issubset(item.keys()))

    def test_notes_preserved_in_result(self):
        result = create_draft_purchase_order(self.manager, self._valid_params())
        self.assertTrue(result["success"])
        self.assertIn("Replenishment", result["data"]["notes"])

    def test_created_by_is_correct_user(self):
        result = create_draft_purchase_order(self.manager, self._valid_params())
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["created_by"], self.manager.username)

    def test_zero_unit_cost_is_allowed(self):
        """Unit cost of 0.00 is valid (promotional / donated goods)."""
        params = {**self._valid_params(), "items": [
            {"product_id": self.product_low.pk, "quantity": 5, "unit_cost": "0.00"}
        ]}
        result = create_draft_purchase_order(self.manager, params)
        self.assertTrue(result["success"], result)

    def test_order_number_format(self):
        result = create_draft_purchase_order(self.manager, self._valid_params())
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["order_number"].startswith("PO-"))

    def test_does_not_update_stock_quantity(self):
        """Creating a DRAFT PO must NOT touch product stock — only RECEIVED does."""
        before_stock = self.product_low.stock_quantity
        create_draft_purchase_order(self.manager, self._valid_params())
        self.product_low.refresh_from_db()
        self.assertEqual(self.product_low.stock_quantity, before_stock)


# ==============================================================================
# Tests: execute_tool (registry)
# ==============================================================================

class TestExecuteTool(ToolTestBase):

    def test_unknown_tool_name_returns_error(self):
        result = execute_tool("drop_all_tables", self.admin, {})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UNKNOWN_TOOL")

    def test_empty_tool_name_returns_error(self):
        result = execute_tool("", self.admin, {})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_TOOL_NAME")

    def test_non_string_tool_name_returns_error(self):
        result = execute_tool(None, self.admin, {})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_TOOL_NAME")

    def test_dispatch_check_low_stock_products(self):
        result = execute_tool("check_low_stock_products", self.admin, {"limit": 5})
        self.assertTrue(result["success"], result)

    def test_dispatch_get_inventory_summary(self):
        result = execute_tool("get_inventory_summary", self.admin, {})
        self.assertTrue(result["success"], result)

    def test_dispatch_create_draft_po_as_manager(self):
        params = {
            "supplier_id": self.supplier.pk,
            "items": [
                {"product_id": self.product_low.pk, "quantity": 5, "unit_cost": "2.00"}
            ],
        }
        result = execute_tool("create_draft_purchase_order", self.manager, params)
        self.assertTrue(result["success"], result)

    def test_dispatch_create_draft_po_blocked_for_standard(self):
        params = {
            "supplier_id": self.supplier.pk,
            "items": [
                {"product_id": self.product_low.pk, "quantity": 5, "unit_cost": "2.00"}
            ],
        }
        result = execute_tool("create_draft_purchase_order", self.standard, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")

    def test_none_params_defaults_to_empty_dict(self):
        """Passing None for params must not raise — registry coerces to {}."""
        result = execute_tool("get_inventory_summary", self.admin, None)
        self.assertTrue(result["success"], result)

    def test_list_tools_returns_all_three(self):
        tools = list_tools()
        names = {t["name"] for t in tools}
        self.assertIn("check_low_stock_products", names)
        self.assertIn("create_draft_purchase_order", names)
        self.assertIn("get_inventory_summary", names)

    def test_list_tools_structure(self):
        tools = list_tools()
        for t in tools:
            self.assertIn("name", t)
            self.assertIn("description", t)
            self.assertIn("required_role", t)
            self.assertIn("params", t)


# ==============================================================================
# Tests: Param schema dataclasses (unit tests, no DB)
# ==============================================================================

class TestCheckLowStockParamsSchema(TestCase):

    def test_defaults(self):
        p = CheckLowStockParams.from_dict({})
        self.assertEqual(p.limit, 50)
        self.assertTrue(p.include_out_of_stock)

    def test_valid_limit(self):
        p = CheckLowStockParams.from_dict({"limit": "10"})
        self.assertEqual(p.limit, 10)

    def test_limit_boundary_min(self):
        p = CheckLowStockParams.from_dict({"limit": 1})
        self.assertEqual(p.limit, 1)

    def test_limit_boundary_max(self):
        p = CheckLowStockParams.from_dict({"limit": 100})
        self.assertEqual(p.limit, 100)

    def test_limit_over_max_raises(self):
        with self.assertRaises(ValueError):
            CheckLowStockParams.from_dict({"limit": 101})

    def test_limit_string_alpha_raises(self):
        with self.assertRaises(ValueError):
            CheckLowStockParams.from_dict({"limit": "lots"})

    def test_include_out_of_stock_string_false(self):
        p = CheckLowStockParams.from_dict({"include_out_of_stock": "false"})
        self.assertFalse(p.include_out_of_stock)


class TestCreateDraftPOParamsSchema(TestCase):

    def _minimal(self, supplier_id=1, product_id=1):
        return {
            "supplier_id": supplier_id,
            "items": [{"product_id": product_id, "quantity": 5, "unit_cost": "2.50"}],
        }

    def test_valid_params(self):
        p = CreateDraftPOParams.from_dict(self._minimal())
        self.assertEqual(p.supplier_id, 1)
        self.assertEqual(len(p.items), 1)
        self.assertEqual(p.items[0].quantity, 5)
        self.assertEqual(p.items[0].unit_cost, Decimal("2.50"))

    def test_missing_supplier_raises(self):
        with self.assertRaises(ValueError) as ctx:
            CreateDraftPOParams.from_dict({"items": [{"product_id": 1, "quantity": 1, "unit_cost": "1.00"}]})
        self.assertIn("supplier_id", str(ctx.exception))

    def test_missing_items_raises(self):
        with self.assertRaises(ValueError) as ctx:
            CreateDraftPOParams.from_dict({"supplier_id": 1})
        self.assertIn("items", str(ctx.exception))

    def test_item_quantity_zero_raises(self):
        params = self._minimal()
        params["items"][0]["quantity"] = 0
        with self.assertRaises(ValueError):
            CreateDraftPOParams.from_dict(params)

    def test_notes_truncated_to_500_chars(self):
        params = {**self._minimal(), "notes": "x" * 600}
        p = CreateDraftPOParams.from_dict(params)
        self.assertEqual(len(p.notes), 500)

    def test_decimal_unit_cost_string(self):
        params = self._minimal()
        params["items"][0]["unit_cost"] = "99.99"
        p = CreateDraftPOParams.from_dict(params)
        self.assertEqual(p.items[0].unit_cost, Decimal("99.99"))

    def test_float_unit_cost_accepted(self):
        params = self._minimal()
        params["items"][0]["unit_cost"] = 12.5
        p = CreateDraftPOParams.from_dict(params)
        self.assertEqual(p.items[0].unit_cost, Decimal("12.5"))
