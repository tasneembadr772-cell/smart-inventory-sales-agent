# End-to-End User Journey Specifications
## Small Business Inventory & Sales Management System (NexusERP)

---

## Overview

This document specifies the six authoritative operational journeys implemented in NexusERP. Each journey details the interaction sequence, backend validation logic, security checks, and database mutations.

---

## Journey 1 — User Registration, Authentication & Role Isolation

### Summary
A new user registers, is deterministically assigned the non-privileged `STANDARD` role, authenticates using salted password verification, and accesses the role-aware dashboard.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Browser as Web Browser
    participant AuthView as apps/authentication/views
    participant UserForm as UserRegistrationForm
    participant DB as PostgreSQL (User Table)

    User->>Browser: Enters Username, Email, Password
    Browser->>AuthView: POST /auth/register/ (with CSRF token)
    AuthView->>UserForm: Bind POST data
    UserForm->>UserForm: Validate email uniqueness, password strength
    UserForm->>DB: INSERT User (role='STANDARD', is_staff=False)
    Note over UserForm,DB: Role assignment is hardcoded on server; user cannot self-promote.
    DB-->>AuthView: User record persisted
    AuthView->>AuthView: auth_login(request, user) [Issue HTTP-only Session Cookie]
    AuthView-->>Browser: Redirect to /auth/dashboard/
    Browser->>AuthView: GET /auth/dashboard/ (Session Cookie)
    AuthView->>DB: Fetch user role & live inventory KPIs
    AuthView-->>Browser: Renders personalized dashboard with 'Standard User' capabilities
```

### Key Security Assertions
- `role`, `is_staff`, and `is_superuser` are strictly excluded from registration forms.
- If an unauthenticated user attempts to access `/domain/products/create/`, they are redirected to `/auth/login/?next=/domain/products/create/`.
- If an authenticated `STANDARD` user accesses `/domain/products/create/`, the server returns **HTTP 403 Forbidden**.

---

## Journey 2 — Product Catalog Lifecycle Management

### Summary
A Manager creates a new inventory SKU, associating it with a Category and Supplier, triggering validation and an initial inventory ledger movement.

```mermaid
sequenceDiagram
    autonumber
    actor Manager as Store Manager
    participant Browser as Web Browser
    participant ProdView as apps/domain_app/views
    participant Decorator as @manager_required
    participant ProdService as apps/domain_app/services
    participant DB as PostgreSQL (Product, InventoryTx)

    Manager->>Browser: Fills Product Form (SKU, Name, Price, Initial Stock, Reorder Level)
    Browser->>ProdView: POST /domain/products/create/
    ProdView->>Decorator: Inspect request.user.role
    Decorator-->>ProdView: Role == 'MANAGER' (Access Granted)
    ProdView->>ProdService: create_product(sku, name, price, stock_quantity, ...)
    Note over ProdService: Starts @transaction.atomic block
    ProdService->>ProdService: Normalize SKU to uppercase; validate price >= 0.00
    ProdService->>DB: INSERT INTO domain_app_product
    opt Initial stock_quantity > 0
        ProdService->>DB: INSERT INTO domain_app_inventorytransaction<br/>(type='ADD', qty=stock_quantity, ref='INITIAL-STOCK')
    end
    Note over ProdService: Atomic Transaction Commits
    ProdService-->>ProdView: Returns persisted Product instance
    ProdView-->>Browser: Flash success message & Redirect to /domain/products/{id}/
