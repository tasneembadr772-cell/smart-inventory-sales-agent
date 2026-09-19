"""
End-to-End Integration Test Suite for Agentic AI & Inventory & Sales Management System.

Tests the complete 14-step workflow and verifies:
1. Standard User permissions (read allowed, write blocked by RBAC).
2. Manager permissions (read + write allowed).
3. Admin permissions (full access).
4. Invalid product IDs (handled safely with INVALID_PRODUCT).
5. Invalid quantities (handled safely with INVALID_PARAMS).
6. Empty low-stock results (handled cleanly without errors).
7. Tool failure handling (graceful reporting to agent).
8. AI-generated invalid arguments (schema interception).
9. Sensitive action confirmation gating (pause -> approve -> execute).
10. CSRF protection (rejected when token missing).
11. Authentication failure (unauthenticated access redirected to login).
12. Full end-to-end multi-step workflow.
"""

import json
from decimal import Decimal
from unittest.mock import MagicMock

from django.test import TestCase, Client
from django.urls import reverse

from apps.authentication.models import User
from apps.domain_app.models import Category, Supplier, Product, PurchaseOrder
from apps.ai_agent.tests.test_agent_service import MockResponse, MockPart, MockGenerativeModel
from apps.ai_agent.services import AgentService


class AgenticSystemIntegrationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        # 1. Users across all roles
        cls.admin_user = User.objects.create_user(
            username="admin_integ",
            email="admin@integ.test",
            password="Password123!",
            role=User.Role.ADMIN,
        )
        cls.manager_user = User.objects.create_user(
            username="manager_integ",
            email="manager@integ.test",
            password="Password123!",
            role=User.Role.MANAGER,
        )
        cls.standard_user = User.objects.create_user(
            username="standard_integ",
            email="standard@integ.test",
            password="Password123!",
            role=User.Role.STANDARD,
        )

        # 2. Master Domain Fixtures
        cls.category = Category.objects.create(
            name="Industrial Fasteners",
            description="High tensile fasteners and fixings",
        )
        cls.supplier = Supplier.objects.create(
            name="Titanium Hardware Corp",
            email="orders@titaniumhardware.com",
            phone="555-8888",
            is_active=True,
        )
        cls.inactive_supplier = Supplier.objects.create(
            name="Obsolete Parts Ltd",
            email="old@obsolete.test",
            phone="555-0000",
            is_active=False,
        )

        # 3. Product with low stock (Deficit item)
        cls.low_stock_product = Product.objects.create(
            name="Titanium Bolt M10",
            sku="TB-M10",
            category=cls.category,
            supplier=cls.supplier,
            price=Decimal("25.00"),
            stock_quantity=2,
            reorder_level=15,
            target_stock_level=40,
            is_active=True,
        )

        # 4. Product with adequate stock
        cls.healthy_product = Product.objects.create(
            name="Titanium Nut M10",
            sku="TN-M10",
            category=cls.category,
            supplier=cls.supplier,
            price=Decimal("12.00"),
            stock_quantity=80,
            reorder_level=20,
            target_stock_level=50,
            is_active=True,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # WORKFLOW VERIFICATION: Full 14-Step End-to-End Workflow
    # ──────────────────────────────────────────────────────────────────────────

    def test_complete_14_step_end_to_end_workflow(self):
        """
        Validates the complete 14-step integration workflow:
        1. Authenticated manager logs in.
        2. Manager opens dashboard.
        3. Manager asks: 'Check low-stock products and prepare draft purchase orders.'
        4. Agent receives authenticated user context.
        5. Agent selects check_low_stock_products.
        6. Backend validates permissions and parameters.
        7. Tool queries PostgreSQL through Django ORM.
        8. Agent analyzes returned low-stock products.
        9. Agent selects create_draft_purchase_order with supplier_id and items.
        10. Backend validates the action.
        11. Draft Purchase Order is created.
        12. Agent receives result.
        13. Agent returns structured response.
        14. UI/API displays result.
        """
        # Step 1: User logs in
        login_success = self.client.login(username="manager_integ", password="Password123!")
        self.assertTrue(login_success, "Manager login failed")

        # Step 2: User opens dashboard
        dash_response = self.client.get(reverse("authentication:dashboard"))
        self.assertEqual(dash_response.status_code, 200)
        self.assertContains(dash_response, "Welcome, manager_integ")
        self.assertContains(dash_response, "nexus-chat-launcher")

        # Configure Multi-Step Agent reasoning
        turn1_low_stock_query = MockResponse([
            MockPart(
                text="Inspecting inventory for low stock items.",
                function_name="check_low_stock_products",
                function_args={"limit": 10, "include_out_of_stock": True},
            )
        ])
        turn2_draft_po_create = MockResponse([
            MockPart(
                text="Titanium Bolt M10 is low (2 in stock, reorder level 15). Preparing draft PO for Titanium Hardware Corp.",
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [
                        {
                            "product_id": self.low_stock_product.pk,
                            "quantity": 38,
                            "unit_cost": 25.00,
                        }
                    ],
                    "notes": "Automated replenishment draft generated for Titanium Bolt M10",
                },
            )
        ])
        turn3_final_response = MockResponse([
            MockPart(
                text=(
                    "### Action:\nDraft Purchase Order Creation\n\n"
                    "### Status:\nSUCCESS\n\n"
                    "### Affected Records:\nPO created for Titanium Hardware Corp (38 units of TB-M10)\n\n"
                    "### Summary:\nSuccessfully created draft purchase order for Titanium Hardware Corp with total $950.00.\n\n"
                    "### Errors / Notes:\nNone"
                )
            )
        ])

        mock_model = MockGenerativeModel([turn1_low_stock_query, turn2_draft_po_create, turn3_final_response])

        orig_init = AgentService.__init__

        def mock_init(svc_self, user, **kwargs):
            orig_init(svc_self, user, **kwargs)
            svc_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            # Step 3 & 4: User asks Agent via Chat API
            payload = {
                "message": "Check low-stock products and prepare draft purchase orders.",
                "history": [],
                "auto_confirm": True,
            }
            chat_response = self.client.post(
                reverse("ai_agent:api_chat"),
                data=json.dumps(payload),
                content_type="application/json",
            )

            # Step 14: Verify UI/API receives complete structured response
            self.assertEqual(chat_response.status_code, 200)
            data = chat_response.json()

            self.assertTrue(data["success"])
            self.assertEqual(data["status"], "SUCCESS")

            # Verify steps executed
            self.assertEqual(len(data["steps"]), 2)

            # Step 5, 6, 7: check_low_stock_products tool validation & execution
            step1 = data["steps"][0]
            self.assertEqual(step1["tool"], "check_low_stock_products")
            self.assertEqual(step1["status"], "SUCCESS")
            self.assertEqual(step1["result"]["data"]["count"], 1)
            self.assertEqual(step1["result"]["data"]["items"][0]["sku"], "TB-M10")

            # Step 9, 10, 11: create_draft_purchase_order tool execution
            step2 = data["steps"][1]
            self.assertEqual(step2["tool"], "create_draft_purchase_order")
            self.assertEqual(step2["status"], "SUCCESS")
            po_id = step2["result"]["data"]["purchase_order_id"]

            # Step 11: Verify PO exists in DB with status DRAFT
            po = PurchaseOrder.objects.get(pk=po_id)
            self.assertEqual(po.status, PurchaseOrder.Status.DRAFT)
            self.assertEqual(po.supplier, self.supplier)
            self.assertEqual(po.created_by, self.manager_user)
            self.assertEqual(po.total_amount, Decimal("950.00"))  # 38 * 25.00

            # Step 12 & 13: Final structured response received
            self.assertIn("Action:", data["reply"])
            self.assertIn("Status:", data["reply"])
            self.assertIn("SUCCESS", data["reply"])
            self.assertIn("Titanium Hardware Corp", data["reply"])
        finally:
            AgentService.__init__ = orig_init

    # ──────────────────────────────────────────────────────────────────────────
    # PERMISSION BOUNDARY TESTS: Standard User vs Manager vs Admin
    # ──────────────────────────────────────────────────────────────────────────

    def test_standard_user_permissions(self):
        """
        Standard users have read permissions but must be blocked by RBAC
        if an action attempts to create a purchase order.
        """
        self.client.force_login(self.standard_user)

        turn1 = MockResponse([
            MockPart(
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.low_stock_product.pk, "quantity": 10, "unit_cost": 25.00}],
                },
            )
        ])
        turn2 = MockResponse([
            MockPart(text="Permission denied: You need Manager or Admin privileges to create purchase orders.")
        ])

        mock_model = MockGenerativeModel([turn1, turn2])

        orig_init = AgentService.__init__

        def mock_init(svc_self, user, **kwargs):
            orig_init(svc_self, user, **kwargs)
            svc_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            response = self.client.post(
                reverse("ai_agent:api_chat"),
                data=json.dumps({"message": "Create purchase order", "auto_confirm": True}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            # Tool must have failed with PERMISSION_DENIED
            self.assertEqual(data["steps"][0]["status"], "FAILURE")
            self.assertEqual(data["steps"][0]["result"]["error"]["code"], "PERMISSION_DENIED")
            self.assertEqual(PurchaseOrder.objects.count(), 0)
        finally:
            AgentService.__init__ = orig_init

    def test_manager_user_permissions(self):
        """Managers are authorized to create draft purchase orders."""
        self.client.force_login(self.manager_user)

        turn1 = MockResponse([
            MockPart(
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.low_stock_product.pk, "quantity": 5, "unit_cost": 25.00}],
                },
            )
        ])
        turn2 = MockResponse([MockPart(text="Draft PO created.")])

        mock_model = MockGenerativeModel([turn1, turn2])

        orig_init = AgentService.__init__

        def mock_init(svc_self, user, **kwargs):
            orig_init(svc_self, user, **kwargs)
            svc_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            response = self.client.post(
                reverse("ai_agent:api_chat"),
                data=json.dumps({"message": "Create PO", "auto_confirm": True}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["steps"][0]["status"], "SUCCESS")
            self.assertEqual(PurchaseOrder.objects.count(), 1)
        finally:
            AgentService.__init__ = orig_init

    def test_admin_user_permissions(self):
        """Admins have full operational and administrative permissions."""
        self.client.force_login(self.admin_user)

        turn1 = MockResponse([
            MockPart(
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.low_stock_product.pk, "quantity": 10, "unit_cost": 25.00}],
                },
            )
        ])
        turn2 = MockResponse([MockPart(text="Admin draft PO created.")])

        mock_model = MockGenerativeModel([turn1, turn2])

        orig_init = AgentService.__init__

        def mock_init(svc_self, user, **kwargs):
            orig_init(svc_self, user, **kwargs)
            svc_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            response = self.client.post(
                reverse("ai_agent:api_chat"),
                data=json.dumps({"message": "Create Admin PO", "auto_confirm": True}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["steps"][0]["status"], "SUCCESS")
            self.assertEqual(PurchaseOrder.objects.count(), 1)
        finally:
            AgentService.__init__ = orig_init

    # ──────────────────────────────────────────────────────────────────────────
    # VALIDATION & ERROR HANDLING TESTS
    # ──────────────────────────────────────────────────────────────────────────

    def test_invalid_product_id_handled_gracefully(self):
        """AI passing non-existent product ID returns INVALID_PRODUCT error."""
        self.client.force_login(self.manager_user)

        turn1 = MockResponse([
            MockPart(
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": 999999, "quantity": 10, "unit_cost": 10.00}],
                },
            )
        ])
        turn2 = MockResponse([MockPart(text="Product ID 999999 does not exist.")])

        mock_model = MockGenerativeModel([turn1, turn2])

        orig_init = AgentService.__init__

        def mock_init(svc_self, user, **kwargs):
            orig_init(svc_self, user, **kwargs)
            svc_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            response = self.client.post(
                reverse("ai_agent:api_chat"),
                data=json.dumps({"message": "Reorder 999999", "auto_confirm": True}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["steps"][0]["status"], "FAILURE")
            self.assertEqual(data["steps"][0]["result"]["error"]["code"], "INVALID_PRODUCT")
        finally:
            AgentService.__init__ = orig_init

    def test_invalid_quantity_handled_gracefully(self):
        """AI passing zero or negative quantity is blocked by dataclass validation."""
        self.client.force_login(self.manager_user)

        turn1 = MockResponse([
            MockPart(
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.low_stock_product.pk, "quantity": 0, "unit_cost": 25.00}],
                },
            )
        ])
        turn2 = MockResponse([MockPart(text="Quantity must be greater than zero.")])

        mock_model = MockGenerativeModel([turn1, turn2])

        orig_init = AgentService.__init__

        def mock_init(svc_self, user, **kwargs):
            orig_init(svc_self, user, **kwargs)
            svc_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            response = self.client.post(
                reverse("ai_agent:api_chat"),
                data=json.dumps({"message": "Order 0 units", "auto_confirm": True}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["steps"][0]["status"], "FAILURE")
            self.assertEqual(data["steps"][0]["result"]["error"]["code"], "INVALID_PARAMS")
        finally:
            AgentService.__init__ = orig_init

    def test_empty_low_stock_results_handled_cleanly(self):
        """
        When all products are well-stocked, check_low_stock_products returns
        empty list and agent reports zero deficit items.
        """
        self.client.force_login(self.manager_user)

        # Set low stock product to healthy stock
        self.low_stock_product.stock_quantity = 100
        self.low_stock_product.save()

        turn1 = MockResponse([
            MockPart(
                function_name="check_low_stock_products",
                function_args={"limit": 50},
            )
        ])
        turn2 = MockResponse([
            MockPart(
                text=(
                    "### Action:\nLow Stock Audit\n\n"
                    "### Status:\nNO_ACTION_REQUIRED\n\n"
                    "### Affected Records:\nNone\n\n"
                    "### Summary:\nAll inventory items are currently above their reorder thresholds.\n\n"
                    "### Errors / Notes:\nNone"
                )
            )
        ])

        mock_model = MockGenerativeModel([turn1, turn2])

        orig_init = AgentService.__init__

        def mock_init(svc_self, user, **kwargs):
            orig_init(svc_self, user, **kwargs)
            svc_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            response = self.client.post(
                reverse("ai_agent:api_chat"),
                data=json.dumps({"message": "Which products are low in stock?"}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["steps"][0]["result"]["data"]["count"], 0)
            self.assertIn("NO_ACTION_REQUIRED", data["reply"])
        finally:
            # Restore stock
            self.low_stock_product.stock_quantity = 2
            self.low_stock_product.save()
            AgentService.__init__ = orig_init

    def test_ai_generated_invalid_arguments_safely_intercepted(self):
        """AI hallucinating unexpected or malformed arguments is caught by parameter schema."""
        self.client.force_login(self.manager_user)

        turn1 = MockResponse([
            MockPart(
                function_name="check_low_stock_products",
                function_args={"limit": "not-a-number", "hallucinated_flag": True},
            )
        ])
        turn2 = MockResponse([MockPart(text="Parameters were invalid.")])

        mock_model = MockGenerativeModel([turn1, turn2])

        orig_init = AgentService.__init__

        def mock_init(svc_self, user, **kwargs):
            orig_init(svc_self, user, **kwargs)
            svc_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            response = self.client.post(
                reverse("ai_agent:api_chat"),
                data=json.dumps({"message": "Check inventory with bad params"}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["steps"][0]["status"], "FAILURE")
            self.assertEqual(data["steps"][0]["result"]["error"]["code"], "INVALID_PARAMS")
        finally:
            AgentService.__init__ = orig_init

    # ──────────────────────────────────────────────────────────────────────────
    # SENSITIVE ACTION CONFIRMATION TESTS
    # ──────────────────────────────────────────────────────────────────────────

    def test_sensitive_action_confirmation_gating(self):
        """
        Verifies that create_draft_purchase_order halts on PENDING_CONFIRMATION,
        and proceeds to execute only after receiving confirmation.
        """
        self.client.force_login(self.manager_user)

        turn1 = MockResponse([
            MockPart(
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.low_stock_product.pk, "quantity": 20, "unit_cost": 25.00}],
                },
            )
        ])

        mock_model = MockGenerativeModel([turn1])

        orig_init = AgentService.__init__

        def mock_init(svc_self, user, **kwargs):
            orig_init(svc_self, user, **kwargs)
            svc_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            # 1. First request without confirmation
            response1 = self.client.post(
                reverse("ai_agent:api_chat"),
                data=json.dumps({"message": "Prepare PO for Titanium Bolts", "auto_confirm": False}),
                content_type="application/json",
            )
            self.assertEqual(response1.status_code, 200)
            data1 = response1.json()
            self.assertEqual(data1["status"], "PENDING_CONFIRMATION")
            self.assertIsNotNone(data1["pending_action"])
            self.assertEqual(data1["pending_action"]["tool_name"], "create_draft_purchase_order")
            self.assertEqual(PurchaseOrder.objects.count(), 0)

            # 2. Second request with confirmation
            turn2 = MockResponse([
                MockPart(
                    function_name="create_draft_purchase_order",
                    function_args={
                        "supplier_id": self.supplier.pk,
                        "items": [{"product_id": self.low_stock_product.pk, "quantity": 20, "unit_cost": 25.00}],
                    },
                )
            ])
            turn3 = MockResponse([MockPart(text="Confirmed order created.")])
            mock_model2 = MockGenerativeModel([turn2, turn3])

            def mock_init2(svc_self, user, **kwargs):
                orig_init(svc_self, user, **kwargs)
                svc_self._custom_model = mock_model2

            AgentService.__init__ = mock_init2

            response2 = self.client.post(
                reverse("ai_agent:api_chat"),
                data=json.dumps({
                    "message": "Confirm PO",
                    "confirmed_actions": ["create_draft_purchase_order"],
                }),
                content_type="application/json",
            )
            self.assertEqual(response2.status_code, 200)
            data2 = response2.json()
            self.assertEqual(data2["status"], "SUCCESS")
            self.assertEqual(PurchaseOrder.objects.count(), 1)
        finally:
            AgentService.__init__ = orig_init

    # ──────────────────────────────────────────────────────────────────────────
    # SECURITY & INTEGRITY TESTS: CSRF & Authentication
    # ──────────────────────────────────────────────────────────────────────────

    def test_csrf_protection_enforcement(self):
        """
        Enforces CSRF validation on /ai/api/chat/ when CSRF checks are enabled.
        Missing or invalid token results in 403 Forbidden.
        """
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.manager_user)

        # POST without CSRF header or token -> 403 Forbidden
        response = csrf_client.post(
            reverse("ai_agent:api_chat"),
            data=json.dumps({"message": "Hello"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_authentication_failure_redirects(self):
        """Unauthenticated requests cannot access the agent API."""
        anon_client = Client()
        response = anon_client.post(
            reverse("ai_agent:api_chat"),
            data=json.dumps({"message": "Hello"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login/", response.url)
