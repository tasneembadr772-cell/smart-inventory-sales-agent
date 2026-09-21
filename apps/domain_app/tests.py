"""
Automated Test Suite for Inventory Product and Category Management.

Covers:
1. Normalized Model Constraints, Foreign Keys, Unique SKU, and PROTECT deletion.
2. Domain Selectors, Search, Filter, and N+1 query avoidance.
3. Domain Services, Transactions, and Business Rules.
4. Role-Based Access Control (RBAC): Admin vs. Manager vs. Standard vs. Anonymous.
5. Form sanitization and validation.
"""

from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.test import TestCase, Client
from django.urls import reverse

from .models import Category, Product, Supplier, InventoryTransaction, Sale, SaleItem, PurchaseOrder, PurchaseOrderItem
from .forms import SupplierForm, StockAdjustmentForm, SaleFilterForm, SaleCreateForm, PurchaseOrderForm
from .services import InsufficientStockError, InvalidStockAdjustmentError, SaleCreationError, PurchaseOrderError
from . import selectors, services

User = get_user_model()


class CategoryAndProductModelTestCase(TestCase):
    """Verifies relational normalization, database constraints, and model helper methods."""

    def setUp(self):
        self.category = Category.objects.create(
            name='Hardware & Peripherals',
            description='Keyboards, mice, and desk gear.',
        )

    def test_category_creation_and_slug_autogen(self):
        self.assertEqual(self.category.name, 'Hardware & Peripherals')
        self.assertEqual(self.category.slug, 'hardware-peripherals')
        self.assertTrue(self.category.is_active)
        self.assertEqual(str(self.category), 'Hardware & Peripherals')

    def test_category_name_uniqueness(self):
        with self.assertRaises((IntegrityError, ValidationError)):
            Category.objects.create(name='Hardware & Peripherals')

    def test_product_creation_and_attributes(self):
        product = Product.objects.create(
            name='Ergonomic Mechanical Keyboard',
            sku='KB-ERGO-001',
            category=self.category,
            price=Decimal('129.99'),
            stock_quantity=25,
            reorder_level=5,
        )
        self.assertEqual(product.sku, 'KB-ERGO-001')
        self.assertEqual(product.stock_status, 'in_stock')
        self.assertFalse(product.is_low_stock)
        self.assertFalse(product.is_out_of_stock)

    def test_product_stock_health_properties(self):
        # Low stock test
        p_low = Product.objects.create(
            name='Low Stock Mouse',
            sku='MS-LOW-001',
            category=self.category,
            price=Decimal('49.99'),
            stock_quantity=4,
            reorder_level=5,
        )
        self.assertTrue(p_low.is_low_stock)
        self.assertFalse(p_low.is_out_of_stock)
        self.assertEqual(p_low.stock_status, 'low_stock')

        # Out of stock test (satisfies current quantity <= reorder_level as well as out_of_stock)
        p_out = Product.objects.create(
            name='Out of Stock Headset',
            sku='HD-OUT-001',
            category=self.category,
            price=Decimal('89.99'),
            stock_quantity=0,
            reorder_level=5,
        )
        self.assertTrue(p_out.is_low_stock)
        self.assertTrue(p_out.is_out_of_stock)
        self.assertEqual(p_out.stock_status, 'out_of_stock')

    def test_sku_uniqueness_enforced(self):
        Product.objects.create(
            name='First Item',
            sku='UNIQUE-SKU-1',
            category=self.category,
            price=Decimal('10.00'),
        )
        with self.assertRaises((IntegrityError, ValidationError)):
            Product.objects.create(
                name='Second Item with Same SKU',
                sku='UNIQUE-SKU-1',
                category=self.category,
                price=Decimal('20.00'),
            )

    def test_database_level_check_constraint_negative_price(self):
        with self.assertRaises((IntegrityError, ValidationError)):
            p = Product(
                name='Negative Price Item',
                sku='NEG-PRICE',
                category=self.category,
                price=Decimal('-15.00'),
                stock_quantity=10,
            )
            p.save()

    def test_database_level_check_constraint_negative_stock(self):
        with self.assertRaises((IntegrityError, ValidationError)):
            p = Product(
                name='Negative Stock Item',
                sku='NEG-STOCK',
                category=self.category,
                price=Decimal('15.00'),
                stock_quantity=-5,
            )
            p.save()

    def test_relational_protection_prevents_category_deletion_with_products(self):
        """
        Academic Defense Highlight:
        Verifies `on_delete=models.PROTECT` prevents accidental cascade deletion of inventory.
        """
        Product.objects.create(
            name='Dependent SKU',
            sku='DEP-SKU-001',
            category=self.category,
            price=Decimal('25.00'),
            stock_quantity=10,
        )
        with self.assertRaises(models.ProtectedError):
            self.category.delete()


class DomainServicesTestCase(TestCase):
    """Tests domain services, transactional consistency, and business exceptions."""

    def setUp(self):
        self.category = services.create_category(
            name='Storage Devices',
            description='SSDs and HDDs',
        )

    def test_create_product_service(self):
        product = services.create_product(
            name='NVMe SSD 1TB',
            sku='ssd-nvme-1tb',
            category=self.category,
            price=Decimal('89.50'),
            stock_quantity=50,
            reorder_level=10,
        )
        # SKU must be automatically normalized to uppercase
        self.assertEqual(product.sku, 'SSD-NVME-1TB')
        self.assertEqual(product.price, Decimal('89.50'))

    def test_create_duplicate_sku_raises_validation_error(self):
        services.create_product(
            name='Item A',
            sku='DUPLICATE-SKU',
            category=self.category,
            price=Decimal('10.00'),
        )
        with self.assertRaises(ValidationError):
            services.create_product(
                name='Item B',
                sku='duplicate-sku',
                category=self.category,
                price=Decimal('20.00'),
            )

    def test_update_product_service(self):
        product = services.create_product(
            name='Initial Name',
            sku='UP-SKU-1',
            category=self.category,
            price=Decimal('50.00'),
        )
        updated = services.update_product(
            product,
            name='Updated Name',
            price=Decimal('45.00'),
            stock_quantity=15,
        )
        self.assertEqual(updated.name, 'Updated Name')
        self.assertEqual(updated.price, Decimal('45.00'))
        self.assertEqual(updated.stock_quantity, 15)

    def test_delete_category_with_products_raises_protected_error(self):
        services.create_product(
            name='Attached Drive',
            sku='DRV-001',
            category=self.category,
            price=Decimal('70.00'),
        )
        with self.assertRaises(services.ProtectedCategoryError):
            services.delete_category(self.category)


class DomainSelectorsTestCase(TestCase):
    """Tests query optimization, filters, search, and KPI calculations."""

    def setUp(self):
        self.cat1 = Category.objects.create(name='Laptops')
        self.cat2 = Category.objects.create(name='Monitors')

        self.p1 = Product.objects.create(
            name='Pro Laptop 16 inch',
            sku='LAP-PRO-16',
            category=self.cat1,
            price=Decimal('1800.00'),
            stock_quantity=15,
            reorder_level=5,
            is_active=True,
        )
        self.p2 = Product.objects.create(
            name='UltraWide 34 Monitor',
            sku='MON-UW-34',
            category=self.cat2,
            price=Decimal('600.00'),
            stock_quantity=2,
            reorder_level=5,
            is_active=True,
        )
        self.p3 = Product.objects.create(
            name='Discontinued Gaming Laptop',
            sku='LAP-DISC-01',
            category=self.cat1,
            price=Decimal('1200.00'),
            stock_quantity=0,
            reorder_level=5,
            is_active=False,
        )

        self.admin_user = User.objects.create_user(
            username='admin_test',
            email='admin@test.com',
            password='Password123!',
            role=User.Role.ADMIN,
        )
        self.standard_user = User.objects.create_user(
            username='standard_test',
            email='standard@test.com',
            password='Password123!',
            role=User.Role.STANDARD,
        )

    def test_standard_user_only_sees_active_products(self):
        qs = selectors.get_products_queryset(user=self.standard_user)
        self.assertEqual(qs.count(), 2)
        self.assertNotIn(self.p3, qs)

    def test_admin_user_sees_all_products(self):
        qs = selectors.get_products_queryset(user=self.admin_user)
        self.assertEqual(qs.count(), 3)
        self.assertIn(self.p3, qs)

    def test_search_filter_by_sku_and_name(self):
        qs = selectors.get_products_queryset(user=self.admin_user, search='MON-UW')
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first(), self.p2)

        qs_name = selectors.get_products_queryset(user=self.admin_user, search='Laptop')
        self.assertEqual(qs_name.count(), 2)

    def test_stock_status_filtering(self):
        # Low stock
        qs_low = selectors.get_products_queryset(user=self.admin_user, stock_status='low_stock')
        self.assertEqual(qs_low.count(), 1)
        self.assertEqual(qs_low.first(), self.p2)

        # Out of stock
        qs_out = selectors.get_products_queryset(user=self.admin_user, stock_status='out_of_stock')
        self.assertEqual(qs_out.count(), 1)
        self.assertEqual(qs_out.first(), self.p3)

    def test_n_plus_one_query_prevention(self):
        """Verifies select_related('category') avoids multiple SQL queries when accessing foreign key."""
        with self.assertNumQueries(1):
            products = list(selectors.get_products_queryset(user=self.admin_user))
            for p in products:
                # Accessing category.name must NOT trigger an extra query
                _ = p.category.name

    def test_inventory_kpis_calculation(self):
        kpis = selectors.get_inventory_kpis()
        self.assertEqual(kpis['total_products'], 3)
        self.assertEqual(kpis['active_products'], 2)
        self.assertEqual(kpis['low_stock_count'], 1)
        self.assertEqual(kpis['out_of_stock_count'], 1)
        self.assertEqual(kpis['total_units'], 17)


