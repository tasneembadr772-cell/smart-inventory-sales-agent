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

from .models import Category, Product, Supplier
from .forms import SupplierForm
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

        # Out of stock test
        p_out = Product.objects.create(
            name='Out of Stock Headset',
            sku='HD-OUT-001',
            category=self.category,
            price=Decimal('89.99'),
            stock_quantity=0,
            reorder_level=5,
        )
        self.assertFalse(p_out.is_low_stock)
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

