"""
Comprehensive Test Suite for the Agentic AI Workflow Service.

Validates the complete Agentic Loop across:
1. Unauthorized user access prevention (anonymous or None user).
2. Simple tool call execution (single-turn function calling).
3. Multi-step procurement workflow (check low stock -> analyze -> create draft PO -> final summary).
4. Sensitive action confirmation gating (pausing on create_draft_purchase_order).
5. Invalid tool parameter handling (validation error handled gracefully).
6. Unknown tool name rejection (whitelist safety enforcement).
7. Permission boundary inheritance (Standard user blocked from Manager-only tool).
"""

from decimal import Decimal
from unittest.mock import MagicMock

from django.test import TestCase

from apps.authentication.models import User
from apps.domain_app.models import Category, Supplier, Product, PurchaseOrder
from apps.ai_agent.services import AgentService, AgentResult
from apps.ai_agent.tools import SENSITIVE_TOOLS


# ==============================================================================
# Mock Helpers for Gemini GenerativeModel
# ==============================================================================

class MockPart:
    """Mock for a Gemini Candidate Part containing text and/or function_call."""
    def __init__(self, text=None, function_name=None, function_args=None):
        self.text = text
        if function_name:
            fc = MagicMock()
            fc.name = function_name
            fc.args = function_args or {}
            self.function_call = fc
        else:
            self.function_call = None


class MockCandidate:
    def __init__(self, parts):
        content = MagicMock()
        content.parts = parts
        self.content = content


class MockResponse:
    def __init__(self, parts):
        self.candidates = [MockCandidate(parts)]


class MockChatSession:
    """
    Simulates a multi-turn chat session with Gemini, returning sequential
    mock responses upon each send_message invocation.
    """
    def __init__(self, responses):
        self.responses = list(responses)
        self.call_history = []

    def send_message(self, message):
        self.call_history.append(message)
        if not self.responses:
            # Default fallback: return text
            return MockResponse([MockPart(text="Task completed.")])
        return self.responses.pop(0)


class MockGenerativeModel:
    def __init__(self, responses):
        self.chat = MockChatSession(responses)

    def start_chat(self, enable_automatic_function_calling=False):
        return self.chat


# ==============================================================================
# Agent Service Tests
# ==============================================================================

class AgentServiceWorkflowTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Create users with different RBAC roles
        cls.admin = User.objects.create_user(
            username="agent_admin",
            email="admin@agent.test",
            password="testpass123",
            role=User.Role.ADMIN,
        )
        cls.manager = User.objects.create_user(
            username="agent_manager",
            email="manager@agent.test",
            password="testpass123",
            role=User.Role.MANAGER,
        )
        cls.standard = User.objects.create_user(
            username="agent_standard",
            email="standard@agent.test",
            password="testpass123",
            role=User.Role.STANDARD,
        )

        # Domain fixtures: Category, Supplier, Products
        cls.category = Category.objects.create(name="Machinery")
        cls.supplier = Supplier.objects.create(
            name="Industrial Parts Direct",
            email="orders@industrialparts.com",
            phone="555-4321",
            is_active=True,
        )
        cls.low_stock_product = Product.objects.create(
            name="Bearing 608RS",
            sku="BRG-608",
            category=cls.category,
            supplier=cls.supplier,
            price=Decimal("15.00"),
            stock_quantity=3,
            reorder_level=15,
            target_stock_level=30,
            is_active=True,
        )
        cls.healthy_product = Product.objects.create(
            name="Linear Rail HGR20",
            sku="RL-HGR20",
            category=cls.category,
            supplier=cls.supplier,
            price=Decimal("85.00"),
            stock_quantity=50,
            reorder_level=10,
            is_active=True,
        )

    # ── 1. Authentication Tests ─────────────────────────────────────────────

    def test_unauthenticated_anonymous_user_is_blocked(self):
        """Anonymous callers must be rejected immediately without calling LLM."""
        anon = MagicMock()
        anon.is_authenticated = False
        service = AgentService(user=anon, api_key="fake-key")

        result = service.run("Check inventory summary")
        self.assertFalse(result.success)
        self.assertEqual(result.status, "UNAUTHORIZED")
        self.assertIn("Authentication required", result.final_answer)
        self.assertEqual(len(result.tools_executed), 0)

    def test_none_user_is_blocked(self):
        """None user must be rejected with UNAUTHORIZED."""
        service = AgentService(user=None, api_key="fake-key")
        result = service.run("Check inventory summary")
        self.assertFalse(result.success)
        self.assertEqual(result.status, "UNAUTHORIZED")

    # ── 2. Simple Tool Call ─────────────────────────────────────────────────

    def test_simple_tool_call_get_inventory_summary(self):
        """
        Tests a single-tool execution:
        Turn 1: Model calls `get_inventory_summary`.
        Turn 2: Model returns final natural language summary.
        """
        turn1_response = MockResponse([
            MockPart(
                text="Checking system-wide inventory KPIs...",
                function_name="get_inventory_summary",
                function_args={},
            )
        ])
        turn2_response = MockResponse([
            MockPart(
                text="Currently, there are 2 total products in the catalog with 1 product running low on stock."
            )
        ])

        mock_model = MockGenerativeModel([turn1_response, turn2_response])
        service = AgentService(user=self.manager, model=mock_model)

        result = service.run("What is the current inventory status?")

        self.assertTrue(result.success)
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.tools_executed, ["get_inventory_summary"])
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(result.steps[0]["tool"], "get_inventory_summary")
        self.assertTrue(result.steps[0]["result"]["success"])
        self.assertIn("total products", result.final_answer)

    # ── 3. Multi-Step Workflow ──────────────────────────────────────────────

    def test_multi_step_replenishment_workflow(self):
        """
        Tests the example supported user goal:
        'Check which products are low in stock and prepare draft purchase orders.'

        Workflow:
        Turn 1: Model calls `check_low_stock_products`.
        Turn 2: Model calls `create_draft_purchase_order` for the supplier.
        Turn 3: Model returns final executive summary of the created PO.
        """
        turn1_response = MockResponse([
            MockPart(
                text="First, I will identify products at or below their reorder level.",
                function_name="check_low_stock_products",
                function_args={"limit": 10, "include_out_of_stock": True},
            )
        ])

        # After receiving low-stock result, the model prepares a draft PO
        turn2_response = MockResponse([
            MockPart(
                text="Bearing 608RS is low in stock (3 on hand, reorder level 15). Creating draft PO for Industrial Parts Direct.",
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [
                        {
                            "product_id": self.low_stock_product.pk,
                            "quantity": 27,
                            "unit_cost": 15.00,
                        }
                    ],
                    "notes": "Automated replenishment draft generated by AI agent.",
                },
            )
        ])

        turn3_response = MockResponse([
            MockPart(
                text="Successfully prepared draft purchase order for Industrial Parts Direct with 27 units of Bearing 608RS."
            )
        ])

        mock_model = MockGenerativeModel([turn1_response, turn2_response, turn3_response])
        service = AgentService(user=self.manager, model=mock_model)

        # Run with auto_confirm=True so multi-step execution proceeds to completion
        result = service.run(
            goal="Check which products are low in stock and prepare draft purchase orders.",
            auto_confirm=True,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(
            result.tools_executed,
            ["check_low_stock_products", "create_draft_purchase_order"],
        )
        self.assertEqual(len(result.steps), 2)
        self.assertEqual(result.steps[0]["tool"], "check_low_stock_products")
        self.assertEqual(result.steps[1]["tool"], "create_draft_purchase_order")
        self.assertTrue(result.steps[1]["result"]["success"])

        # Verify a real PurchaseOrder was created in the database
        created_po_id = result.steps[1]["result"]["data"]["purchase_order_id"]
        po = PurchaseOrder.objects.get(pk=created_po_id)
        self.assertEqual(po.status, PurchaseOrder.Status.DRAFT)
        self.assertEqual(po.supplier, self.supplier)
        self.assertEqual(po.created_by, self.manager)
        self.assertEqual(po.total_amount, Decimal("405.00"))  # 27 * 15.00

    # ── 4. Sensitive Action Confirmation Gating ─────────────────────────────

    def test_sensitive_action_requires_explicit_confirmation(self):
        """
        When the model invokes `create_draft_purchase_order` without prior confirmation,
        the agent must PAUSE, returning status PENDING_CONFIRMATION without executing the tool.
        """
        turn1_response = MockResponse([
            MockPart(
                text="I recommend creating a draft purchase order.",
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.low_stock_product.pk, "quantity": 10, "unit_cost": 15.00}],
                },
            )
        ])

        mock_model = MockGenerativeModel([turn1_response])
        service = AgentService(user=self.manager, model=mock_model)

        # auto_confirm is False (default)
        result = service.run("Prepare a draft purchase order for low stock items.")

        self.assertTrue(result.success)
        self.assertEqual(result.status, "PENDING_CONFIRMATION")
        self.assertIsNotNone(result.pending_action)
        self.assertEqual(result.pending_action["tool_name"], "create_draft_purchase_order")
        self.assertIn("supplier_id", result.pending_action["params"])
        # Crucial check: tool was NOT executed yet!
        self.assertEqual(len(result.tools_executed), 0)
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_sensitive_action_executes_when_pre_confirmed(self):
        """
        When confirmed_actions includes 'create_draft_purchase_order',
        execution proceeds safely.
        """
        turn1_response = MockResponse([
            MockPart(
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.low_stock_product.pk, "quantity": 5, "unit_cost": 15.00}],
                },
            )
        ])
        turn2_response = MockResponse([
            MockPart(text="Draft purchase order created successfully.")
        ])

        mock_model = MockGenerativeModel([turn1_response, turn2_response])
        service = AgentService(user=self.manager, model=mock_model)

        result = service.run(
            "Create confirmed draft PO.",
            confirmed_actions=["create_draft_purchase_order"],
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "SUCCESS")
        self.assertIn("create_draft_purchase_order", result.tools_executed)
        self.assertEqual(PurchaseOrder.objects.count(), 1)

    # ── 5. Permission Boundary Inheritance (RBAC) ───────────────────────────

    def test_standard_user_blocked_from_draft_po_by_rbac(self):
        """
        If a Standard User issues a goal and the model attempts `create_draft_purchase_order`,
        the backend tool's RBAC rejects it with PERMISSION_DENIED.
        The agent handles this failure gracefully and reports it.
        """
        turn1_response = MockResponse([
            MockPart(
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.low_stock_product.pk, "quantity": 5, "unit_cost": 15.00}],
                },
            )
        ])
        turn2_response = MockResponse([
            MockPart(text="I cannot create the purchase order because you do not have Manager privileges.")
        ])

        mock_model = MockGenerativeModel([turn1_response, turn2_response])
        service = AgentService(user=self.standard, model=mock_model)

        result = service.run("Create draft purchase order", auto_confirm=True)

        self.assertTrue(result.success)
        self.assertEqual(len(result.steps), 1)
        # Step failed with PERMISSION_DENIED
        self.assertEqual(result.steps[0]["status"], "FAILURE")
        self.assertEqual(result.steps[0]["result"]["error"]["code"], "PERMISSION_DENIED")
        # No PO was created in database
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    # ── 6. Invalid Tool Parameters Handling ─────────────────────────────────

    def test_invalid_parameters_handled_gracefully(self):
        """
        If the model generates invalid arguments (e.g. negative quantity),
        the parameter schema catches it and returns INVALID_PARAMS without crashing.
        """
        turn1_response = MockResponse([
            MockPart(
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.low_stock_product.pk, "quantity": -10, "unit_cost": 15.00}],
                },
            )
        ])
        turn2_response = MockResponse([
            MockPart(text="The quantity cannot be negative.")
        ])

        mock_model = MockGenerativeModel([turn1_response, turn2_response])
        service = AgentService(user=self.manager, model=mock_model)

        result = service.run("Create invalid PO", auto_confirm=True)

        self.assertTrue(result.success)
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(result.steps[0]["status"], "FAILURE")
        self.assertEqual(result.steps[0]["result"]["error"]["code"], "INVALID_PARAMS")

    # ── 7. Unknown Tool Name Rejection ──────────────────────────────────────

    def test_unregistered_tool_name_rejected_by_whitelist(self):
        """
        If the model tries to invoke an unregistered tool (e.g. 'run_custom_sql'),
        it is intercepted and rejected with UNKNOWN_TOOL.
        """
        turn1_response = MockResponse([
            MockPart(
                function_name="run_arbitrary_python",
                function_args={"code": "import os; os.system('dir')"},
            )
        ])
        turn2_response = MockResponse([
            MockPart(text="Arbitrary code execution is not permitted.")
        ])

        mock_model = MockGenerativeModel([turn1_response, turn2_response])
        service = AgentService(user=self.admin, model=mock_model)

        result = service.run("Run command", auto_confirm=True)

        self.assertTrue(result.success)
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(result.steps[0]["result"]["error"]["code"], "UNKNOWN_TOOL")

    # ── 8. Web API Endpoint Integration ─────────────────────────────────────

    def test_agent_api_endpoint_authenticated(self):
        """Tests the POST /ai/api/run/ endpoint with an authenticated manager session."""
        self.client.force_login(self.manager)

        # Post goal to API
        response = self.client.post(
            "/ai/api/run/",
            data='{"goal": "Check summary"}',
            content_type="application/json",
        )
        # Endpoint responds with 200 or 400 (if API key not configured in test environment)
        self.assertIn(response.status_code, [200, 400])

    def test_agent_api_endpoint_requires_login(self):
        """Unauthenticated POST to API endpoint must redirect to login."""
        response = self.client.post(
            "/ai/api/run/",
            data='{"goal": "Check summary"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login/", response.url)