```

### Key Business Invariants
- SKU uniqueness is enforced globally. Duplicate SKUs trigger immediate form errors.
- Database check constraints reject negative values for `price`, `stock_quantity`, or `reorder_level`.

---

## Journey 3 — Point-of-Sale Transaction Execution

### Summary
A sales representative executes a point-of-sale customer order. The backend serializes the stock decrement using database row locks, evaluates financial subtotals, and creates an immutable inventory audit record.

```mermaid
sequenceDiagram
    autonumber
    actor Cashier as Sales Staff / Cashier
    participant Browser as Interactive POS UI
    participant SaleView as apps/domain_app/views
    participant SaleService as apps/domain_app/services
    participant DB as PostgreSQL (Sale, Product, InventoryTx)

    Cashier->>Browser: Selects Customer Name & Items [Product A x 2, Product B x 1]
    Browser->>SaleView: POST /domain/sales/create/ (Payload with product IDs & quantities)
    SaleView->>SaleService: create_sale(customer_name, items_data, user=request.user)
    Note over SaleService: Starts @transaction.atomic block
    SaleService->>DB: Product.objects.select_for_update().filter(pk__in=[A, B])
    Note over SaleService,DB: Acquires exclusive row-level locks on Product rows
    SaleService->>SaleService: Verify product.stock_quantity >= requested_quantity
    alt Insufficient Stock Available
        SaleService-->>SaleView: Raises InsufficientStockError
        Note over SaleService: Transaction Rolls Back Completely
        SaleView-->>Browser: Renders error: "Insufficient stock for Product A"
    else Stock Validation Passes
        SaleService->>SaleService: Compute line subtotals & aggregate total_amount
        SaleService->>DB: INSERT INTO domain_app_sale (order_identifier, total_amount, ...)
        SaleService->>DB: INSERT INTO domain_app_saleitem (for each item)
        SaleService->>DB: UPDATE domain_app_product SET stock_quantity = stock_quantity - qty
        SaleService->>DB: INSERT INTO domain_app_inventorytransaction<br/>(type='REMOVE', ref=order_identifier)
        Note over SaleService: Transaction Commits Successfully
        SaleService-->>SaleView: Returns persisted Sale instance
        SaleView-->>Browser: Redirect to /domain/sales/{id}/ (Render Receipt)
    end
```

### Key Business Invariants
- Zero negative stock is strictly guaranteed via `select_for_update()` serialization and check constraints.
- Selling prices and computed subtotals are frozen in `SaleItem` to preserve historical integrity.

---

## Journey 4 — Purchase Order Procurement & Receiving Lifecycle

### Summary
A Manager manages replenishment stock from an initial Draft Purchase Order through to Receiving, which atomically increments physical inventory.

```mermaid
stateDiagram-v2
    [*] --> DRAFT : Manager creates PO (services.create_purchase_order)
    DRAFT --> PENDING : Submit for vendor acknowledgment
    DRAFT --> CANCELLED : Manager cancels order
    
    PENDING --> APPROVED : Management authorization granted
    PENDING --> CANCELLED : Order rejected or vendor unavailable
    
    APPROVED --> RECEIVED : Shipment arrives at warehouse (Receiving execution)
    APPROVED --> CANCELLED : Order cancelled prior to dispatch
    
    RECEIVED --> [*] : TERMINAL STATE (Inventory stock incremented)
    CANCELLED --> [*] : TERMINAL STATE (No stock mutation)

    note right of RECEIVED
        When status changes to RECEIVED:
        1. Row locks acquired on PO and target Products
        2. product.stock_quantity += item.quantity
        3. InventoryTransaction('ADD', ref=po.order_number) created
        4. PurchaseOrder marked RECEIVED
    end note
