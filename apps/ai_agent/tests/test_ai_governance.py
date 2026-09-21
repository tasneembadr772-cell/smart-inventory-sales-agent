"""
Tests for AI Safety, Tool Governance & AgentAuditLog.

Validates:
1. AgentAuditLog model schema and fields.
2. Parameter sanitization (masking sensitive keys, converting Decimals).
3. RBAC enforcement:
   - Standard Users can execute read-only tools (check_low_stock_products, get_inventory_summary).
   - Standard Users are DENIED from executing mutation tools (create_draft_purchase_order).
   - Managers and Admins are permitted to execute mutation tools.
4. Audit log persistence on SUCCESS, DENIED, and FAILED execution attempts.
5. AgentService integration and friendly error handling without unhandled exceptions.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.authentication.models import User
from apps.domain_app.models import Category, Product, PurchaseOrder, Supplier
from apps.ai_agent.models import AgentAuditLog
from apps.ai_agent.services import AgentService
from apps.ai_agent.tools import (
    can_user_execute_tool,
    record_tool_audit_log,
    sanitize_tool_parameters,
)
from apps.ai_agent.tool_registry import execute_tool


class AIGovernanceAuditLogTests(TestCase):
    """Tests for Tool Governance and AgentAuditLog persistence."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_gov",
            email="admin_gov@test.com",
            password="pass",
            role=User.Role.ADMIN,
        )
        self.manager = User.objects.create_user(
            username="manager_gov",
            email="manager_gov@test.com",
            password="pass",
            role=User.Role.MANAGER,
        )
        self.standard = User.objects.create_user(
            username="standard_gov",
            email="standard_gov@test.com",
            password="pass",
            role=User.Role.STANDARD,
        )

        self.category = Category.objects.create(name="Gov Electronics")
        self.supplier = Supplier.objects.create(
            name="Gov Supplier Ltd",
            contact_person="Jane Doe",
            email="jane@govsupplier.com",
            phone="+1-555-0100",
            address="123 Tech Lane",
            is_active=True,
        )
        self.product = Product.objects.create(
            sku="GOV-PROD-001",
            name="Gov Test Product",
            category=self.category,
            supplier=self.supplier,
            price=Decimal("150.00"),
            stock_quantity=2,
            reorder_level=5,
            is_active=True,
        )

    def test_parameter_sanitization(self):
        """Sensitive credentials must be masked and Decimals serialized."""
        raw_params = {
            "supplier_id": 1,
            "secret_key": "my-ultra-secret",
            "auth_token": "token123",
            "nested": {
                "password": "super-secret-password",
                "cost": Decimal("49.99"),
            },
        }
        sanitized = sanitize_tool_parameters(raw_params)

        self.assertEqual(sanitized["supplier_id"], 1)
        self.assertEqual(sanitized["secret_key"], "********")
        self.assertEqual(sanitized["auth_token"], "********")
        self.assertEqual(sanitized["nested"]["password"], "********")
        self.assertEqual(sanitized["nested"]["cost"], "49.99")

    def test_rbac_check_read_only_tools(self):
        """Standard users must be allowed to execute read-only tools."""
        allowed_kpi, _ = can_user_execute_tool(self.standard, "get_inventory_summary")
        self.assertTrue(allowed_kpi)

        allowed_stock, _ = can_user_execute_tool(self.standard, "check_low_stock_products")
        self.assertTrue(allowed_stock)

    def test_rbac_denies_standard_user_from_mutation_tool(self):
        """Standard users must be DENIED from executing create_draft_purchase_order."""
        allowed, reason = can_user_execute_tool(self.standard, "create_draft_purchase_order")
        self.assertFalse(allowed)
        self.assertIn("Permission denied", reason)
        self.assertIn("Manager or Admin", reason)

    def test_rbac_allows_manager_and_admin_for_mutation_tool(self):
        """Managers and Admins must be permitted to execute mutation tools."""
        allowed_mgr, _ = can_user_execute_tool(self.manager, "create_draft_purchase_order")
        self.assertTrue(allowed_mgr)

        allowed_adm, _ = can_user_execute_tool(self.admin, "create_draft_purchase_order")
        self.assertTrue(allowed_adm)

    def test_execute_tool_logs_denied_audit_for_standard_user(self):
        """Executing mutation tool as Standard user logs DENIED and returns error dict."""
        initial_log_count = AgentAuditLog.objects.count()

        params = {
            "supplier_id": self.supplier.pk,
            "items": [{"product_id": self.product.pk, "quantity": 10, "unit_cost": 120.00}],
        }
        result = execute_tool("create_draft_purchase_order", user=self.standard, params=params)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
        self.assertIn("Permission denied", result["error"]["detail"])

        # Verify audit log record
        self.assertEqual(AgentAuditLog.objects.count(), initial_log_count + 1)
        latest_log = AgentAuditLog.objects.first()
        self.assertEqual(latest_log.user, self.standard)
        self.assertEqual(latest_log.tool_name, "create_draft_purchase_order")
        self.assertEqual(latest_log.status, AgentAuditLog.Status.DENIED)
        self.assertIn("Permission denied", latest_log.response_summary)

    def test_execute_tool_logs_success_audit_for_manager(self):
        """Executing mutation tool as Manager logs SUCCESS and persists Draft PO."""
        initial_log_count = AgentAuditLog.objects.count()

        params = {
            "supplier_id": self.supplier.pk,
            "items": [{"product_id": self.product.pk, "quantity": 5, "unit_cost": 110.00}],
            "notes": "Manager restock order",
        }
        result = execute_tool("create_draft_purchase_order", user=self.manager, params=params)

        self.assertTrue(result["success"])
        self.assertIn("purchase_order_id", result["data"])

        # Verify audit log record
        self.assertEqual(AgentAuditLog.objects.count(), initial_log_count + 1)
        latest_log = AgentAuditLog.objects.first()
        self.assertEqual(latest_log.user, self.manager)
        self.assertEqual(latest_log.tool_name, "create_draft_purchase_order")
        self.assertEqual(latest_log.status, AgentAuditLog.Status.SUCCESS)
        self.assertIn("created successfully", latest_log.response_summary)

    def test_execute_read_only_tool_logs_success_for_standard_user(self):
        """Standard user executing read-only inventory summary logs SUCCESS."""
        initial_log_count = AgentAuditLog.objects.count()

        result = execute_tool("get_inventory_summary", user=self.standard, params={})

        self.assertTrue(result["success"])
        self.assertEqual(AgentAuditLog.objects.count(), initial_log_count + 1)
        latest_log = AgentAuditLog.objects.first()
        self.assertEqual(latest_log.user, self.standard)
        self.assertEqual(latest_log.tool_name, "get_inventory_summary")
        self.assertEqual(latest_log.status, AgentAuditLog.Status.SUCCESS)

    def test_agent_service_loop_rbac_interception(self):
        """AgentService interceptor records DENIED and feeds friendly error back to LLM."""
        # Mock LLM to return function call for create_draft_purchase_order
        mock_fc = MagicMock()
        mock_fc.name = "create_draft_purchase_order"
        mock_fc.args = {
            "supplier_id": self.supplier.pk,
            "items": [{"product_id": self.product.pk, "quantity": 5, "unit_cost": 100.0}],
        }

        mock_part = MagicMock()
        mock_part.function_call = mock_fc
        mock_part.text = None

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        # Second turn: final text response from LLM
        mock_text_part = MagicMock()
        mock_text_part.function_call = None
        mock_text_part.text = "I cannot fulfill this request because your role lacks permission."

        mock_candidate_2 = MagicMock()
        mock_candidate_2.content.parts = [mock_text_part]

        mock_chat = MagicMock()
        mock_chat.send_message.side_effect = [
            MagicMock(candidates=[mock_candidate]),
            MagicMock(candidates=[mock_candidate_2]),
        ]

        mock_model = MagicMock()
        mock_model.start_chat.return_value = mock_chat

        service = AgentService(user=self.standard, model=mock_model)
        result = service.run(goal="Order 5 more processors")

        self.assertTrue(result.success)
        self.assertEqual(result.status, "SUCCESS")

        # Step 1 must have status FAILURE with PERMISSION_DENIED error code
        self.assertEqual(len(result.steps), 1)
        step = result.steps[0]
        self.assertEqual(step["status"], "FAILURE")
        self.assertEqual(step["result"]["error"]["code"], "PERMISSION_DENIED")

        # Audit log must have recorded DENIED
        denied_log = AgentAuditLog.objects.filter(
            user=self.standard,
            tool_name="create_draft_purchase_order",
            status=AgentAuditLog.Status.DENIED,
        ).first()
        self.assertIsNotNone(denied_log)
