"""
Django Management Command to seed realistic inventory data for testing and defense demonstration.
Creates categories, suppliers, diverse products (in-stock, low-stock, out-of-stock, inactive with stock),
and recorded stock movement transactions (ADD, REMOVE, ADJUSTMENT).
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.authentication.models import User
from apps.domain_app.models import Category, Supplier, Product, InventoryTransaction


class Command(BaseCommand):
    help = 'Seeds realistic inventory data, categories, suppliers, and stock transactions.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing products, suppliers, and transactions before seeding.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Starting inventory database seeding...'))

        if options['clear']:
            self.stdout.write(self.style.WARNING('Clearing existing inventory transactions, products, and suppliers...'))
            InventoryTransaction.objects.all().delete()
            Product.objects.all().delete()
            Supplier.objects.all().delete()
            Category.objects.all().delete()

        # 1. Ensure privileged user for audit trail
        admin_user = User.objects.filter(role__in=[User.Role.ADMIN, User.Role.MANAGER]).first()
        if not admin_user:
            admin_user = User.objects.filter(is_superuser=True).first()

        # 2. Categories
        categories_data = [
            {'name': 'Computer Components', 'description': 'Processors, RAM kits, graphics cards, and internal computing components.'},
            {'name': 'Networking & Infrastructure', 'description': 'Enterprise switches, wireless access points, patch panels, and routers.'},
            {'name': 'Peripherals & Displays', 'description': 'Mechanical keyboards, ergonomic mice, monitors, and workspace equipment.'},
            {'name': 'Storage & Memory', 'description': 'PCIe 4.0 NVMe drives, enterprise SATA SSDs, NAS hard drives, and memory modules.'},
            {'name': 'Cables & Power', 'description': 'High-speed fiber cables, modular power supplies, HDMI adapters, and surge protectors.'},
        ]

        categories = {}
        for cdata in categories_data:
            cat, created = Category.objects.get_or_create(
                name=cdata['name'],
                defaults={'description': cdata['description'], 'is_active': True}
            )
            categories[cdata['name']] = cat

        self.stdout.write(self.style.SUCCESS(f'Verified {len(categories)} categories.'))

        # 3. Suppliers
        suppliers_data = [
            {
                'name': 'Apex Micro Technologies',
                'contact_person': 'Elena Vance',
                'email': 'elena@apexmicro.com',
                'phone': '+1-555-0192',
                'address': 'Building 4, Silicon Valley Tech Park, CA 94025',
                'is_active': True,
            },
            {
                'name': 'Nexus Network Distribution',
                'contact_person': 'Marcus Brody',
                'email': 'procurement@nexusdist.net',
                'phone': '+1-555-0144',
                'address': '742 Evergreen Terrace, Portland, OR 97201',
                'is_active': True,
            },
            {
                'name': 'Global Storage Solutions',
                'contact_person': 'Sarah Chen',
                'email': 'orders@globalstorage.io',
                'phone': '+1-555-0178',
                'address': '100 Innovation Way, Austin, TX 78701',
                'is_active': True,
            },
            {
                'name': 'ProGear Workspace Hardware',
                'contact_person': 'David Miller',
                'email': 'sales@progearhardware.com',
                'phone': '+1-555-0123',
                'address': '55 Logistics Blvd, Chicago, IL 60607',
                'is_active': True,
            },
        ]

        suppliers = {}
        for sdata in suppliers_data:
            supp, created = Supplier.objects.get_or_create(
                name=sdata['name'],
                defaults=sdata
            )
            suppliers[sdata['name']] = supp

        self.stdout.write(self.style.SUCCESS(f'Verified {len(suppliers)} suppliers.'))

        # 4. Realistic Products
        products_data = [
            # In-Stock Healthy Items
            {
                'sku': 'KB-PRO-001',
                'name': 'Pro Mechanical Keyboard (RGB Cherry MX Brown)',
                'category': categories['Peripherals & Displays'],
                'supplier': suppliers['ProGear Workspace Hardware'],
                'price': Decimal('129.99'),
                'stock_quantity': 45,
                'reorder_level': 10,
                'target_stock_level': 60,
                'is_active': True,
                'description': 'Aerospace-grade aluminum body, per-key RGB illumination, and hot-swappable mechanical switches.',
            },
            {
                'sku': 'SSD-NVME-1T',
                'name': '1TB PCIe 4.0 NVMe M.2 Solid State Drive',
                'category': categories['Storage & Memory'],
                'supplier': suppliers['Global Storage Solutions'],
                'price': Decimal('89.50'),
                'stock_quantity': 65,
                'reorder_level': 15,
                'target_stock_level': 80,
                'is_active': True,
                'description': 'High-performance NVMe SSD reaching sequential read speeds of 7,300 MB/s with graphene heat spreader.',
            },
            {
                'sku': 'MON-UW-340',
                'name': 'UltraWide 34-Inch Curved Productivity Monitor',
                'category': categories['Peripherals & Displays'],
                'supplier': suppliers['ProGear Workspace Hardware'],
                'price': Decimal('499.00'),
                'stock_quantity': 18,
                'reorder_level': 5,
                'target_stock_level': 25,
                'is_active': True,
                'description': '1440p WQHD resolution, 1500R curvature, 99% sRGB color gamut, and integrated 90W USB-C docking.',
            },
            {
                'sku': 'AP-WIFI-6E',
                'name': 'Enterprise Wi-Fi 6E Tri-Band Access Point',
                'category': categories['Networking & Infrastructure'],
                'supplier': suppliers['Nexus Network Distribution'],
                'price': Decimal('320.00'),
                'stock_quantity': 28,
                'reorder_level': 8,
                'target_stock_level': 40,
                'is_active': True,
                'description': 'Tri-band 2.4/5/6 GHz wireless access point supporting up to 500 concurrent client devices and PoE+.',
            },

            # Low Stock Items (Requiring Attention - Warning)
            {
                'sku': 'RAM-D5-32G',
                'name': '32GB (2x16GB) DDR5 6000MHz CL30 RAM Kit',
                'category': categories['Computer Components'],
                'supplier': suppliers['Apex Micro Technologies'],
                'price': Decimal('115.00'),
                'stock_quantity': 3,
                'reorder_level': 10,
                'target_stock_level': 30,
                'is_active': True,
                'description': 'Low-latency DDR5 memory optimized for next-gen desktop workstations and server compilation nodes.',
            },
            {
                'sku': 'MS-ERGO-002',
                'name': 'Ergonomic Vertical Wireless Mouse',
                'category': categories['Peripherals & Displays'],
                'supplier': suppliers['ProGear Workspace Hardware'],
                'price': Decimal('64.99'),
                'stock_quantity': 4,
                'reorder_level': 12,
                'target_stock_level': 35,
                'is_active': True,
                'description': 'Natural 57-degree vertical handshake angle preventing carpal tunnel strain with rechargeable battery.',
            },
            {
                'sku': 'CBL-FIB-10M',
                'name': 'OM4 Multimode Fiber Optic Cable (10 Meters)',
                'category': categories['Cables & Power'],
                'supplier': suppliers['Nexus Network Distribution'],
                'price': Decimal('28.50'),
                'stock_quantity': 5,
                'reorder_level': 15,
                'target_stock_level': 50,
                'is_active': True,
                'description': 'Duplex LC-LC 50/125 laser-optimized multimode fiber patch cable rated for 40G/100G Ethernet links.',
            },

            # Out of Stock Items (Requiring Attention - Critical)
            {
                'sku': 'SW-MNG-08P',
                'name': '8-Port Managed Gigabit PoE+ Industrial Switch',
                'category': categories['Networking & Infrastructure'],
                'supplier': suppliers['Nexus Network Distribution'],
                'price': Decimal('210.00'),
                'stock_quantity': 0,
                'reorder_level': 6,
                'target_stock_level': 20,
                'is_active': True,
                'description': 'Rugged DIN-rail mountable network switch delivering 130W total PoE power budget for IP cameras and APs.',
            },
            {
                'sku': 'SSD-NVME-4T',
                'name': '4TB PCIe 4.0 High-Endurance NVMe SSD',
                'category': categories['Storage & Memory'],
                'supplier': suppliers['Global Storage Solutions'],
                'price': Decimal('299.99'),
                'stock_quantity': 0,
                'reorder_level': 8,
                'target_stock_level': 25,
                'is_active': True,
                'description': 'Extreme capacity M.2 drive rated for 3,000 TBW endurance for heavy database servers and VM virtualization.',
            },

            # Inactive Item with Stranded Stock (Requiring Attention - Audit for Managers)
            {
                'sku': 'ADP-VGA-HD',
                'name': 'Legacy VGA to HDMI Adapter Converter',
                'category': categories['Cables & Power'],
                'supplier': suppliers['Apex Micro Technologies'],
                'price': Decimal('14.99'),
                'stock_quantity': 16,
                'reorder_level': 5,
                'target_stock_level': 20,
                'is_active': False,
                'description': 'Discontinued analog-to-digital video converter. Retained in storage pending final liquidation clearance.',
            },
        ]

        persisted_products = {}
        for pdata in products_data:
            prod, created = Product.objects.update_or_create(
                sku=pdata['sku'],
                defaults=pdata
            )
            persisted_products[pdata['sku']] = prod

        self.stdout.write(self.style.SUCCESS(f'Verified {len(persisted_products)} products.'))

        # 5. Realistic Stock Movement Audit Ledger (Recent Transactions)
        # Clear previous transactions for these products if already exist to have fresh ledger
        InventoryTransaction.objects.filter(product__in=persisted_products.values()).delete()

        transactions_data = [
            {
                'product': persisted_products['KB-PRO-001'],
                'type': InventoryTransaction.TransactionType.ADD,
                'quantity': 25,
                'previous_stock': 20,
                'new_stock': 45,
                'reference': 'PO-2026-0819',
                'notes': 'Quarterly container replenishment shipment received at Dock B.',
            },
            {
                'product': persisted_products['SW-MNG-08P'],
                'type': InventoryTransaction.TransactionType.REMOVE,
                'quantity': 5,
                'previous_stock': 5,
                'new_stock': 0,
                'reference': 'DISP-89214',
                'notes': 'Final inventory dispatched for Regional Office VoIP deployment.',
            },
            {
                'product': persisted_products['SSD-NVME-1T'],
                'type': InventoryTransaction.TransactionType.ADD,
                'quantity': 30,
                'previous_stock': 35,
                'new_stock': 65,
                'reference': 'PO-2026-0814',
                'notes': 'Supplier direct batch intake verified and barcode scanned.',
            },
            {
                'product': persisted_products['RAM-D5-32G'],
                'type': InventoryTransaction.TransactionType.REMOVE,
                'quantity': 7,
                'previous_stock': 10,
                'new_stock': 3,
                'reference': 'ORD-77412',
                'notes': 'Fulfilled custom server builder client purchase order.',
            },
            {
                'product': persisted_products['MS-ERGO-002'],
                'type': InventoryTransaction.TransactionType.ADJUSTMENT,
                'quantity': 2,
                'previous_stock': 6,
                'new_stock': 4,
                'reference': 'AUDIT-Q3-01',
                'notes': 'Warehouse physical cycle count calibration. Two damaged units written off.',
            },
            {
                'product': persisted_products['AP-WIFI-6E'],
                'type': InventoryTransaction.TransactionType.ADD,
                'quantity': 15,
                'previous_stock': 13,
                'new_stock': 28,
                'reference': 'PO-2026-0802',
                'notes': 'Restocked campus enterprise networking supply inventory.',
            },
            {
                'product': persisted_products['SSD-NVME-4T'],
                'type': InventoryTransaction.TransactionType.REMOVE,
                'quantity': 8,
                'previous_stock': 8,
                'new_stock': 0,
                'reference': 'DISP-90114',
                'notes': 'High-density storage nodes provisioned for Data Center Rack 4.',
            },
            {
                'product': persisted_products['CBL-FIB-10M'],
                'type': InventoryTransaction.TransactionType.REMOVE,
                'quantity': 10,
                'previous_stock': 15,
                'new_stock': 5,
                'reference': 'ORD-81190',
                'notes': 'Dispatched patch cables for infrastructure upgrade contract.',
            },
        ]

        for tx in transactions_data:
            InventoryTransaction.objects.create(
                product=tx['product'],
                transaction_type=tx['type'],
                quantity=tx['quantity'],
                previous_stock=tx['previous_stock'],
                new_stock=tx['new_stock'],
                reference=tx['reference'],
                notes=tx['notes'],
                created_by=admin_user,
            )

        self.stdout.write(self.style.SUCCESS(f'Created {len(transactions_data)} audit ledger transactions.'))
        self.stdout.write(self.style.SUCCESS('Inventory database successfully populated with realistic data!'))