```

### Detailed Sequence for Receiving:
1. **Manager Action:** Clicks "Receive Order" on an `APPROVED` purchase order.
2. **Permission Check:** `@manager_required` confirms elevated role.
3. **Status Validation:** Engine asserts current status is `APPROVED` (orders cannot jump from `DRAFT` directly to `RECEIVED`).
4. **Supplier Active Check:** Inactive suppliers cannot receive status advancements.
5. **Atomic Stock Increment:** Each line item locks the corresponding `Product` row, increments `stock_quantity`, and generates an `InventoryTransaction` of type `ADD`.

---

## Journey 5 — Autonomous AI Replenishment Workflow

### Summary
A Manager instructs the AI Assistant to identify inventory shortages and draft purchase orders. The AI orchestrates allowlisted tools, reasons over structured deficits, pauses for human confirmation, and records an auditable execution trace.

```mermaid
sequenceDiagram
    autonumber
    actor Manager as Store Manager
    participant ChatUI as Chatbot UI (ai_agent/chat)
    participant Engine as AgentService (services.py)
    participant Gemini as Google Gemini 1.5 Flash
    participant Registry as Tool Registry (_TOOL_REGISTRY)
    participant Domain as domain_app (Selectors & Services)
    participant Audit as apps/ai_agent/models (AgentAuditLog)

    Manager->>ChatUI: "Check low stock items and prepare draft POs."
    ChatUI->>Engine: POST /ai/api/run/ {goal: "..."}
    Engine->>Gemini: Prompt + 3 Declared Tools (check_low_stock, create_draft_po, get_summary)
    Gemini-->>Engine: function_call: check_low_stock_products(limit=50)
    Engine->>Registry: execute_tool('check_low_stock_products', user=Manager)
    Registry->>Domain: selectors.get_low_stock_report()
    Domain-->>Registry: Returns 4 deficit items grouped by Supplier
    Registry->>Audit: INSERT AgentAuditLog(tool='check_low_stock', status='SUCCESS')
    Registry-->>Engine: Structured JSON ToolResult
    Engine->>Gemini: Feed ToolResult back to Gemini
    Gemini-->>Engine: function_call: create_draft_purchase_order(supplier_id=1, items=[...])
    
    Note over Engine: Sensitive Tool Check: create_draft_purchase_order requires HITL confirmation
    Engine-->>ChatUI: Return status='PENDING_CONFIRMATION'<br/>"I prepared a draft PO for Supplier #1 (Total: $450.00). Please confirm to proceed."
    
    Manager->>ChatUI: Clicks "Confirm & Create PO"
    ChatUI->>Engine: POST /ai/api/run/ {confirmed_actions: ['create_draft_purchase_order']}
    Engine->>Registry: execute_tool('create_draft_purchase_order', params={...})
    Registry->>Domain: services.create_purchase_order(status='DRAFT')
    Domain-->>Registry: Returns PurchaseOrder(order_number='PO-20260921-A891', total=450.00)
    Registry->>Audit: INSERT AgentAuditLog(tool='create_draft_po', status='SUCCESS')
    Registry-->>Engine: ToolResult with verified order_number
    Engine->>Gemini: Feed ToolResult to Gemini
    Gemini-->>Engine: Structured final response with order number
    Engine-->>ChatUI: Displays confirmation card with link to /domain/purchase-orders/{id}/
```

### Critical Architectural Defenses Demonstrated:
- **No Direct DB Access:** Gemini never touches the database; all actions run through `domain_app` services.
- **Human-in-the-Loop (HITL):** Financial mutations pause until explicit user confirmation is submitted.
- **Anti-Hallucination:** The agent only confirms creation if the backend service returns a real `order_number`.

---

## Journey 6 — Unauthorized AI Mutation Attempt

### Summary
A standard cashier attempts to trigger an elevated mutation via the AI Chatbot. The backend security gateway intercepts the request, rejects execution, writes an audit record, and returns a safe error without touching the database.

```mermaid
sequenceDiagram
    autonumber
    actor Attacker as Standard User (Cashier)
    participant ChatUI as Chatbot UI
    participant Engine as AgentService
    participant Gemini as Google Gemini
    participant Registry as Tool Registry
    participant Tools as tools.py (can_user_execute_tool)
    participant Audit as AgentAuditLog

    Attacker->>ChatUI: "Create a draft purchase order for Supplier 2 immediately."
    ChatUI->>Engine: POST /ai/api/run/ (Session user: role='STANDARD')
    Engine->>Gemini: Dispatches goal with tool signatures
    Gemini-->>Engine: function_call: create_draft_purchase_order(supplier_id=2, ...)
    Engine->>Tools: can_user_execute_tool(request.user, 'create_draft_purchase_order')
    Note over Tools: Evaluates user.has_role('ADMIN', 'MANAGER') ──► FALSE
    Tools-->>Engine: Allowed = False, Reason: "Permission denied: requires Manager or Admin"
    Engine->>Audit: INSERT AgentAuditLog(user=Attacker, tool='create_draft_po', status='DENIED')
    Note over Engine: Execution is blocked. Database is NOT touched.
    Engine-->>ChatUI: Return status='ERROR'<br/>"Permission denied: Standard users cannot create purchase orders."
```

### Key Security Assertions
- The LLM cannot grant permissions or bypass RBAC rules.
- `AgentAuditLog` records every unauthorized attempt with the offending user's identity and parameters for security auditing.
