"""
Django Management Command: seed_demo_data

Populates clean, realistic, production-ready demonstration data for the graduation project evaluation:
- Complete users for each RBAC role (Admin, Store Manager, Cashier / Sales)
- 3 Active Suppliers with complete contact details
- 4 Categories (Electronics, Stationery, Hardware, Packaging)
- At least 8 Products (3 low stock, 1 out of stock, 4 healthy stock)
- At least 2 completed Sales Orders with line items and stock movement audit records
- At least 1 Draft Purchase Order with line items

Strictly idempotent: can be safely executed repeatedly without creating duplicates or distorting inventory.
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.authentication.models import User
from apps.domain_app.models import (
    Category,
    InventoryTransaction,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Sale,
    SaleItem,
    Supplier,
)


class Command(BaseCommand):
    help = "Seeds clean, realistic demo data for graduation defense evaluation (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("===> Starting NexusERP Demo Data Seeding..."))

        # ----------------------------------------------------------------------
        # 1. RBAC Users
        # ----------------------------------------------------------------------
        users_data = [
            {
                "username": "admin",
                "email": "admin@example.com",
                "password": "Admin@12345",
                "first_name": "System",
                "last_name": "Administrator",
                "role": User.Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
            {
                "username": "manager",
                "email": "manager@example.com",
                "password": "Manager@12345",
                "first_name": "Sarah",
                "last_name": "Jenkins",
                "role": User.Role.MANAGER,
                "is_staff": True,
                "is_superuser": False,
            },
            {
                "username": "cashier",
                "email": "cashier@example.com",
                "password": "Cashier@12345",
                "first_name": "Alex",
                "last_name": "Rivera",
                "role": User.Role.STANDARD,
                "is_staff": False,
                "is_superuser": False,
            },
        ]

        seeded_users = {}
        for uinfo in users_data:
            user = User.objects.filter(username=uinfo["username"]).first()
            if not user:
                user = User.objects.create_user(
                    username=uinfo["username"],
                    email=uinfo["email"],
                    password=uinfo["password"],
                    first_name=uinfo["first_name"],
                    last_name=uinfo["last_name"],
                    role=uinfo["role"],
                    is_staff=uinfo["is_staff"],
                    is_superuser=uinfo["is_superuser"],
                )
                self.stdout.write(self.style.SUCCESS(f"  [+] Created User '{user.username}' ({user.get_role_display()})"))
            else:
                user.email = uinfo["email"]
                user.role = uinfo["role"]
                user.first_name = uinfo["first_name"]
                user.last_name = uinfo["last_name"]
                user.is_staff = uinfo["is_staff"]
                user.is_superuser = uinfo["is_superuser"]
                user.set_password(uinfo["password"])
                user.save()
                self.stdout.write(self.style.SUCCESS(f"  [*] Updated User '{user.username}' ({user.get_role_display()})"))
            seeded_users[uinfo["username"]] = user

        admin_user = seeded_users["admin"]
        manager_user = seeded_users["manager"]
        cashier_user = seeded_users["cashier"]

        # ----------------------------------------------------------------------
        # 2. Categories (4 Categories)
        # ----------------------------------------------------------------------
        categories_data = [
            {
                "name": "Electronics",
                "description": "High-performance compute hardware, chipsets, memory, and graphics processing units.",
            },
            {
                "name": "Stationery",
                "description": "Commercial office consumables, thermal labels, barcodes, and documentation supplies.",
            },
            {
                "name": "Hardware",
                "description": "Server rack mounting hardware, cabling, networking accessories, and chassis components.",
            },
            {
                "name": "Packaging",
                "description": "Anti-static shielding materials, ESD bubble wraps, shipping boxes, and protective containers.",
            },
        ]

        categories = {}
        for cdata in categories_data:
            cat, created = Category.objects.get_or_create(
                name=cdata["name"],
                defaults={"description": cdata["description"], "is_active": True},
            )
            if not created and cat.description != cdata["description"]:
                cat.description = cdata["description"]
                cat.save(update_fields=["description"])
            categories[cdata["name"]] = cat
            status_tag = "[+]" if created else "[*]"
            self.stdout.write(f"  {status_tag} Category: '{cat.name}'")

        # ----------------------------------------------------------------------
        # 3. Suppliers (3 Suppliers with Complete Contact Details)
        # ----------------------------------------------------------------------
        suppliers_data = [
            {
                "name": "Global Tech Components Ltd",
                "contact_person": "Alexander Wright",
                "phone": "+1-555-0182",
                "email": "contact@globaltechcomp.com",
                "address": "Suite 400, 102 Silicon Parkway, San Jose, CA 95134",
            },
            {
                "name": "Apex Office & Logistics Supplies",
                "contact_person": "Sophia Martinez",
                "phone": "+1-555-0245",
                "email": "sales@apexsupplies.org",
                "address": "780 Commerce Industrial Blvd, Austin, TX 78744",
            },
            {
                "name": "OmniCore Industrial Hardware",
                "contact_person": "Marcus Sterling",
                "phone": "+1-555-0391",
                "email": "orders@omnicorehw.com",
                "address": "1200 Manufacturing Way, Chicago, IL 60609",
            },
        ]

        suppliers = {}
        for sdata in suppliers_data:
            supplier, created = Supplier.objects.get_or_create(
                name=sdata["name"],
                defaults={
                    "contact_person": sdata["contact_person"],
                    "phone": sdata["phone"],
                    "email": sdata["email"],
                    "address": sdata["address"],
                    "is_active": True,
                },
            )
            if not created:
                supplier.contact_person = sdata["contact_person"]
                supplier.phone = sdata["phone"]
                supplier.email = sdata["email"]
                supplier.address = sdata["address"]
                supplier.is_active = True
                supplier.save()
            suppliers[sdata["name"]] = supplier
            status_tag = "[+]" if created else "[*]"
            self.stdout.write(f"  {status_tag} Supplier: '{supplier.name}' (Contact: {supplier.contact_person})")

        # ----------------------------------------------------------------------
        # 4. Products (8+ Products: 3 Low Stock, 1 Out of Stock, 4 Healthy Stock)
        # ----------------------------------------------------------------------
        products_data = [
            # 3 Low Stock items (current_stock <= reorder_level and current_stock > 0)
            {
                "sku": "ELEC-PROC-001",
                "name": "Intel Core i7-14700K Desktop Processor",
                "description": "20 cores (8 P-cores + 12 E-cores) up to 5.6 GHz, LGA1700 unlocked.",
                "category": categories["Electronics"],
                "supplier": suppliers["Global Tech Components Ltd"],
                "price": Decimal("389.99"),
                "stock_quantity": 3,
                "reorder_level": 10,
                "target_stock_level": 25,
            },
            {
                "sku": "STAT-PRNT-002",
                "name": "Thermal Barcode Label Rolls (500 labels/roll)",
                "description": "4x6 direct thermal transfer industrial warehouse labels.",
                "category": categories["Stationery"],
                "supplier": suppliers["Apex Office & Logistics Supplies"],
                "price": Decimal("18.50"),
                "stock_quantity": 4,
                "reorder_level": 15,
                "target_stock_level": 50,
            },
            {
                "sku": "HDWR-CABL-003",
                "name": "Cat6A Shielded S/FTP Ethernet Spool (50m)",
                "description": "Pure bare copper 10Gbps enterprise high-density network cable.",
                "category": categories["Hardware"],
                "supplier": suppliers["OmniCore Industrial Hardware"],
                "price": Decimal("42.00"),
                "stock_quantity": 2,
                "reorder_level": 8,
                "target_stock_level": 20,
            },
            # 1 Out of Stock item (current_stock == 0)
            {
                "sku": "ELEC-GPU-004",
                "name": "NVIDIA GeForce RTX 4070 Ti Super 16GB",
                "description": "Ada Lovelace architecture, DLSS 3, 256-bit GDDR6X ray tracing GPU.",
                "category": categories["Electronics"],
                "supplier": suppliers["Global Tech Components Ltd"],
                "price": Decimal("799.99"),
                "stock_quantity": 0,
                "reorder_level": 5,
                "target_stock_level": 15,
            },
            # 4 Healthy Stock items (current_stock > reorder_level)
            {
                "sku": "PCKG-ESD-005",
                "name": "Anti-Static Shielding Bags 10x12 (Pack of 100)",
                "description": "Faraday cage ESD safe metallized moisture barrier storage bags.",
                "category": categories["Packaging"],
                "supplier": suppliers["Apex Office & Logistics Supplies"],
                "price": Decimal("24.00"),
                "stock_quantity": 65,
                "reorder_level": 15,
                "target_stock_level": 80,
            },
            {
                "sku": "STAT-PEN-006",
                "name": "Industrial Waterproof Marker Pen Set (12-pack)",
                "description": "Quick-drying indelible black markers for metal and plastic labeling.",
                "category": categories["Stationery"],
                "supplier": suppliers["Apex Office & Logistics Supplies"],
                "price": Decimal("14.25"),
                "stock_quantity": 80,
                "reorder_level": 20,
                "target_stock_level": 100,
            },
            {
                "sku": "HDWR-RACK-007",
                "name": "1U Universal Server Rack Cantilever Shelf",
                "description": "Heavy-duty cold rolled steel 19-inch equipment shelf.",
                "category": categories["Hardware"],
                "supplier": suppliers["OmniCore Industrial Hardware"],
                "price": Decimal("34.50"),
                "stock_quantity": 45,
                "reorder_level": 10,
                "target_stock_level": 60,
            },
            {
                "sku": "ELEC-RAM-008",
                "name": "Crucial Pro DDR5 32GB (2x16GB) 6000MHz Kit",
                "description": "Low-latency Intel XMP 3.0 & AMD EXPO compatible memory modules.",
                "category": categories["Electronics"],
                "supplier": suppliers["Global Tech Components Ltd"],
                "price": Decimal("119.99"),
                "stock_quantity": 30,
                "reorder_level": 8,
                "target_stock_level": 40,
            },
        ]

        products = {}
        for pdata in products_data:
            sku = pdata["sku"]
            product = Product.objects.filter(sku=sku).first()
            if not product:
                product = Product.objects.create(
                    sku=sku,
                    name=pdata["name"],
                    description=pdata["description"],
                    category=pdata["category"],
                    supplier=pdata["supplier"],
                    price=pdata["price"],
                    stock_quantity=pdata["stock_quantity"],
                    reorder_level=pdata["reorder_level"],
                    target_stock_level=pdata["target_stock_level"],
                    is_active=True,
                )
                self.stdout.write(f"  [+] Product: '{product.name}' (Stock: {product.stock_quantity}, Reorder: {product.reorder_level})")
            else:
                product.name = pdata["name"]
                product.description = pdata["description"]
                product.category = pdata["category"]
                product.supplier = pdata["supplier"]
                product.price = pdata["price"]
                product.stock_quantity = pdata["stock_quantity"]
                product.reorder_level = pdata["reorder_level"]
                product.target_stock_level = pdata["target_stock_level"]
                product.is_active = True
                product.save()
                self.stdout.write(f"  [*] Product: '{product.name}' (Stock: {product.stock_quantity}, Reorder: {product.reorder_level})")
            products[sku] = product

        # ----------------------------------------------------------------------
        # 5. Completed Sales Orders (2+ Orders with Items & Inventory Transactions)
        # ----------------------------------------------------------------------
        # Sale 1
        sale1_id = "SALE-DEMO-001"
        sale1 = Sale.objects.filter(order_identifier=sale1_id).first()
        if not sale1:
            sale1 = Sale.objects.create(
                order_identifier=sale1_id,
                customer_name="Acme Corporation Tech Lab",
                customer_email="procurement@acme.corp",
                customer_phone="+1-555-9001",
                sale_date=timezone.now() - timezone.timedelta(days=2),
                status=Sale.Status.COMPLETED,
                total_amount=Decimal("140.25"),
                notes="Standard wholesale shipment to secondary workshop facility.",
                created_by=cashier_user,
            )
            # Item A: 2x HDWR-RACK-007 ($34.50 ea = $69.00)
            item1_a = SaleItem.objects.create(
                sale=sale1,
                product=products["HDWR-RACK-007"],
                quantity=2,
                unit_price=Decimal("34.50"),
                subtotal=Decimal("69.00"),
            )
            # Item B: 5x STAT-PEN-006 ($14.25 ea = $71.25)
            item1_b = SaleItem.objects.create(
                sale=sale1,
                product=products["STAT-PEN-006"],
                quantity=5,
                unit_price=Decimal("14.25"),
                subtotal=Decimal("71.25"),
            )
            # Audit stock movement
            InventoryTransaction.objects.create(
                product=products["HDWR-RACK-007"],
                transaction_type=InventoryTransaction.TransactionType.REMOVE,
                quantity=2,
                previous_stock=47,
                new_stock=45,
                reference=sale1.order_identifier,
                notes="Sale fulfillment: 2 units sold to Acme Corporation.",
                created_by=cashier_user,
            )
            InventoryTransaction.objects.create(
                product=products["STAT-PEN-006"],
                transaction_type=InventoryTransaction.TransactionType.REMOVE,
                quantity=5,
                previous_stock=85,
                new_stock=80,
                reference=sale1.order_identifier,
                notes="Sale fulfillment: 5 units sold to Acme Corporation.",
                created_by=cashier_user,
            )
            self.stdout.write(self.style.SUCCESS(f"  [+] Completed Sale '{sale1.order_identifier}' ($140.25)"))
        else:
            self.stdout.write(f"  [*] Completed Sale '{sale1.order_identifier}' already exists.")

        # Sale 2
        sale2_id = "SALE-DEMO-002"
        sale2 = Sale.objects.filter(order_identifier=sale2_id).first()
        if not sale2:
            sale2 = Sale.objects.create(
                order_identifier=sale2_id,
                customer_name="Vanguard Dynamic Systems",
                customer_email="billing@vanguard.io",
                customer_phone="+1-555-9002",
                sale_date=timezone.now() - timezone.timedelta(days=1),
                status=Sale.Status.COMPLETED,
                total_amount=Decimal("335.98"),
                notes="Express dispatch for high-priority engineering workstation upgrades.",
                created_by=cashier_user,
            )
            # Item A: 4x PCKG-ESD-005 ($24.00 ea = $96.00)
            item2_a = SaleItem.objects.create(
                sale=sale2,
                product=products["PCKG-ESD-005"],
                quantity=4,
                unit_price=Decimal("24.00"),
                subtotal=Decimal("96.00"),
            )
            # Item B: 2x ELEC-RAM-008 ($119.99 ea = $239.98)
            item2_b = SaleItem.objects.create(
                sale=sale2,
                product=products["ELEC-RAM-008"],
                quantity=2,
                unit_price=Decimal("119.99"),
                subtotal=Decimal("239.98"),
            )
            # Audit stock movement
            InventoryTransaction.objects.create(
                product=products["PCKG-ESD-005"],
                transaction_type=InventoryTransaction.TransactionType.REMOVE,
                quantity=4,
                previous_stock=69,
                new_stock=65,
                reference=sale2.order_identifier,
                notes="Sale fulfillment: 4 units sold to Vanguard Dynamics.",
                created_by=cashier_user,
            )
            InventoryTransaction.objects.create(
                product=products["ELEC-RAM-008"],
                transaction_type=InventoryTransaction.TransactionType.REMOVE,
                quantity=2,
                previous_stock=32,
                new_stock=30,
                reference=sale2.order_identifier,
                notes="Sale fulfillment: 2 units sold to Vanguard Dynamics.",
                created_by=cashier_user,
            )
            self.stdout.write(self.style.SUCCESS(f"  [+] Completed Sale '{sale2.order_identifier}' ($335.98)"))
        else:
            self.stdout.write(f"  [*] Completed Sale '{sale2.order_identifier}' already exists.")

        # ----------------------------------------------------------------------
        # 6. Draft Purchase Order (1+ Draft PO with Line Items)
        # ----------------------------------------------------------------------
        po_num = "PO-DEMO-001"
        po = PurchaseOrder.objects.filter(order_number=po_num).first()
        if not po:
            supplier = suppliers["Global Tech Components Ltd"]
            po = PurchaseOrder.objects.create(
                order_number=po_num,
                supplier=supplier,
                status=PurchaseOrder.Status.DRAFT,
                total_amount=Decimal("6600.00"),
                notes="Autonomous AI replenishment draft: restocking processors and depleted GPU inventory.",
                created_by=manager_user,
            )
            # Item A: 10x ELEC-PROC-001 @ $320.00 = $3200.00
            PurchaseOrderItem.objects.create(
                purchase_order=po,
                product=products["ELEC-PROC-001"],
                quantity=10,
                unit_cost=Decimal("320.00"),
                subtotal=Decimal("3200.00"),
            )
            # Item B: 5x ELEC-GPU-004 @ $680.00 = $3400.00
            PurchaseOrderItem.objects.create(
                purchase_order=po,
                product=products["ELEC-GPU-004"],
                quantity=5,
                unit_cost=Decimal("680.00"),
                subtotal=Decimal("3400.00"),
            )
            self.stdout.write(self.style.SUCCESS(f"  [+] Draft Purchase Order '{po.order_number}' ($6,600.00, Supplier: {supplier.name})"))
        else:
            self.stdout.write(f"  [*] Draft Purchase Order '{po.order_number}' already exists.")

        self.stdout.write(self.style.SUCCESS("===> NexusERP Demo Data Seeding Completed Successfully!"))