class RoleBasedAccessControlViewsTestCase(TestCase):
    """
    Verifies Role-Based Access Control (RBAC) across all Product and Category endpoints:
    - Admin: Full CRUD on Products and Categories.
    - Manager: Create, Read, Update on Products and Categories; Delete is 403 Forbidden.
    - Standard User: Read-only access to Product catalog & details; Create/Update/Delete are 403 Forbidden.
    - Anonymous: Redirected to login.
    """

    def setUp(self):
        self.client = Client()

        self.category = Category.objects.create(name='Audio Equipment')
        self.product = Product.objects.create(
            name='Noise Cancelling Headphones',
            sku='AUDIO-NC-001',
            category=self.category,
            price=Decimal('299.99'),
            stock_quantity=30,
            reorder_level=5,
            is_active=True,
        )

        self.admin = User.objects.create_user(
            username='admin_role_user',
            email='admin_role@test.com',
            password='Password123!',
            role=User.Role.ADMIN,
        )
        self.manager = User.objects.create_user(
            username='manager_role_user',
            email='manager_role@test.com',
            password='Password123!',
            role=User.Role.MANAGER,
        )
        self.standard = User.objects.create_user(
            username='standard_role_user',
            email='standard_role@test.com',
            password='Password123!',
            role=User.Role.STANDARD,
        )

    # ==========================================================================
    # 1. Anonymous Access (Must redirect to Login)
    # ==========================================================================

    def test_anonymous_redirected_from_product_list(self):
        response = self.client.get(reverse('domain_app:product_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('authentication:login'), response.url)

    def test_anonymous_redirected_from_product_create(self):
        response = self.client.get(reverse('domain_app:product_create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('authentication:login'), response.url)

    # ==========================================================================
    # 2. Standard User Access (Read-Only)
    # ==========================================================================

    def test_standard_user_can_view_product_list(self):
        self.client.force_login(self.standard)
        response = self.client.get(reverse('domain_app:product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Noise Cancelling Headphones')

    def test_standard_user_can_view_product_detail(self):
        self.client.force_login(self.standard)
        response = self.client.get(reverse('domain_app:product_detail', args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'AUDIO-NC-001')

    def test_standard_user_forbidden_from_product_create(self):
        self.client.force_login(self.standard)
        # GET form forbidden
        res_get = self.client.get(reverse('domain_app:product_create'))
        self.assertEqual(res_get.status_code, 403)

        # POST submission forbidden
        res_post = self.client.post(reverse('domain_app:product_create'), {
            'name': 'Unauthorized Product',
            'sku': 'UNAUTH-01',
            'category': self.category.id,
            'price': '10.00',
            'stock_quantity': 5,
            'reorder_level': 2,
            'is_active': True,
        })
        self.assertEqual(res_post.status_code, 403)

    def test_standard_user_forbidden_from_product_update(self):
        self.client.force_login(self.standard)
        response = self.client.post(reverse('domain_app:product_update', args=[self.product.pk]), {
            'name': 'Hacked Name',
            'sku': self.product.sku,
            'category': self.category.id,
            'price': '1.00',
            'stock_quantity': 100,
            'reorder_level': 2,
            'is_active': True,
        })
        self.assertEqual(response.status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Noise Cancelling Headphones')

    def test_standard_user_forbidden_from_product_delete(self):
        self.client.force_login(self.standard)
        response = self.client.post(reverse('domain_app:product_delete', args=[self.product.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_standard_user_forbidden_from_category_create(self):
        self.client.force_login(self.standard)
        response = self.client.post(reverse('domain_app:category_create'), {
            'name': 'Unauthorized Category',
            'is_active': True,
        })
        self.assertEqual(response.status_code, 403)

    # ==========================================================================
    # 3. Manager Access (Can Create and Update, Cannot Delete)
    # ==========================================================================

    def test_manager_can_create_product(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse('domain_app:product_create'), {
            'name': 'Studio Monitor Speakers',
            'sku': 'AUDIO-ST-002',
            'category': self.category.id,
            'price': '450.00',
            'stock_quantity': 12,
            'reorder_level': 4,
            'is_active': True,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.filter(sku='AUDIO-ST-002').exists())

    def test_manager_can_update_product(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse('domain_app:product_update', args=[self.product.pk]), {
            'name': 'Premium NC Headphones Gen 2',
            'sku': self.product.sku,
            'category': self.category.id,
            'price': '349.99',
            'stock_quantity': 28,
            'reorder_level': 5,
            'is_active': True,
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Premium NC Headphones Gen 2')
        self.assertEqual(self.product.price, Decimal('349.99'))

    def test_manager_forbidden_from_product_delete(self):
        """Managers are strictly forbidden from permanently deleting products."""
        self.client.force_login(self.manager)
        res_get = self.client.get(reverse('domain_app:product_delete', args=[self.product.pk]))
        self.assertEqual(res_get.status_code, 403)

        res_post = self.client.post(reverse('domain_app:product_delete', args=[self.product.pk]))
        self.assertEqual(res_post.status_code, 403)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_manager_forbidden_from_category_delete(self):
        """Managers are strictly forbidden from deleting categories."""
        empty_cat = Category.objects.create(name='Empty Category for Test')
        self.client.force_login(self.manager)
        response = self.client.post(reverse('domain_app:category_delete', args=[empty_cat.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Category.objects.filter(pk=empty_cat.pk).exists())

    # ==========================================================================
    # 4. Admin Access (Full System Management)
    # ==========================================================================

    def test_admin_can_manage_and_delete_product(self):
        self.client.force_login(self.admin)
        prod = Product.objects.create(
            name='Product to Delete',
            sku='DEL-SKU-99',
            category=self.category,
            price=Decimal('15.00'),
            stock_quantity=1,
        )
        response = self.client.post(reverse('domain_app:product_delete', args=[prod.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.filter(pk=prod.pk).exists())

    def test_admin_can_delete_empty_category(self):
        self.client.force_login(self.admin)
        empty_cat = Category.objects.create(name='Obsolete Taxonomy')
        response = self.client.post(reverse('domain_app:category_delete', args=[empty_cat.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Category.objects.filter(pk=empty_cat.pk).exists())

    def test_admin_deleting_category_with_products_shows_warning_and_preserves_db(self):
        self.client.force_login(self.admin)
        # Attempting to delete self.category which contains self.product
        response = self.client.post(reverse('domain_app:category_delete', args=[self.category.pk]))
        self.assertEqual(response.status_code, 302)
        # Category must still exist due to ProtectedCategoryError
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())


class SupplierModelAndRelationshipTestCase(TestCase):
    """
    Verifies Supplier model normalization, constraints, validation,
    and direct ForeignKey relationship from Product to Supplier (models.SET_NULL).
    """

    def setUp(self):
        self.category = Category.objects.create(name='Components & ICs')
        self.supplier = Supplier.objects.create(
            name='Global Silicon Tech',
            contact_person='Alice Cooper',
            email='alice@globalsilicon.com',
            phone='+1 (555) 123-4567',
            address='100 Silicon Blvd, San Jose, CA',
            is_active=True,
        )

    def test_supplier_creation_and_attributes(self):
        self.assertEqual(self.supplier.name, 'Global Silicon Tech')
        self.assertEqual(self.supplier.contact_person, 'Alice Cooper')
        self.assertEqual(self.supplier.email, 'alice@globalsilicon.com')
        self.assertEqual(self.supplier.phone, '+1 (555) 123-4567')
        self.assertTrue(self.supplier.is_active)
        self.assertEqual(str(self.supplier), 'Global Silicon Tech')

    def test_supplier_email_normalization_and_validation(self):
        # Email is automatically lowercased and stripped
        supp = Supplier(
            name='Normalized Tech',
            email='  TEST@Domain.COM  ',
            phone='123456',
        )
        supp.save()
        self.assertEqual(supp.email, 'test@domain.com')

    def test_supplier_invalid_email_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            supp = Supplier(
                name='Invalid Email Vendor',
                email='not-an-email',
                phone='123456',
            )
            supp.full_clean()
            supp.save()

    def test_supplier_empty_name_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            supp = Supplier(
                name='   ',
                email='valid@email.com',
                phone='123456',
            )
            supp.full_clean()
            supp.save()

    def test_link_product_to_supplier_foreign_key(self):
        product = Product.objects.create(
            name='Microcontroller Unit 32-bit',
            sku='MCU-32-001',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('5.50'),
            stock_quantity=500,
        )
        self.assertEqual(product.supplier, self.supplier)
        self.assertIn(product, self.supplier.products.all())
        self.assertEqual(self.supplier.products.count(), 1)

    def test_deleting_supplier_sets_product_supplier_to_null(self):
        """
        Academic Defense Highlight:
        Verifies `on_delete=models.SET_NULL` preserves inventory SKUs while decoupling deleted suppliers.
        """
        product = Product.objects.create(
            name='Capacitor 100uF',
            sku='CAP-100UF-01',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('0.25'),
            stock_quantity=1000,
        )
        self.assertEqual(product.supplier_id, self.supplier.id)

        # Delete supplier
        self.supplier.delete()

        # Product must remain intact, supplier set to NULL
        product.refresh_from_db()
        self.assertIsNone(product.supplier)
        self.assertIsNone(product.supplier_id)
        self.assertTrue(Product.objects.filter(sku='CAP-100UF-01').exists())


class SupplierServicesAndSelectorsTestCase(TestCase):
    """
    Tests Supplier domain services and selectors.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            username='supplier_admin',
            email='sadmin@test.com',
            password='Password123!',
            role=User.Role.ADMIN,
        )
        self.standard = User.objects.create_user(
            username='supplier_std',
            email='sstd@test.com',
            password='Password123!',
            role=User.Role.STANDARD,
        )
        self.active_supp = services.create_supplier(
            name='Alpha Industrial Corp',
            contact_person='Bob Vance',
            email='bob@alphaind.com',
            phone='555-0101',
            address='Scranton, PA',
            is_active=True,
        )
        self.inactive_supp = services.create_supplier(
            name='Omega Liquidators',
            contact_person='Zoe Washburne',
            email='zoe@omegaliquid.com',
            phone='555-0199',
            is_active=False,
        )

    def test_create_supplier_service(self):
        supp = services.create_supplier(
            name='Beta Manufacturing',
            contact_person='Charlie Day',
            email='charlie@paddys.com',
            phone='555-0123',
        )
        self.assertEqual(supp.name, 'Beta Manufacturing')
        self.assertEqual(supp.email, 'charlie@paddys.com')
        self.assertTrue(supp.is_active)

    def test_update_supplier_service(self):
        updated = services.update_supplier(
            self.active_supp,
            name='Alpha Industrial Global',
            phone='555-9999',
        )
        self.assertEqual(updated.name, 'Alpha Industrial Global')
        self.assertEqual(updated.phone, '555-9999')

    def test_delete_supplier_service(self):
        pk = self.active_supp.pk
        services.delete_supplier(self.active_supp)
        self.assertFalse(Supplier.objects.filter(pk=pk).exists())

    def test_standard_user_only_sees_active_suppliers(self):
        qs = selectors.get_suppliers_queryset(user=self.standard)
        self.assertEqual(qs.count(), 1)
        self.assertIn(self.active_supp, qs)
        self.assertNotIn(self.inactive_supp, qs)

    def test_admin_user_sees_all_suppliers(self):
        qs = selectors.get_suppliers_queryset(user=self.admin)
        self.assertEqual(qs.count(), 2)
        self.assertIn(self.inactive_supp, qs)

    def test_supplier_search_filter(self):
        qs_name = selectors.get_suppliers_queryset(user=self.admin, search='Alpha')
        self.assertEqual(qs_name.count(), 1)
        self.assertEqual(qs_name.first(), self.active_supp)

        qs_email = selectors.get_suppliers_queryset(user=self.admin, search='omegaliquid')
        self.assertEqual(qs_email.count(), 1)
        self.assertEqual(qs_email.first(), self.inactive_supp)

    def test_supplier_kpis(self):
        kpis = selectors.get_supplier_kpis()
        self.assertEqual(kpis['total_suppliers'], 2)
        self.assertEqual(kpis['active_suppliers'], 1)
        self.assertEqual(kpis['inactive_suppliers'], 1)


class SupplierFormsTestCase(TestCase):
    """
    Tests validation and behavior of SupplierForm and SupplierFilterForm.
    """

    def test_valid_supplier_form(self):
        form = SupplierForm(data={
            'name': 'Valid Supplier Inc',
            'contact_person': 'Jane Doe',
            'email': 'jane@validsupplier.com',
            'phone': '+1 800 555 1234',
            'address': '123 Enterprise Way',
            'is_active': True,
        })
        self.assertTrue(form.is_valid())

    def test_invalid_email_in_form(self):
        form = SupplierForm(data={
            'name': 'Invalid Email Co',
            'email': 'bad-email-format',
            'phone': '555-1234',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_empty_required_fields_in_form(self):
        form = SupplierForm(data={
            'name': '',
            'email': '',
            'phone': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)
        self.assertIn('email', form.errors)
        self.assertIn('phone', form.errors)


class SupplierRBACViewsTestCase(TestCase):
    """
    Verifies Role-Based Access Control (RBAC) across all Supplier endpoints:
    - Admin: Full CRUD on Suppliers.
    - Manager: Full CRUD on Suppliers (Create, Read, Update, Delete per prompt requirement).
    - Standard User: Read-only access to Supplier list and detail; Create/Update/Delete are 403 Forbidden.
    - Anonymous: Redirected to login.
    """

    def setUp(self):
        self.client = Client()
        self.supplier = Supplier.objects.create(
            name='Precision Instruments Ltd',
            contact_person='Dr. Marcus',
            email='marcus@precision.com',
            phone='555-4321',
            is_active=True,
        )
        self.admin = User.objects.create_user(
            username='supp_admin',
            email='sadmin2@test.com',
            password='Password123!',
            role=User.Role.ADMIN,
        )
        self.manager = User.objects.create_user(
            username='supp_manager',
            email='smanager2@test.com',
            password='Password123!',
            role=User.Role.MANAGER,
        )
        self.standard = User.objects.create_user(
            username='supp_standard',
            email='sstandard2@test.com',
            password='Password123!',
            role=User.Role.STANDARD,
        )

    # 1. Anonymous Access
    def test_anonymous_redirected_from_supplier_list(self):
        response = self.client.get(reverse('domain_app:supplier_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('authentication:login'), response.url)

    def test_anonymous_redirected_from_supplier_create(self):
        response = self.client.get(reverse('domain_app:supplier_create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('authentication:login'), response.url)

    # 2. Standard User Access (Read-Only)
    def test_standard_user_can_view_supplier_list(self):
        self.client.force_login(self.standard)
        response = self.client.get(reverse('domain_app:supplier_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Precision Instruments Ltd')

    def test_standard_user_can_view_supplier_detail(self):
        self.client.force_login(self.standard)
        response = self.client.get(reverse('domain_app:supplier_detail', args=[self.supplier.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'marcus@precision.com')

    def test_standard_user_forbidden_from_supplier_create(self):
        self.client.force_login(self.standard)
        res_get = self.client.get(reverse('domain_app:supplier_create'))
        self.assertEqual(res_get.status_code, 403)

        res_post = self.client.post(reverse('domain_app:supplier_create'), {
            'name': 'Unauthorized Supplier',
            'email': 'unauth@test.com',
            'phone': '555-0000',
            'is_active': True,
        })
        self.assertEqual(res_post.status_code, 403)

    def test_standard_user_forbidden_from_supplier_update(self):
        self.client.force_login(self.standard)
        response = self.client.post(reverse('domain_app:supplier_update', args=[self.supplier.pk]), {
            'name': 'Hacked Supplier Name',
            'email': self.supplier.email,
            'phone': self.supplier.phone,
            'is_active': True,
        })
        self.assertEqual(response.status_code, 403)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.name, 'Precision Instruments Ltd')

    def test_standard_user_forbidden_from_supplier_delete(self):
        self.client.force_login(self.standard)
        response = self.client.post(reverse('domain_app:supplier_delete', args=[self.supplier.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Supplier.objects.filter(pk=self.supplier.pk).exists())

    # 3. Manager Access (Can Create, Update, and Delete per prompt RBAC requirement)
    def test_manager_can_create_supplier(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse('domain_app:supplier_create'), {
            'name': 'Manager Created Supplier',
            'contact_person': 'Tom Hagen',
            'email': 'tom@corleone.com',
            'phone': '555-7777',
            'address': 'Long Beach, NY',
            'is_active': True,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Supplier.objects.filter(name='Manager Created Supplier').exists())

    def test_manager_can_update_supplier(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse('domain_app:supplier_update', args=[self.supplier.pk]), {
            'name': 'Precision Instruments Worldwide',
            'contact_person': 'Dr. Marcus',
            'email': 'marcus@precision-global.com',
            'phone': '555-4321',
            'is_active': True,
        })
        self.assertEqual(response.status_code, 302)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.name, 'Precision Instruments Worldwide')
        self.assertEqual(self.supplier.email, 'marcus@precision-global.com')

    def test_manager_can_delete_supplier(self):
        self.client.force_login(self.manager)
        supp_to_delete = Supplier.objects.create(
            name='Temporary Supplier for Delete',
            email='temp@delete.com',
            phone='555-9876',
            is_active=True,
        )
        response = self.client.post(reverse('domain_app:supplier_delete', args=[supp_to_delete.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Supplier.objects.filter(pk=supp_to_delete.pk).exists())

    # 4. Admin Access (Full Management)
    def test_admin_can_manage_and_delete_supplier(self):
        self.client.force_login(self.admin)
        supp_to_delete = Supplier.objects.create(
            name='Admin Deletable Supplier',
            email='admin_del@test.com',
            phone='555-4444',
            is_active=True,
        )
        response = self.client.post(reverse('domain_app:supplier_delete', args=[supp_to_delete.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Supplier.objects.filter(pk=supp_to_delete.pk).exists())


# ==============================================================================
# Inventory & Low-Stock Module Test Suite
# ==============================================================================

class InventoryModelAndTrackingTestCase(TestCase):
    """Verifies target stock level field, InventoryTransaction model, and constraints."""

    def setUp(self):
        self.category = Category.objects.create(name='Storage Devices')
        self.supplier = Supplier.objects.create(name='Western Digital Corp', email='orders@wdc.com', phone='555-1234')

    def test_product_target_stock_level_attribute_and_validation(self):
        product = Product.objects.create(
            name='1TB NVMe SSD',
            sku='SSD-NVME-1TB',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('89.99'),
            stock_quantity=15,
            reorder_level=5,
            target_stock_level=50,
        )
        self.assertEqual(product.target_stock_level, 50)

        # Validation rejects negative target stock level
        product.target_stock_level = -5
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_inventory_transaction_creation_and_string_representation(self):
        product = Product.objects.create(
            name='2TB External HDD',
            sku='HDD-EXT-2TB',
            category=self.category,
            price=Decimal('69.99'),
            stock_quantity=20,
        )
        tx = InventoryTransaction.objects.create(
            product=product,
            transaction_type=InventoryTransaction.TransactionType.ADD,
            quantity=10,
            previous_stock=10,
            new_stock=20,
            reference='PO-2026-001',
            notes='Shipment received.',
        )
        self.assertEqual(tx.transaction_type, 'ADD')
        self.assertEqual(tx.quantity, 10)
        self.assertEqual(tx.previous_stock, 10)
        self.assertEqual(tx.new_stock, 20)
        self.assertIn('Stock Added: 10 units for HDD-EXT-2TB', str(tx))

    def test_inventory_transaction_negative_constraints(self):
        product = Product.objects.create(
            name='Flash Drive 64GB',
            sku='USB-64GB-01',
            category=self.category,
            price=Decimal('9.99'),
            stock_quantity=5,
        )
        tx_valid = InventoryTransaction(
            product=product,
            transaction_type='ADD',
            quantity=0,
            previous_stock=5,
            new_stock=5,
        )
        tx_valid.clean()

        tx_neg = InventoryTransaction(
            product=product,
            transaction_type='REMOVE',
            quantity=-1,
            previous_stock=5,
            new_stock=4,
        )
        with self.assertRaises(ValidationError):
            tx_neg.full_clean()


class InventoryServiceStockMovementsTestCase(TestCase):
    """Verifies atomic stock movements: ADD, REMOVE, ADJUSTMENT, and business rules."""

    def setUp(self):
        self.category = Category.objects.create(name='Monitors & Screens')
        self.user = User.objects.create_user(
            username='inv_manager',
            email='inv_mgr@test.com',
            password='password123',
            role=User.Role.MANAGER,
        )
        self.product = services.create_product(
            name='27-inch 4K IPS Monitor',
            sku='MON-4K-27',
            category=self.category,
            price=Decimal('349.99'),
            stock_quantity=20,
            reorder_level=5,
            target_stock_level=40,
            created_by=self.user,
        )

    def test_initial_stock_transaction_recorded(self):
        # Because product was created with stock_quantity=20, an initial transaction must exist
        tx = InventoryTransaction.objects.filter(product=self.product).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.transaction_type, 'ADD')
        self.assertEqual(tx.quantity, 20)
        self.assertEqual(tx.previous_stock, 0)
        self.assertEqual(tx.new_stock, 20)
        self.assertEqual(tx.reference, 'INITIAL-STOCK')

    def test_add_stock_success(self):
        tx = services.add_stock(
            product=self.product,
            quantity=15,
            user=self.user,
            reference='PO-REPLENISH-101',
            notes='Restocked from central distributor.',
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 35)
        self.assertEqual(tx.transaction_type, 'ADD')
        self.assertEqual(tx.quantity, 15)
        self.assertEqual(tx.previous_stock, 20)
        self.assertEqual(tx.new_stock, 35)
        self.assertEqual(tx.created_by, self.user)

    def test_add_stock_rejects_non_positive_quantity(self):
        with self.assertRaises(ValidationError):
            services.add_stock(product=self.product, quantity=0)

        with self.assertRaises(ValidationError):
            services.add_stock(product=self.product, quantity=-5)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)

    def test_remove_stock_success(self):
        tx = services.remove_stock(
            product=self.product,
            quantity=8,
            user=self.user,
            reference='INV-DISPATCH-55',
            notes='Customer fulfillment.',
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 12)
        self.assertEqual(tx.transaction_type, 'REMOVE')
        self.assertEqual(tx.quantity, 8)
        self.assertEqual(tx.previous_stock, 20)
        self.assertEqual(tx.new_stock, 12)

    def test_remove_stock_insufficient_stock_prevents_negative(self):
        # Product has 20 units; attempting to remove 25 must fail
        with self.assertRaises(InsufficientStockError) as ctx:
            services.remove_stock(
                product=self.product,
                quantity=25,
                user=self.user,
                reference='ORDER-TOO-BIG',
            )

        self.assertIn("Insufficient stock", str(ctx.exception))
        # Verify atomic rollback: product stock remains unchanged
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)
        # Verify no failed transaction recorded
        self.assertFalse(InventoryTransaction.objects.filter(reference='ORDER-TOO-BIG').exists())

    def test_adjust_stock_success(self):
        tx = services.adjust_stock(
            product=self.product,
            new_quantity=18,
            user=self.user,
            reference='AUDIT-Q3-2026',
            notes='Discrepancy resolved during cycle count.',
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 18)
        self.assertEqual(tx.transaction_type, 'ADJUSTMENT')
        self.assertEqual(tx.previous_stock, 20)
        self.assertEqual(tx.new_stock, 18)
        self.assertEqual(tx.quantity, 2)

    def test_adjust_stock_rejects_negative_new_stock(self):
        with self.assertRaises(InvalidStockAdjustmentError):
            services.adjust_stock(
                product=self.product,
                new_quantity=-10,
                user=self.user,
            )

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)

    def test_database_check_constraint_prevents_negative_stock(self):
        # Directly attempting to bypass services and save negative stock fails at DB level
        self.product.stock_quantity = -5
        with self.assertRaises((IntegrityError, ValidationError)):
            self.product.save()


class LowStockDetectionAndSelectorTestCase(TestCase):
    """Verifies low-stock detection business rule and reusable AI Agent selectors."""

    def setUp(self):
        self.category = Category.objects.create(name='Networking & Cables')
        self.supplier = Supplier.objects.create(
            name='Cisco Systems Distribution',
            email='procure@cisco-dist.com',
            phone='555-8888',
        )

        # In-stock product (15 > 5)
        self.p_in = Product.objects.create(
            name='Gigabit Ethernet Cable 5m',
            sku='NET-CAT6-5M',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('12.99'),
            stock_quantity=15,
            reorder_level=5,
            target_stock_level=30,
        )

        # Low-stock product: current quantity == reorder_level (5 == 5)
        self.p_exact = Product.objects.create(
            name='Managed Switch 8-Port',
            sku='NET-SW-8P',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('89.99'),
            stock_quantity=5,
            reorder_level=5,
            target_stock_level=20,
        )

        # Low-stock product: current quantity < reorder_level (2 < 5)
        self.p_below = Product.objects.create(
            name='WiFi 6 Router',
            sku='NET-RT-AX',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('129.99'),
            stock_quantity=2,
            reorder_level=5,
            target_stock_level=15,
        )

        # Out-of-stock product: current quantity == 0 (0 <= 5)
        self.p_out = Product.objects.create(
            name='Fiber Optic Patch 1m',
            sku='NET-FO-1M',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('24.99'),
            stock_quantity=0,
            reorder_level=5,
            target_stock_level=25,
        )

    def test_low_stock_detection_business_rules(self):
        # 1. Product with stock > reorder_level is NOT low stock
        self.assertFalse(self.p_in.is_low_stock)
        self.assertEqual(self.p_in.stock_status, 'in_stock')

        # 2. Product with stock == reorder_level IS low stock
        self.assertTrue(self.p_exact.is_low_stock)
        self.assertEqual(self.p_exact.stock_status, 'low_stock')

        # 3. Product with stock < reorder_level IS low stock
        self.assertTrue(self.p_below.is_low_stock)
        self.assertEqual(self.p_below.stock_status, 'low_stock')

        # 4. Product with stock == 0 IS low stock and out of stock
        self.assertTrue(self.p_out.is_low_stock)
        self.assertTrue(self.p_out.is_out_of_stock)
        self.assertEqual(self.p_out.stock_status, 'out_of_stock')

    def test_get_low_stock_products_selector(self):
        # Default (include_out_of_stock=True): returns exact, below, and out
        low_stock_qs = selectors.get_low_stock_products(include_out_of_stock=True)
        skus = list(low_stock_qs.values_list('sku', flat=True))
        self.assertIn('NET-SW-8P', skus)
        self.assertIn('NET-RT-AX', skus)
        self.assertIn('NET-FO-1M', skus)
        self.assertNotIn('NET-CAT6-5M', skus)
        self.assertEqual(len(skus), 3)

        # Excluding out-of-stock
        strictly_low = selectors.get_low_stock_products(include_out_of_stock=False)
        strictly_skus = list(strictly_low.values_list('sku', flat=True))
        self.assertIn('NET-SW-8P', strictly_skus)
        self.assertIn('NET-RT-AX', strictly_skus)
        self.assertNotIn('NET-FO-1M', strictly_skus)
        self.assertEqual(len(strictly_skus), 2)

    def test_get_out_of_stock_products_selector(self):
        out_qs = selectors.get_out_of_stock_products()
        self.assertEqual(out_qs.count(), 1)
        self.assertEqual(out_qs.first().sku, 'NET-FO-1M')

    def test_get_low_stock_report_for_ai_agent(self):
        report = selectors.get_low_stock_report()
        self.assertEqual(len(report), 3)

        # Verify structured dictionary schema for AI Agent
        item_out = next(item for item in report if item['sku'] == 'NET-FO-1M')
        self.assertEqual(item_out['current_stock'], 0)
        self.assertEqual(item_out['reorder_level'], 5)
        self.assertEqual(item_out['target_stock_level'], 25)
        self.assertEqual(item_out['deficit_to_reorder'], 5)
        self.assertEqual(item_out['deficit_to_target'], 25)
        self.assertEqual(item_out['urgency'], 'CRITICAL')
        self.assertEqual(item_out['supplier_name'], 'Cisco Systems Distribution')
        self.assertEqual(item_out['supplier_email'], 'procure@cisco-dist.com')

        item_below = next(item for item in report if item['sku'] == 'NET-RT-AX')
        self.assertEqual(item_below['current_stock'], 2)
        self.assertEqual(item_below['deficit_to_reorder'], 3)
        self.assertEqual(item_below['deficit_to_target'], 13)
        self.assertEqual(item_below['urgency'], 'HIGH')

    def test_get_inventory_kpis(self):
        kpis = selectors.get_inventory_kpis()
        self.assertEqual(kpis['total_products'], 4)
        self.assertEqual(kpis['total_units'], 22) # 15 + 5 + 2 + 0
        self.assertEqual(kpis['out_of_stock_count'], 1) # p_out
        self.assertEqual(kpis['low_stock_count'], 2) # p_exact, p_below
        self.assertEqual(kpis['total_reorder_needed'], 3) # p_exact, p_below, p_out


class InventoryViewsAndRBACTestCase(TestCase):
    """Verifies HTTP responses, RBAC protection, and AJAX stock operations."""

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Printers & Toner')
        self.product = Product.objects.create(
            name='LaserJet Pro Multifunction',
            sku='PRN-LJ-100',
            category=self.category,
            price=Decimal('299.99'),
            stock_quantity=8,
            reorder_level=5,
            target_stock_level=20,
            is_active=True,
        )

        self.standard_user = User.objects.create_user(
            username='user_regular',
            email='user@test.com',
            password='Password123!',
            role=User.Role.STANDARD,
        )
        self.manager = User.objects.create_user(
            username='mgr_stock',
            email='manager@test.com',
            password='Password123!',
            role=User.Role.MANAGER,
        )
        self.admin = User.objects.create_user(
            username='admin_boss',
            email='admin@test.com',
            password='Password123!',
            role=User.Role.ADMIN,
        )

    def test_anonymous_redirected_to_login(self):
        endpoints = [
            reverse('domain_app:inventory_dashboard'),
            reverse('domain_app:low_stock_list'),
            reverse('domain_app:inventory_transactions'),
            reverse('domain_app:product_stock_adjustment', args=[self.product.pk]),
            reverse('domain_app:api_low_stock'),
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, f"Failed for {url}")
            self.assertIn('/auth/login/', response.url)

    def test_standard_user_can_view_inventory_hubs(self):
        self.client.force_login(self.standard_user)
        # Dashboard view (200 OK)
        res_dash = self.client.get(reverse('domain_app:inventory_dashboard'))
        self.assertEqual(res_dash.status_code, 200)

        # Low stock view (200 OK)
        res_low = self.client.get(reverse('domain_app:low_stock_list'))
        self.assertEqual(res_low.status_code, 200)

        # Transactions ledger (200 OK)
        res_tx = self.client.get(reverse('domain_app:inventory_transactions'))
        self.assertEqual(res_tx.status_code, 200)

        # JSON low stock API (200 OK)
        res_api = self.client.get(reverse('domain_app:api_low_stock'))
        self.assertEqual(res_api.status_code, 200)
        data = res_api.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('kpis', data)

    def test_standard_user_forbidden_from_stock_adjustment(self):
        self.client.force_login(self.standard_user)
        url = reverse('domain_app:product_stock_adjustment', args=[self.product.pk])
        # GET should be forbidden
        res_get = self.client.get(url)
        self.assertEqual(res_get.status_code, 403)

        # POST should be forbidden
        res_post = self.client.post(url, {
            'transaction_type': 'ADD',
            'quantity': 10,
        })
        self.assertEqual(res_post.status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)

    def test_manager_can_adjust_stock_form_post(self):
        self.client.force_login(self.manager)
        url = reverse('domain_app:product_stock_adjustment', args=[self.product.pk])
        response = self.client.post(url, {
            'transaction_type': 'ADD',
            'quantity': 12,
            'reference': 'RESTOCK-MGR-01',
            'notes': 'Added by warehouse manager.',
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)

        # Verify transaction logged
        tx = InventoryTransaction.objects.filter(reference='RESTOCK-MGR-01').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.created_by, self.manager)

    def test_manager_ajax_stock_adjustment_json_response(self):
        self.client.force_login(self.manager)
        url = reverse('domain_app:product_stock_adjustment', args=[self.product.pk])
        response = self.client.post(
            url,
            data={
                'transaction_type': 'REMOVE',
                'quantity': 3,
                'reference': 'INV-AJAX-01',
                'notes': 'Dispatched.',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['new_stock'], 5)
        self.assertEqual(data['stock_status'], 'low_stock') # 5 <= reorder_level 5
        self.assertTrue(data['is_low_stock'])

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)

    def test_manager_ajax_stock_removal_insufficient_error(self):
        self.client.force_login(self.manager)
        url = reverse('domain_app:product_stock_adjustment', args=[self.product.pk])
        response = self.client.post(
            url,
            data={
                'transaction_type': 'REMOVE',
                'quantity': 500, # product only has 8 units
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn("Insufficient stock", data['message'])

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)

    def test_admin_can_adjust_stock(self):
        self.client.force_login(self.admin)
        url = reverse('domain_app:product_stock_adjustment', args=[self.product.pk])
        response = self.client.post(url, {
            'transaction_type': 'ADJUSTMENT',
            'quantity': 42,
            'reference': 'ANNUAL-AUDIT',
            'notes': 'Admin physical count alignment.',
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 42)


class InventoryDashboardPolishTests(TestCase):
    """
    Unit and integration tests for the polished Inventory Dashboard.
    Validates O(1) KPI queries, attention logic, RBAC visibility, and template context.
    """

    def setUp(self):
        self.category = Category.objects.create(name='Computing Hardware', slug='computing-hardware')
        self.supplier = Supplier.objects.create(
            name='Apex Systems',
            email='sales@apex.com',
            phone='+1-555-0100',
        )

        # Diverse products in different inventory health states
        self.p_instock = Product.objects.create(
            name='Enterprise Server Blade',
            sku='SRV-BLADE-01',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('1200.00'),
            stock_quantity=50,
            reorder_level=10,
            target_stock_level=80,
            is_active=True,
        )
        self.p_lowstock = Product.objects.create(
            name='Dual Port 10GbE NIC',
            sku='NIC-10G-02',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('180.00'),
            stock_quantity=3,
            reorder_level=8,
            target_stock_level=20,
            is_active=True,
        )
        self.p_outofstock = Product.objects.create(
            name='Hot Swap Power Supply 850W',
            sku='PSU-850-HS',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('220.00'),
            stock_quantity=0,
            reorder_level=5,
            target_stock_level=15,
            is_active=True,
        )
        self.p_inactive_stock = Product.objects.create(
            name='Legacy SAS Controller',
            sku='SAS-CTRL-OLD',
            category=self.category,
            supplier=self.supplier,
            price=Decimal('50.00'),
            stock_quantity=12,
            reorder_level=4,
            is_active=False,
        )

        # Users
        self.admin = User.objects.create_user(
            username='admin_inventory',
            email='admin@nexus.com',
            password='Password123!',
            role=User.Role.ADMIN,
        )
        self.standard_user = User.objects.create_user(
            username='standard_staff',
            email='staff@nexus.com',
            password='Password123!',
            role=User.Role.STANDARD,
        )

        # Record a stock movement
        InventoryTransaction.objects.create(
            product=self.p_instock,
            transaction_type=InventoryTransaction.TransactionType.ADD,
            quantity=20,
            previous_stock=30,
            new_stock=50,
            reference='PO-2026-TEST',
            notes='Initial intake verification',
            created_by=self.admin,
        )

    def test_kpi_aggregation_rbac_and_accuracy(self):
        """KPIs correctly aggregate counts and valuations, separating standard and elevated views."""
        admin_kpis = selectors.get_inventory_kpis(user=self.admin)
        self.assertEqual(admin_kpis['total_products'], 4)
        self.assertEqual(admin_kpis['active_products'], 3)
        self.assertEqual(admin_kpis['low_stock_count'], 1)
        self.assertEqual(admin_kpis['out_of_stock_count'], 1)
        self.assertEqual(admin_kpis['attention_count'], 3)  # low stock + out of stock + inactive with stock
        self.assertEqual(admin_kpis['total_stock'], 65)     # 50 + 3 + 0 + 12
        self.assertEqual(admin_kpis['total_units'], 65)

        standard_kpis = selectors.get_inventory_kpis(user=self.standard_user)
        self.assertEqual(standard_kpis['total_products'], 3) # inactive excluded
        self.assertEqual(standard_kpis['attention_count'], 2) # low stock + out of stock
        self.assertEqual(standard_kpis['total_stock'], 53)    # 50 + 3 + 0 (excludes 12 inactive)

    def test_products_requiring_attention_selector(self):
        """Attention selector correctly assigns severity, deficits, and obeys RBAC."""
        # Standard user attention list
        std_attention = selectors.get_products_requiring_attention(user=self.standard_user)
        self.assertEqual(len(std_attention), 2)
        std_skus = [x['sku'] for x in std_attention]
        self.assertIn('PSU-850-HS', std_skus)
        self.assertIn('NIC-10G-02', std_skus)
        self.assertNotIn('SAS-CTRL-OLD', std_skus)

        # Admin attention list
        adm_attention = selectors.get_products_requiring_attention(user=self.admin)
        self.assertEqual(len(adm_attention), 3)
        adm_skus = [x['sku'] for x in adm_attention]
        self.assertIn('SAS-CTRL-OLD', adm_skus)

        # Verify urgency and deficit calculations
        out_item = next(x for x in adm_attention if x['sku'] == 'PSU-850-HS')
        self.assertEqual(out_item['urgency'], 'CRITICAL')
        self.assertEqual(out_item['deficit_to_reorder'], 5)

        low_item = next(x for x in adm_attention if x['sku'] == 'NIC-10G-02')
        self.assertEqual(low_item['urgency'], 'WARNING')
        self.assertEqual(low_item['deficit_to_reorder'], 5)  # 8 - 3

        audit_item = next(x for x in adm_attention if x['sku'] == 'SAS-CTRL-OLD')
        self.assertEqual(audit_item['urgency'], 'AUDIT')

    def test_inventory_dashboard_view_authenticated(self):
        """Dashboard renders HTTP 200 with complete context and respects user permissions."""
        self.client.force_login(self.standard_user)
        response = self.client.get(reverse('domain_app:inventory_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Verify context contents
        self.assertIn('kpis', response.context)
        self.assertIn('attention_items', response.context)
        self.assertIn('recent_transactions', response.context)
        self.assertIn('products', response.context)

        # Standard user should not see Add Product button or stock adjustment modal
        self.assertNotContains(response, '⚡ Restock')
        self.assertNotContains(response, 'id="stockAdjustmentModal"')

        # Login as admin
        self.client.force_login(self.admin)
        admin_response = self.client.get(reverse('domain_app:inventory_dashboard'))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, '⚡ Restock')
        self.assertContains(admin_response, 'id="stockAdjustmentModal"')

    def test_filter_by_attention_status(self):
        """Filtering by stock_status=attention returns only products needing attention."""
        self.client.force_login(self.admin)
        response = self.client.get(reverse('domain_app:inventory_dashboard') + '?stock_status=attention')
        self.assertEqual(response.status_code, 200)
        products = response.context['products']
        skus = [p.sku for p in products]
        self.assertIn('PSU-850-HS', skus)
        self.assertIn('NIC-10G-02', skus)
        self.assertNotIn('SRV-BLADE-01', skus)


# ==============================================================================
# Sales Management Module Test Suite
# ==============================================================================

class SalesManagementTestCase(TestCase):
    """
    Comprehensive test coverage for the Sales Management module:
    1. Normalized Models, Foreign Keys, Subtotal Calculations, PROTECT deletion.
    2. Atomic Sale Creation Service with row-locking and backend total calculations.
    3. Stock Availability Validation preventing negative stock states.
    4. Inventory Decrement and linked InventoryTransaction audit logging.
    5. Duplicate line item consolidation enforcement.
    6. Role-Based Access Control (RBAC) and Views.
    """

    def setUp(self):
        self.client = Client()

        # Users with distinct RBAC roles
        self.admin = User.objects.create_user(
            username='admin_sales_test',
            email='adminsales@test.com',
            password='Password123!',
            role=User.Role.ADMIN,
        )
        self.manager = User.objects.create_user(
            username='manager_sales_test',
            email='managersales@test.com',
            password='Password123!',
            role=User.Role.MANAGER,
        )
        self.standard = User.objects.create_user(
            username='standard_sales_test',
            email='standardsales@test.com',
            password='Password123!',
            role=User.Role.STANDARD,
        )

        # Category and Products
        self.category = Category.objects.create(
            name='Enterprise Storage',
            description='Enterprise SSD and NVMe drives',
        )

        self.product_nvme = Product.objects.create(
            name='Enterprise NVMe SSD 2TB',
            sku='SSD-NVME-2TB',
            category=self.category,
            price=Decimal('250.00'),
            stock_quantity=20,
            reorder_level=5,
            is_active=True,
        )

        self.product_sata = Product.objects.create(
            name='Data Center SATA SSD 1TB',
            sku='SSD-SATA-1TB',
            category=self.category,
            price=Decimal('100.00'),
            stock_quantity=5,
            reorder_level=2,
            is_active=True,
        )

        self.inactive_product = Product.objects.create(
            name='Legacy Hard Drive 500GB',
            sku='HDD-LEGACY-500',
            category=self.category,
            price=Decimal('40.00'),
            stock_quantity=15,
            reorder_level=2,
            is_active=False,
        )

    # --------------------------------------------------------------------------
    # 1. Model Constraints & Foreign Key Integrity
    # --------------------------------------------------------------------------

    def test_sale_and_sale_item_models_creation(self):
        """Verifies Sale and SaleItem persistence, subtotal calculation, and helper properties."""
        from django.utils import timezone

        sale = Sale.objects.create(
            order_identifier='SALE-20260918-001',
            customer_name='Acme Cloud Infrastructure',
            customer_email='billing@acmecloud.com',
            customer_phone='+1 555-0199',
            sale_date=timezone.now(),
            status=Sale.Status.COMPLETED,
            total_amount=Decimal('500.00'),
            created_by=self.admin,
        )

        item = SaleItem.objects.create(
            sale=sale,
            product=self.product_nvme,
            quantity=2,
            unit_price=Decimal('250.00'),
        )

        self.assertEqual(item.subtotal, Decimal('500.00'))
        self.assertEqual(sale.total_items_count, 2)
        self.assertIn('Acme Cloud Infrastructure', str(sale))
        self.assertIn('Enterprise NVMe SSD 2TB', str(item))

    def test_unique_product_per_sale_constraint(self):
        """Database constraint prevents duplicate line items for the same product in a sale."""
        from django.utils import timezone

        sale = Sale.objects.create(
            order_identifier='SALE-20260918-UNIQUE',
            customer_name='Unique Test Corp',
            sale_date=timezone.now(),
            status=Sale.Status.COMPLETED,
            total_amount=Decimal('500.00'),
        )

        SaleItem.objects.create(
            sale=sale,
            product=self.product_nvme,
            quantity=1,
            unit_price=Decimal('250.00'),
        )

        with self.assertRaises(IntegrityError):
            SaleItem.objects.create(
                sale=sale,
                product=self.product_nvme,
                quantity=2,
                unit_price=Decimal('250.00'),
            )

    def test_product_deletion_protected_when_referenced_by_sale(self):
        """Product cannot be deleted if a SaleItem references it (PROTECT integrity)."""
        from django.utils import timezone

        sale = Sale.objects.create(
            order_identifier='SALE-20260918-PROTECT',
            customer_name='Protect Corp',
            sale_date=timezone.now(),
            status=Sale.Status.COMPLETED,
            total_amount=Decimal('250.00'),
        )
        SaleItem.objects.create(
            sale=sale,
            product=self.product_nvme,
            quantity=1,
            unit_price=Decimal('250.00'),
        )

        with self.assertRaises(models.ProtectedError):
            self.product_nvme.delete()

    # --------------------------------------------------------------------------
    # 2. Service Layer: Successful Sale Creation & Inventory Flow
    # --------------------------------------------------------------------------

    def test_create_sale_service_successful_flow(self):
        """
        create_sale creates Sale, SaleItems, decrements product stock,
        and generates InventoryTransaction REMOVE records.
        """
        initial_nvme_stock = self.product_nvme.stock_quantity  # 20
        initial_sata_stock = self.product_sata.stock_quantity  # 5

        sale = services.create_sale(
            customer_name='Mega Corp',
            customer_email='procure@megacorp.com',
            items_data=[
                {'product_id': self.product_nvme.id, 'quantity': 3},  # 3 * 250 = 750
                {'product_id': self.product_sata.id, 'quantity': 2},  # 2 * 100 = 200
            ],
            user=self.standard,
            notes='Urgent data center expansion order.',
        )

        self.assertIsNotNone(sale.pk)
        self.assertTrue(sale.order_identifier.startswith('SALE-'))
        self.assertEqual(sale.total_amount, Decimal('950.00'))
        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(sale.created_by, self.standard)
        self.assertEqual(sale.items.count(), 2)

        # Verify physical stock reduction
        self.product_nvme.refresh_from_db()
        self.product_sata.refresh_from_db()
        self.assertEqual(self.product_nvme.stock_quantity, initial_nvme_stock - 3)  # 17
        self.assertEqual(self.product_sata.stock_quantity, initial_sata_stock - 2)  # 3

        # Verify audit transactions
        txs = InventoryTransaction.objects.filter(reference=sale.order_identifier)
        self.assertEqual(txs.count(), 2)
        for tx in txs:
            self.assertEqual(tx.transaction_type, InventoryTransaction.TransactionType.REMOVE)
            self.assertEqual(tx.created_by, self.standard)

    # --------------------------------------------------------------------------
    # 3. Stock Validation & Preventing Negative Stock
    # --------------------------------------------------------------------------

    def test_insufficient_stock_prevents_sale_and_rolls_back(self):
        """
        When requested quantity exceeds stock, InsufficientStockError is raised,
        no sale is saved, and product stock remains untouched.
        """
        initial_sata_stock = self.product_sata.stock_quantity  # 5 units

        with self.assertRaises(InsufficientStockError):
            services.create_sale(
                customer_name='Greedy Corp',
                items_data=[
                    {'product_id': self.product_sata.id, 'quantity': 10},  # Request 10, only 5 available
                ],
                user=self.manager,
            )

        # Ensure stock was not decremented
        self.product_sata.refresh_from_db()
        self.assertEqual(self.product_sata.stock_quantity, initial_sata_stock)

        # Ensure no Sale or InventoryTransaction was persisted
        self.assertFalse(Sale.objects.filter(customer_name='Greedy Corp').exists())
        self.assertFalse(InventoryTransaction.objects.filter(notes__icontains='Greedy Corp').exists())

    def test_inactive_product_cannot_be_sold(self):
        """Inactive products cannot be ordered in a completed sale."""
        with self.assertRaises(InsufficientStockError):
            services.create_sale(
                customer_name='Inactive SKU Test',
                items_data=[
                    {'product_id': self.inactive_product.id, 'quantity': 1},
                ],
                user=self.admin,
            )

    def test_duplicate_product_in_items_data_rejected(self):
        """Attempting to specify the same product ID multiple times in items_data is rejected."""
        with self.assertRaises(SaleCreationError):
            services.create_sale(
                customer_name='Duplicate SKU Test',
                items_data=[
                    {'product_id': self.product_nvme.id, 'quantity': 1},
                    {'product_id': self.product_nvme.id, 'quantity': 2},
                ],
                user=self.admin,
            )

    def test_empty_items_rejected(self):
        """Sale with empty items payload is rejected."""
        with self.assertRaises(SaleCreationError):
            services.create_sale(
                customer_name='Empty Items Test',
                items_data=[],
                user=self.admin,
            )

    # --------------------------------------------------------------------------
    # 4. Data Selectors & KPIs
    # --------------------------------------------------------------------------

    def test_sales_selectors_and_kpis(self):
        """Verifies selector querying, filtering, and summary statistics."""
        sale1 = services.create_sale(
            customer_name='Alpha Tech',
            items_data=[{'product_id': self.product_nvme.id, 'quantity': 1}],
        )
        sale2 = services.create_sale(
            customer_name='Beta Corp',
            items_data=[{'product_id': self.product_nvme.id, 'quantity': 2}],
        )

        # Search selector
        qs = selectors.get_sales_queryset(search='Alpha')
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().customer_name, 'Alpha Tech')

        # KPI selector
        kpis = selectors.get_sales_summary_kpis()
        self.assertEqual(kpis['completed_sales_count'], 2)
        self.assertEqual(kpis['total_revenue'], Decimal('750.00'))  # (1*250) + (2*250)
        self.assertEqual(kpis['total_units_sold'], 3)

    # --------------------------------------------------------------------------
    # 5. Views and RBAC Permissions
    # --------------------------------------------------------------------------

    def test_sales_views_require_authentication(self):
        """Unauthenticated requests are redirected to the login view."""
        list_url = reverse('domain_app:sale_list')
        create_url = reverse('domain_app:sale_create')

        resp_list = self.client.get(list_url)
        self.assertEqual(resp_list.status_code, 302)
        self.assertIn('/auth/login/', resp_list.url)

        resp_create = self.client.get(create_url)
        self.assertEqual(resp_create.status_code, 302)
        self.assertIn('/auth/login/', resp_create.url)

    def test_sales_list_view_authenticated(self):
        """Authenticated users (Standard, Manager, Admin) can view the sales list."""
        self.client.force_login(self.standard)
        response = self.client.get(reverse('domain_app:sale_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('kpis', response.context)
        self.assertIn('page_obj', response.context)

    def test_sale_detail_view(self):
        """Sale detail view renders sale details and linked stock movement ledger."""
        sale = services.create_sale(
            customer_name='Detail Test Client',
            customer_email='client@detailtest.com',
            items_data=[{'product_id': self.product_nvme.id, 'quantity': 1}],
            user=self.manager,
        )

        self.client.force_login(self.manager)
        response = self.client.get(reverse('domain_app:sale_detail', kwargs={'pk': sale.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sale'], sale)
        self.assertContains(response, 'Detail Test Client')
        self.assertContains(response, 'Stock Movement Audit Ledger')

    def test_sale_create_post_success(self):
        """POST to sale_create with form arrays creates sale and redirects to detail."""
        self.client.force_login(self.standard)

        payload = {
            'customer_name': 'Web Order Customer',
            'customer_email': 'web@order.com',
            'customer_phone': '123-456',
            'notes': 'Online checkout',
            'product_id[]': [str(self.product_nvme.id)],
            'quantity[]': ['2'],
            'unit_price[]': ['250.00'],
        }

        response = self.client.post(reverse('domain_app:sale_create'), data=payload)
        self.assertEqual(response.status_code, 302)

        sale = Sale.objects.get(customer_name='Web Order Customer')
        self.assertEqual(sale.total_amount, Decimal('500.00'))
        self.assertRedirects(response, reverse('domain_app:sale_detail', kwargs={'pk': sale.pk}))

    def test_sale_create_post_insufficient_stock_shows_error(self):
        """POST requesting more stock than on hand re-renders with error message."""
        self.client.force_login(self.standard)

        payload = {
            'customer_name': 'Overstock Customer',
            'product_id[]': [str(self.product_sata.id)],
            'quantity[]': ['999'],  # Only 5 available
        }

        response = self.client.post(reverse('domain_app:sale_create'), data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Sale.objects.filter(customer_name='Overstock Customer').exists())


class PurchaseOrderSecurityAndWorkflowTestCase(TestCase):
    """
    Verifies RBAC protection, inactive supplier safeguards, atomic workflow
    intake, and URL naming consistency on Purchase Orders.
    """

    def setUp(self):
        self.category = Category.objects.create(name='Components', description='Test')
        self.active_supplier = Supplier.objects.create(
            name='Active Supplier Corp',
            email='active@supplier.com',
            phone='111-222-3333',
            is_active=True,
        )
        self.inactive_supplier = Supplier.objects.create(
            name='Defunct Supplier Ltd',
            email='defunct@supplier.com',
            phone='444-555-6666',
            is_active=False,
        )
        self.product = Product.objects.create(
            name='DRAM Module 16GB',
            sku='RAM-DDR4-16G',
            category=self.category,
            supplier=self.active_supplier,
            price=Decimal('65.00'),
            stock_quantity=10,
            reorder_level=20,
        )

        self.manager = User.objects.create_user(
            username='po_manager',
            email='po_manager@example.com',
            password='Password123!',
            role=User.Role.MANAGER,
        )
        self.standard = User.objects.create_user(
            username='po_cashier',
            email='po_cashier@example.com',
            password='Password123!',
            role=User.Role.STANDARD,
        )
        self.client = Client()

    def test_inactive_supplier_rejected_in_create_purchase_order_service(self):
        """Service layer must reject creating purchase orders for inactive suppliers."""
        items = [{'product_id': self.product.id, 'quantity': 5, 'unit_cost': Decimal('50.00')}]
        with self.assertRaises(PurchaseOrderError) as ctx:
            services.create_purchase_order(
                supplier=self.inactive_supplier,
                items_data=items,
                user=self.manager,
            )
        self.assertIn("inactive supplier", str(ctx.exception).lower())

    def test_inactive_supplier_rejected_in_purchase_order_clean(self):
        """Model validation clean() must reject assigning inactive suppliers to active POs."""
        po = PurchaseOrder(
            order_number='PO-TEST-INACTIVE',
            supplier=self.inactive_supplier,
            status=PurchaseOrder.Status.DRAFT,
            total_amount=Decimal('100.00'),
        )
        with self.assertRaises(ValidationError) as ctx:
            po.clean()
        self.assertIn('supplier', ctx.exception.message_dict)

    def test_inactive_supplier_rejected_in_purchase_order_form(self):
        """PurchaseOrderForm must reject inactive suppliers."""
        form = PurchaseOrderForm(data={'supplier': self.inactive_supplier.pk, 'notes': 'Test'})
        self.assertFalse(form.is_valid())
        self.assertIn('supplier', form.errors)

    def test_inactive_supplier_rejected_when_advancing_status(self):
        """Cannot advance an order to Pending/Approved/Received if supplier became inactive."""
        # Create draft with active supplier
        po = services.create_purchase_order(
            supplier=self.active_supplier,
            items_data=[{'product_id': self.product.id, 'quantity': 10, 'unit_cost': Decimal('40.00')}],
            user=self.manager,
        )
        # Deactivate supplier mid-process
        self.active_supplier.is_active = False
        self.active_supplier.save()
        po.refresh_from_db()

        with self.assertRaises(PurchaseOrderError) as ctx:
            services.update_purchase_order_status(
                po=po,
                new_status=PurchaseOrder.Status.PENDING,
                user=self.manager,
            )
        self.assertIn("inactive supplier", str(ctx.exception).lower())

    def test_purchase_order_workflow_endpoints_rbac(self):
        """Workflow POST endpoints must enforce manager role and reject standard users."""
        po = services.create_purchase_order(
            supplier=self.active_supplier,
            items_data=[{'product_id': self.product.id, 'quantity': 5, 'unit_cost': Decimal('40.00')}],
            user=self.manager,
        )

        approve_url = reverse('domain_app:purchase_order_approve', kwargs={'pk': po.pk})
        receive_url = reverse('domain_app:purchase_order_receive', kwargs={'pk': po.pk})
        cancel_url = reverse('domain_app:purchase_order_cancel', kwargs={'pk': po.pk})
        delete_url = reverse('domain_app:purchase_order_delete', kwargs={'pk': po.pk})

        # 1. Anonymous -> 302 to login
        resp = self.client.post(approve_url)
        self.assertEqual(resp.status_code, 302)

        # 2. Standard User -> 403 Forbidden
        self.client.force_login(self.standard)
        self.assertEqual(self.client.post(approve_url).status_code, 403)
        self.assertEqual(self.client.post(receive_url).status_code, 403)
        self.assertEqual(self.client.post(cancel_url).status_code, 403)
        self.assertEqual(self.client.post(delete_url).status_code, 403)

        # 3. Manager User -> Success through lifecycle
        self.client.force_login(self.manager)

        # Transition Draft -> Pending via update_status
        services.update_purchase_order_status(po, PurchaseOrder.Status.PENDING, user=self.manager)
        po.refresh_from_db()

        # Approve endpoint
        resp_approve = self.client.post(approve_url)
        self.assertEqual(resp_approve.status_code, 302)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.Status.APPROVED)

        # Receive endpoint (updates inventory atomically)
        initial_stock = self.product.stock_quantity
        resp_receive = self.client.post(receive_url)
        self.assertEqual(resp_receive.status_code, 302)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.Status.RECEIVED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial_stock + 5)

    def test_purchase_order_url_naming_consistency(self):
        """Both canonical purchase_order_* and abbreviated po_* names must resolve identically."""
        self.assertEqual(
            reverse('domain_app:purchase_order_list'),
            reverse('domain_app:po_list')
        )
        self.assertEqual(
            reverse('domain_app:purchase_order_create'),
            reverse('domain_app:po_create')
        )
        self.assertEqual(
            reverse('domain_app:purchase_order_detail', kwargs={'pk': 42}),
            reverse('domain_app:po_detail', kwargs={'pk': 42})
        )
        self.assertEqual(
            reverse('domain_app:purchase_order_update_status', kwargs={'pk': 42}),
            reverse('domain_app:po_update_status', kwargs={'pk': 42})
        )

    def test_create_purchase_order_rejects_products_from_different_supplier(self):
        """Service layer must reject PO line items whose product belongs to a different supplier."""
        other_supplier = Supplier.objects.create(
            name='Second Vendor Corp',
            email='vendor2@example.com',
            phone='+1-555-8822',
        )
        other_product = Product.objects.create(
            name='Competing GPU SKU',
            sku='GPU-COMP-002',
            category=self.category,
            supplier=other_supplier,
            price=Decimal('350.00'),
            stock_quantity=5,
            reorder_level=2,
        )
        # Attempt to order other_product under self.active_supplier
        items = [{'product_id': other_product.id, 'quantity': 2, 'unit_cost': Decimal('300.00')}]
        with self.assertRaises(PurchaseOrderError) as ctx:
            services.create_purchase_order(
                supplier=self.active_supplier,
                items_data=items,
                user=self.manager,
            )
        self.assertIn("different supplier", str(ctx.exception).lower())

    def test_purchase_order_item_clean_rejects_product_from_different_supplier(self):
        """PurchaseOrderItem.clean() rejects products belonging to another supplier."""
        other_supplier = Supplier.objects.create(
            name='Third Vendor LLC',
            email='vendor3@example.com',
            phone='+1-555-8833',
        )
        other_product = Product.objects.create(
            name='Third Party Part',
            sku='PART-TP-003',
            category=self.category,
            supplier=other_supplier,
            price=Decimal('20.00'),
            stock_quantity=10,
            reorder_level=5,
        )
        po = PurchaseOrder.objects.create(
            order_number='PO-CLEAN-SUPP-DIFF',
            supplier=self.active_supplier,
            status=PurchaseOrder.Status.DRAFT,
            total_amount=Decimal('40.00'),
        )
        item = PurchaseOrderItem(
            purchase_order=po,
            product=other_product,
            quantity=2,
            unit_cost=Decimal('20.00'),
        )
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn('product', ctx.exception.message_dict)

    def test_product_deletion_protected_when_referenced_by_purchase_order(self):
        """Product cannot be deleted if a PurchaseOrderItem references it (PROTECT integrity)."""
        services.create_purchase_order(
            supplier=self.active_supplier,
            items_data=[{'product_id': self.product.id, 'quantity': 5, 'unit_cost': Decimal('50.00')}],
            user=self.manager,
        )
        with self.assertRaises(models.ProtectedError):
            self.product.delete()

    def test_product_deletion_view_handles_protected_error_gracefully(self):
        """product_delete view catches ProtectedError and redirects with warning instead of 500."""
        admin_user = User.objects.create_user(
            username='po_admin_test',
            email='po_admin@test.com',
            password='Password123!',
            role=User.Role.ADMIN,
        )
        services.create_purchase_order(
            supplier=self.active_supplier,
            items_data=[{'product_id': self.product.id, 'quantity': 3, 'unit_cost': Decimal('50.00')}],
            user=self.manager,
        )
        self.client.force_login(admin_user)
        delete_url = reverse('domain_app:product_delete', kwargs={'pk': self.product.pk})
        resp = self.client.post(delete_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        # Product still exists
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
        # Message was displayed
        messages_list = list(resp.context['messages'])
        self.assertTrue(any("Cannot delete product" in str(m) for m in messages_list))

    def test_supplier_deletion_protected_when_referenced_by_purchase_order(self):
        """Supplier cannot be deleted if a PurchaseOrder references it (PROTECT integrity)."""
        services.create_purchase_order(
            supplier=self.active_supplier,
            items_data=[{'product_id': self.product.id, 'quantity': 2, 'unit_cost': Decimal('50.00')}],
            user=self.manager,
        )
        with self.assertRaises(models.ProtectedError):
            self.active_supplier.delete()

    def test_supplier_deletion_view_handles_protected_error_gracefully(self):
        """supplier_delete view catches ProtectedError and redirects with warning instead of 500."""
        services.create_purchase_order(
            supplier=self.active_supplier,
            items_data=[{'product_id': self.product.id, 'quantity': 2, 'unit_cost': Decimal('50.00')}],
            user=self.manager,
        )
        self.client.force_login(self.manager)
        delete_url = reverse('domain_app:supplier_delete', kwargs={'pk': self.active_supplier.pk})
        resp = self.client.post(delete_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        # Supplier still exists
        self.assertTrue(Supplier.objects.filter(pk=self.active_supplier.pk).exists())
        # Message was displayed
        messages_list = list(resp.context['messages'])
        self.assertTrue(any("Cannot delete supplier" in str(m) for m in messages_list))






