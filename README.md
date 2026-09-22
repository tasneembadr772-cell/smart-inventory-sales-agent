# 📦 Small Business Inventory & Sales Management System (NexusERP)

[![Python 3.12](https://img.shields.io/badge/Python-3.12+-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Django 5.1](https://img.shields.io/badge/Django-5.1-092E20.svg?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Tests Passing](https://img.shields.io/badge/Tests-272%20Passed-brightgreen.svg)](https://github.com/tasneembadr772-cell/smart-inventory-sales-agent)
[![AI Agent](https://img.shields.io/badge/AI%20Engine-Gemini%201.5%20Flash-orange.svg)](https://deepmind.google/technologies/gemini/)

NexusERP is a production-hardened web application featuring an **Autonomous Agentic AI Workflow** with safe backend tool-calling, built with Python, Django (MVT), and PostgreSQL. It delivers real-time inventory calibration, transactional point-of-sale processing, replenishment purchase order lifecycles, and role-governed AI assistance.

---

## 👥 Graduation Project Team (Group 2)

- **Tasneem Yasser Ibrahim Badr**
- **Ebrahim Ahmed Mahmoud Al Asrag**

---

## 📚 Complete Project Documentation Suite

For comprehensive academic evaluation, defense review, and system specifications, refer to the following authoritative documents:

| Specification Document | Focus Area & Description |
| :--- | :--- |
| 📄 [Official SRS Document](docs/SRS.md) | Full Software Requirements Specification (Functional, Non-Functional, RBAC Matrix, AI Governance, Data Architecture). |
| 📊 [Entity-Relationship Diagram (ERD)](docs/ERD.md) | Visual Mermaid ERD, detailed Data Dictionary, PK/FK relationships, check constraints, and composite indexes across all 10 models. |
| 🏛️ [System Architecture](docs/ARCHITECTURE.md) | MVT architectural separation, Selector/Service layers, ACID transaction boundaries, and the dual-track AI sandboxing boundary. |
| 🗺️ [User Journey Specifications](docs/USER_JOURNEYS.md) | Step-by-step visual workflows for Registration, Product CRUD, POS Sales, PO Lifecycle, AI Replenishment, and Unauthorized Mutation Denial. |
| 🤖 [AI Agent Design & Governance](docs/AI_AGENT_DESIGN.md) | Deep-dive specification of the 3 allowlisted tools, 7-step reasoning loop, prompt engineering, confirmation gate, and threat mitigations. |

---

## 🚀 Verified Tech Stack

- **Backend Framework:** Python 3.12+, Django 5.1+ (Model-View-Template Architecture)
- **Database:** PostgreSQL 18 (Third Normal Form Normalized Schema with SQLite fallback for isolated unit tests)
- **Frontend Layer:** Semantic HTML5, Custom Vanilla Modern CSS, Vanilla JavaScript (ES6+ Fetch API, CSRF-protected)
- **AI & LLM Integration:** Google Gemini 1.5 Flash (`gemini-1.5-flash` via `google.generativeai` function-calling SDK)
- **Version Control:** Git & GitHub (Feature branch workflow, Conventional Commits)

---

## 📂 Project Structure

```
smart-inventory-sales-agent/
├── apps/
│   ├── authentication/          # Custom User model, RBAC decorators, auth views, dashboard
│   ├── domain_app/              # Domain models (Product, Category, Supplier, Sale, PO, InventoryTx)
│   │   ├── selectors.py         # N+1 safe query selectors & database aggregations
│   │   ├── services.py          # Atomic mutations, stock row locking, PO receiving
│   │   ├── views.py             # Product, Supplier, Sales, and Purchase Order controllers
│   │   └── management/commands/ # Idempotent demo data seeding commands
│   ├── ai_agent/                # Sandboxed Agentic AI Engine
│   │   ├── tool_registry.py     # Central dispatch & tool whitelist verification
│   │   ├── agent_tools.py       # Callable tool implementations (check_low_stock, create_draft_po, get_summary)
│   │   ├── tools.py             # Function declarations, RBAC evaluations, parameter sanitization
│   │   ├── services.py          # Multi-step Agent reasoning-action loop with HITL confirmation
│   │   └── models.py            # AgentAuditLog persistence model
│   └── core/                    # Shared layouts, base templates, and static resources
├── config/                      # Django project settings and root URL routing
├── docs/                        # Graduation Project Deliverables (SRS, ERD, Architecture, Journeys, AI)
├── static/                      # CSS stylesheets, ES6 client scripts, brand imagery
├── templates/                   # Semantic HTML5 template hierarchy
└── manage.py                    # Django management runner
```

---

## ⚙️ Prerequisites

- **Python:** 3.12 or higher installed
- **Database:** PostgreSQL 15+ (PostgreSQL 18 recommended) or SQLite for development
- **AI API Key:** Active Google Gemini API Key (`GEMINI_API_KEY`)

---

## 🛠️ Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/tasneembadr772-cell/smart-inventory-sales-agent.git
cd smart-inventory-sales-agent
```

### 2. Set Up Virtual Environment
```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 🔐 Environment Variables

Create a `.env` file in the project root by copying `.env.example`:

```bash
cp .env.example .env
```

Configure your environment variables (*variable names only — never commit secrets to Git*):

| Variable Name | Default Value | Description |
| :--- | :--- | :--- |
| `SECRET_KEY` | `django-insecure-...` | Django cryptographic signing secret key. |
| `DEBUG` | `True` | Debug mode toggle (`True` for local development, `False` for production). |
| `ALLOWED_HOSTS`| `localhost,127.0.0.1`| Comma-separated list of permitted hostnames. |
| `DB_ENGINE` | `django.db.backends.postgresql` | Database backend (`postgresql` or `sqlite3`). |
| `DB_NAME` | `inventory_sales_db` | PostgreSQL database name (or `db.sqlite3` for SQLite). |
| `DB_USER` | `postgres` | PostgreSQL database user. |
| `DB_PASSWORD` | *(your local password)* | PostgreSQL database password. |
| `DB_HOST` | `localhost` | PostgreSQL host address. |
| `DB_PORT` | `5432` | PostgreSQL database port. |
| `GEMINI_API_KEY`| *(your Gemini key)* | Google Gemini API key for the AI Assistant. |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Gemini model variant. |

---

## 🗄️ Database Setup & Migrations

### Apply Migrations
```bash
python manage.py migrate
```

### Verify Migration Status
```bash
python manage.py makemigrations --dry-run
# Output: No changes detected
```

---

## 👥 Seed Demonstration Data

Populate clean, realistic, production-ready demonstration data for evaluation:
```bash
python manage.py seed_demo_data
```

> [!WARNING]
> **DEMO CREDENTIALS ONLY — CHANGE / REMOVE FOR REAL DEPLOYMENT**
> 
> | Role | Username | Password | Access Capabilities |
> | :--- | :--- | :--- | :--- |
> | **Admin / Superuser** | `admin` | `Admin@12345` | Full system administration, destructive deletions, user management. |
> | **Store Manager** | `manager` | `Manager@12345` | Product/Category/Supplier CRUD, Stock Adjustments, PO Lifecycle, AI PO Drafting. |
> | **Cashier / Standard**| `cashier` | `Cashier@12345` | Active catalog lookup, POS sales processing, read-only AI inventory queries. |

---

## 💻 Running the Application

Start the local Django development server:
```bash
python manage.py runserver
```
Visit `http://127.0.0.1:8000/` in your browser.

---

## 🧪 Testing & Verification

The project includes an extensive automated test suite covering models, services, selectors, views, RBAC permissions, and AI tool governance.

Execute all tests:
```bash
python manage.py test
```

### Verified Test Suite Results:
- **Total Tests:** **272**
- **Status:** **OK (100% Passing)**
- **Failures:** **0**
- **Errors:** **0**
- **Execution Time:** ~296s

---

## 🤖 Agentic AI Engine & Security Boundaries

NexusERP incorporates a sandboxed autonomous AI assistant accessible via `/ai/`:
- **Allowed Tools:** 
  1. `check_low_stock_products` (Read-only catalog shortage query)
  2. `create_draft_purchase_order` (Mutating; restricted to Manager/Admin; requires Human confirmation)
  3. `get_inventory_summary` (Read-only system KPI query)
- **Security Boundaries:**
  - **Zero Direct Database Access:** The LLM cannot execute SQL, run scripts, or touch models directly.
  - **Server-Side Identity Binding:** The caller's authenticated session (`request.user`) is authoritative.
  - **Human-in-the-Loop Gate:** Generating a purchase order pauses execution with status `PENDING_CONFIRMATION` until the human manager explicitly authorizes it.
  - **Audit Logging:** Every AI execution is persisted in `AgentAuditLog` with sanitized parameters (credentials and API keys masked).

---

## 🌿 Git Workflow & Repository Audit

- **Active Branch:** `docs/final-documentation`
- **Main Remote:** `origin` (`https://github.com/tasneembadr772-cell/smart-inventory-sales-agent.git`)
- **Commit Methodology:** Conventional Commits (`feat:`, `chore:`, `fix:`) with modular feature branches merged via pull requests (`#7`, `#8`, `#9`, `#10`).
- **Audit Verification Status:**
  - *Local History:* Factually verified.
  - *GitHub Pull Request & Issue Discussions:* **MANUAL VERIFICATION REQUIRED** (Web browser or GitHub credentials needed to inspect remote web issue threads).

---

## 📦 PostgreSQL Database Dump Deliverable

To generate a sanitized PostgreSQL database dump prior to final graduation submission:

```bash
# Run pg_dump from your PostgreSQL installation directory:
pg_dump -U postgres -h localhost -p 5432 -d inventory_sales_db -F c -b -v -f "nexus_erp_demo_dump.dump"
```
*Note: Ensure demo passwords and sensitive API keys are stripped or reset to default demo credentials prior to submitting the dump file.*

---

## ⏱️ 15-Minute Graduation Project Defense Guide

When presenting NexusERP to the university examination committee, follow this structured, high-impact order:

| Minute | Presentation Phase | What to Demonstrate & Explain |
| :---: | :--- | :--- |
| **01–02** | **1. The Problem & Business Need** | Inefficient manual inventory tracking, stockout risks, and human error in procurement drafting. |
| **03–04** | **2. The Solution & Architecture** | Introduce NexusERP as an MVT web application. Present the **System Architecture Diagram** showing clean separation between Views, Selectors, Services, and PostgreSQL. |
| **05–06** | **3. Database & Relational ERD** | Open `docs/ERD.md`. Highlight 3NF normalization, header/item separation (`Sale`/`SaleItem`, `PurchaseOrder`/`PurchaseOrderItem`), immutable `InventoryTransaction` ledger, and database check constraints. |
| **07–08** | **4. Authentication & RBAC Boundary** | Demonstrate login across roles (`admin`, `manager`, `cashier`). Prove that standard users cannot access manager areas or delete catalog items (show HTTP 403 Forbidden). |
| **09–10** | **5. Concurrency-Safe Inventory & Sales** | Demonstrate POS sale creation. Explain row-level concurrency locking (`select_for_update()`), real-time stock deduction, and immediate creation of an immutable audit record. |
| **11–12** | **6. Purchase Order Replenishment Lifecycle** | Walk through PO status advancement: `DRAFT` → `PENDING` → `APPROVED` → `RECEIVED`. Show that marking `RECEIVED` automatically increments physical stock. |
| **13–14** | **7. Agentic AI & Security Sandboxing** | Open `/ai/`. Prompt the AI: *"Check low stock products and prepare a draft PO."* Point out the **Human-in-the-Loop confirmation modal**, explain the 3-tool allowlist, and open the Django admin to show the sanitized `AgentAuditLog`. |
| **15** | **8. Testing & Delivery Summary** | Highlight **272 passing automated tests**, clean system checks, and conclude with Q&A. |

---

## ⚠️ Known Limitations & Future Roadmap

- **Single-Node Deployment:** Current architecture runs as a single-node Django instance; horizontal scaling with load balancers (e.g. Nginx + Gunicorn) and distributed caching (Redis) is planned for future enterprise rollouts.
- **Asynchronous Processing:** Background report generation and automated vendor email dispatching are scheduled for integration via Celery/Redis in Phase 2.
