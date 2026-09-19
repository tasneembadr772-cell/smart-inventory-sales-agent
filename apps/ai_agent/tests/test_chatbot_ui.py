"""
Automated Test Suite for the Embedded Context-Aware AI Chatbot UI & APIs.

Tests:
1. Authentication protection (unauthenticated access redirects to login).
2. Live Application Context API (/ai/api/context/).
3. Conversational Chat API (/ai/api/chat/) with real Agentic backend dispatch.
4. Multi-turn conversation memory and context handling.
5. Sensitive action confirmation workflow.
6. Error handling for malformed JSON, empty inputs, and tool failures.
7. Zero leakage of backend secrets, database credentials, or server configuration.
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


class ChatbotUiApiTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Users
        cls.manager = User.objects.create_user(
            username="chat_manager",
            email="manager@chat.test",
            password="testpass123",
            role=User.Role.MANAGER,
        )
        cls.standard = User.objects.create_user(
            username="chat_standard",
            email="standard@chat.test",
            password="testpass123",
            role=User.Role.STANDARD,
        )

        # Domain Data
        cls.category = Category.objects.create(name="Hardware")
        cls.supplier = Supplier.objects.create(
            name="Apex Fasteners",
            email="sales@apexfasteners.com",
            phone="555-9876",
            is_active=True,
        )
        cls.product_low = Product.objects.create(
            name="M8 Hex Bolt",
            sku="BLT-M8",
            category=cls.category,
            supplier=cls.supplier,
            price=Decimal("1.25"),
            stock_quantity=4,
            reorder_level=20,
            target_stock_level=50,
            is_active=True,
        )
        cls.product_ok = Product.objects.create(
            name="M12 Hex Nut",
            sku="NUT-M12",
            category=cls.category,
            supplier=cls.supplier,
            price=Decimal("0.75"),
            stock_quantity=100,
            reorder_level=20,
            is_active=True,
        )

    def setUp(self):
        self.client = Client()

    # ── 1. Authentication Gate Tests ────────────────────────────────────────

    def test_unauthenticated_chat_api_redirects_to_login(self):
        """Unauthenticated POST to /ai/api/chat/ must be rejected with redirect."""
        response = self.client.post(
            "/ai/api/chat/",
            data=json.dumps({"message": "Which products are low in stock?"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login/", response.url)

    def test_unauthenticated_context_api_redirects_to_login(self):
        """Unauthenticated GET to /ai/api/context/ must be rejected with redirect."""
        response = self.client.get("/ai/api/context/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login/", response.url)

    def test_unauthenticated_chat_page_redirects_to_login(self):
        """Unauthenticated GET to /ai/ must redirect to login."""
        response = self.client.get("/ai/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login/", response.url)

    # ── 2. Live Application Context API Tests ───────────────────────────────

    def test_authenticated_context_api_returns_safe_data(self):
        """
        Tests GET /ai/api/context/ returns valid context for authenticated user
        without leaking passwords, DB credentials, or SECRET_KEY.
        """
        self.client.force_login(self.manager)
        response = self.client.get("/ai/api/context/")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data["success"])
        self.assertIn("user", data)
        self.assertEqual(data["user"]["username"], "chat_manager")
        self.assertEqual(data["user"]["role"], "Manager")
        self.assertTrue(data["user"]["is_privileged"])

        self.assertIn("inventory", data)
        inv = data["inventory"]
        self.assertEqual(inv["total_products"], 2)
        self.assertEqual(inv["low_stock_count"], 1)

        self.assertIn("suggestions", data)
        self.assertIsInstance(data["suggestions"], list)
        self.assertGreater(len(data["suggestions"]), 0)

        # Zero exposure verification: ensure no sensitive keys exist
        raw_json = response.content.decode("utf-8")
        self.assertNotIn("password", raw_json)
        self.assertNotIn("SECRET_KEY", raw_json)
        self.assertNotIn("postgres", raw_json)
        self.assertNotIn("GEMINI_API_KEY", raw_json)

    # ── 3. Chat API — Message Sending & Real Agent Execution ────────────────

    def test_chat_api_successful_interaction(self):
        """
        Tests asynchronous POST /ai/api/chat/ invoking a tool and returning
        structured agent actions and response.
        """
        self.client.force_login(self.manager)

        turn1 = MockResponse([
            MockPart(
                text="Checking products below reorder level.",
                function_name="check_low_stock_products",
                function_args={"include_out_of_stock": True},
            )
        ])
        turn2 = MockResponse([
            MockPart(text="1 product is currently below its reorder level: M8 Hex Bolt (4 on hand, reorder level 20).")
        ])

        mock_model = MockGenerativeModel([turn1, turn2])

        # Mock _custom_model on AgentService
        original_init = AgentService.__init__

        def mock_init(service_self, user, **kwargs):
            original_init(service_self, user, **kwargs)
            service_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            payload = {
                "message": "Which products are low in stock?",
                "history": [],
            }
            response = self.client.post(
                "/ai/api/chat/",
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertTrue(data["success"])
            self.assertEqual(data["status"], "SUCCESS")
            self.assertIn("1 product is currently below its reorder level", data["reply"])
            self.assertEqual(data["tools_executed"], ["check_low_stock_products"])
            self.assertEqual(len(data["steps"]), 1)
            self.assertEqual(data["steps"][0]["tool"], "check_low_stock_products")
            self.assertEqual(data["steps"][0]["status"], "SUCCESS")
            self.assertIn("context", data)
            self.assertEqual(data["context"]["username"], "chat_manager")
        finally:
            AgentService.__init__ = original_init

    # ── 4. Chat API — Multi-Turn Conversational Memory & Context Handling ───

    def test_chat_api_multi_turn_conversational_context(self):
        """
        Simulates the user request example:
        Turn 1: User asked for low stock -> Agent replied 5 products low.
        Turn 2: User says 'Prepare draft purchase orders for them.'
        Verifies that conversation history is preserved and passed into the Agent loop.
        """
        self.client.force_login(self.manager)

        turn1 = MockResponse([
            MockPart(
                text="Identified M8 Hex Bolt deficit. Creating draft purchase order.",
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.product_low.pk, "quantity": 46, "unit_cost": 1.25}],
                },
            )
        ])
        turn2 = MockResponse([
            MockPart(text="1 draft purchase order was prepared for Apex Fasteners.")
        ])

        mock_model = MockGenerativeModel([turn1, turn2])

        original_init = AgentService.__init__

        def mock_init(service_self, user, **kwargs):
            original_init(service_self, user, **kwargs)
            service_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            payload = {
                "message": "Prepare draft purchase orders for them.",
                "history": [
                    {"role": "user", "content": "Which products are low in stock?"},
                    {"role": "assistant", "content": "1 product is currently below its reorder level."},
                ],
                "auto_confirm": True,
            }
            response = self.client.post(
                "/ai/api/chat/",
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertTrue(data["success"])
            self.assertEqual(data["status"], "SUCCESS")
            self.assertIn("1 draft purchase order was prepared", data["reply"])
            self.assertIn("create_draft_purchase_order", data["tools_executed"])

            # Verify that mock_model received the conversation history in its prompt
            sent_prompt = mock_model.chat.call_history[0]
            self.assertIn("[Recent Conversation History]", sent_prompt)
            self.assertIn("Which products are low in stock?", sent_prompt)
            self.assertIn("Prepare draft purchase orders for them.", sent_prompt)
        finally:
            AgentService.__init__ = original_init

    # ── 5. Sensitive Action Confirmation Workflow ───────────────────────────

    def test_chat_api_sensitive_action_returns_pending_confirmation(self):
        """
        When the model proposes creating a draft PO without pre-approval,
        the API returns PENDING_CONFIRMATION and pending_action metadata.
        """
        self.client.force_login(self.manager)

        turn1 = MockResponse([
            MockPart(
                function_name="create_draft_purchase_order",
                function_args={
                    "supplier_id": self.supplier.pk,
                    "items": [{"product_id": self.product_low.pk, "quantity": 10, "unit_cost": 1.25}],
                },
            )
        ])

        mock_model = MockGenerativeModel([turn1])

        original_init = AgentService.__init__

        def mock_init(service_self, user, **kwargs):
            original_init(service_self, user, **kwargs)
            service_self._custom_model = mock_model

        AgentService.__init__ = mock_init
        try:
            payload = {
                "message": "Restock M8 bolts",
                "auto_confirm": False,
            }
            response = self.client.post(
                "/ai/api/chat/",
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertEqual(data["status"], "PENDING_CONFIRMATION")
            self.assertIsNotNone(data["pending_action"])
            self.assertEqual(data["pending_action"]["tool_name"], "create_draft_purchase_order")
            # PO not created yet
            self.assertEqual(PurchaseOrder.objects.count(), 0)

            # Now send confirmation
            turn2_confirm = MockResponse([
                MockPart(
                    function_name="create_draft_purchase_order",
                    function_args={
                        "supplier_id": self.supplier.pk,
                        "items": [{"product_id": self.product_low.pk, "quantity": 10, "unit_cost": 1.25}],
                    },
                )
            ])
            turn3_done = MockResponse([
                MockPart(text="Confirmed. Draft purchase order created.")
            ])

            mock_model_confirm = MockGenerativeModel([turn2_confirm, turn3_done])

            def mock_init_confirm(service_self, user, **kwargs):
                original_init(service_self, user, **kwargs)
                service_self._custom_model = mock_model_confirm

            AgentService.__init__ = mock_init_confirm

            confirm_payload = {
                "message": "Confirm draft PO",
                "confirmed_actions": ["create_draft_purchase_order"],
            }
            confirm_response = self.client.post(
                "/ai/api/chat/",
                data=json.dumps(confirm_payload),
                content_type="application/json",
            )

            self.assertEqual(confirm_response.status_code, 200)
            confirm_data = confirm_response.json()
            self.assertEqual(confirm_data["status"], "SUCCESS")
            self.assertEqual(PurchaseOrder.objects.count(), 1)
        finally:
            AgentService.__init__ = original_init

    # ── 6. Error Handling & Validation Tests ─────────────────────────────────

    def test_chat_api_malformed_json_returns_400(self):
        """Malformed JSON payloads return clean 400 Bad Request."""
        self.client.force_login(self.manager)
        response = self.client.post(
            "/ai/api/chat/",
            data="Not valid json {",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("Malformed request", data["error"])

    def test_chat_api_empty_message_returns_400(self):
        """Empty message returns clean 400 Bad Request."""
        self.client.force_login(self.manager)
        response = self.client.post(
            "/ai/api/chat/",
            data=json.dumps({"message": "   "}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("required", data["error"])

    def test_chat_api_get_method_not_allowed(self):
        """GET request to /ai/api/chat/ returns 405 Method Not Allowed."""
        self.client.force_login(self.manager)
        response = self.client.get("/ai/api/chat/")
        self.assertEqual(response.status_code, 405)
