"""
Domain Models for Inventory & Sales Management System.

Defines normalized, relational database models for Category and Product
with strict database-level constraints, composite indexes, and data validation
suitable for academic code defense and production-grade reliability.
"""

from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models
from django.utils.text import slugify


class Supplier(models.Model):
    """
    Vendor or manufacturer furnishing inventory stock products.

    Database Integrity & Normalization:
    - B-Tree indexes on `name` and `email` for rapid searching and sorting.
    - Check constraint ensuring supplier name is non-empty.
    - Email validation on model cleaning.
    """
    name = models.CharField(
        max_length=200,
        db_index=True,
        help_text='Official company or business name of the supplier.',
    )
    contact_person = models.CharField(
        max_length=150,
        blank=True,
        default='',
        help_text='Primary contact representative or account manager.',
    )
    email = models.EmailField(
        db_index=True,
        help_text='Contact email address for procurement and inquiries.',
    )
    phone = models.CharField(
        max_length=50,
        help_text='Direct telephone or mobile contact number.',
    )
    address = models.TextField(
        blank=True,
        default='',
        help_text='Physical office, factory, or warehouse dispatch address.',
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text='Designates whether this supplier is active for inventory operations.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Supplier'
        verbose_name_plural = 'Suppliers'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name'], name='idx_supplier_name'),
            models.Index(fields=['email'], name='idx_supplier_email'),
            models.Index(fields=['name', 'is_active'], name='idx_supplier_name_active'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name__exact=''),
                name='check_supplier_name_not_empty',
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        """Model-level validation and string normalization."""
        if self.name:
            self.name = self.name.strip()
            if not self.name:
                raise ValidationError({'name': 'Supplier name cannot be empty or whitespace.'})
        else:
            raise ValidationError({'name': 'Supplier name is required.'})

        if self.contact_person:
            self.contact_person = self.contact_person.strip()

        if self.phone:
            self.phone = self.phone.strip()
            if not self.phone:
                raise ValidationError({'phone': 'Supplier phone number cannot be empty or whitespace.'})
        else:
            raise ValidationError({'phone': 'Supplier phone number is required.'})

        if self.email:
            self.email = self.email.strip().lower()
            try:
                validate_email(self.email)
            except ValidationError as e:
                raise ValidationError({'email': 'Enter a valid email address.'}) from e
        else:
            raise ValidationError({'email': 'Supplier email address is required.'})

        if self.address:
            self.address = self.address.strip()

    def save(self, *args, **kwargs):
        """Execute validation before committing to database."""
        self.clean()
        super().save(*args, **kwargs)


class Category(models.Model):
    """
    Categorical taxonomy grouping inventory products.
    
    Database Integrity:
    - Unique name to prevent duplicate classifications.
    - Slug generation for SEO-friendly URLs.
    - Protected deletion when referenced by active inventory products.
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text='Unique name for the product category.',
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True,
        help_text='URL-safe slug representation of the category.',
    )
    description = models.TextField(
        blank=True,
        default='',
        help_text='Detailed overview of this category.',
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text='Whether this category is active and visible for product assignment.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Category'
        verbose_name_plural = 'Categories'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name', 'is_active'], name='idx_cat_name_active'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name__exact=''),
                name='check_category_name_not_empty',
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        """Model-level validation and normalization."""
        if self.name:
            self.name = self.name.strip()
            if not self.name:
                raise ValidationError({'name': 'Category name cannot be empty or whitespace.'})

    def save(self, *args, **kwargs):
        """Auto-populate slug if not provided, and enforce validation."""
        self.clean()
        if not self.slug and self.name:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Product(models.Model):
    """
    Physical or digital inventory SKU record.

    Database Integrity & Normalization:
    - SKU (Stock Keeping Unit) is globally unique and indexed.
    - Category relationship is protected (`on_delete=models.PROTECT`) to avoid
      cascading deletions destroying stock/historical data.
    - Check constraints enforce non-negative prices and inventory thresholds.
    """
    name = models.CharField(
        max_length=200,
        db_index=True,
        help_text='Commercial display name of the product.',
    )
    sku = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text='Globally unique Stock Keeping Unit identifier.',
    )
    description = models.TextField(
        blank=True,
        default='',
        help_text='Full specifications or commercial description.',
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
        db_index=True,
        help_text='The classification group this product belongs to.',
    )
    supplier = models.ForeignKey(
        Supplier,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='products',
        db_index=True,
        help_text='Vendor or manufacturer supplying this product SKU.',
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text='Unit selling price (must be non-negative).',
    )
    stock_quantity = models.PositiveIntegerField(
        default=0,
        help_text='Physical units currently in stock.',
    )
    reorder_level = models.PositiveIntegerField(
        default=10,
        help_text='Threshold below which low-stock reorder alerts are triggered.',
    )
    target_stock_level = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Optional target or maximum stock level for inventory replenishment.',
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text='Designates whether this product is available for inventory operations.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Product'
        verbose_name_plural = 'Products'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['category', 'is_active'], name='idx_prod_cat_active'),
            models.Index(fields=['supplier'], name='idx_prod_supplier'),
            models.Index(fields=['name'], name='idx_prod_name'),
            models.Index(fields=['sku'], name='idx_prod_sku'),
            models.Index(fields=['-created_at'], name='idx_prod_created_at'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price__gte=Decimal('0.00')),
                name='check_product_price_non_negative',
            ),
            models.CheckConstraint(
                condition=models.Q(stock_quantity__gte=0),
                name='check_product_stock_non_negative',
            ),
            models.CheckConstraint(
                condition=models.Q(reorder_level__gte=0),
                name='check_product_reorder_non_negative',
            ),
            models.CheckConstraint(
                condition=models.Q(target_stock_level__isnull=True) | models.Q(target_stock_level__gte=0),
                name='check_product_target_stock_non_negative',
            ),
            models.CheckConstraint(
                condition=~models.Q(sku__exact=''),
                name='check_product_sku_not_empty',
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"

    # --------------------------------------------------------------------------
    # Business Properties & Inventory Health Helpers
    # --------------------------------------------------------------------------

    @property
    def is_low_stock(self) -> bool:
        """
        True if current stock is at or below the reorder threshold (quantity <= reorder_level).
        Satisfies core business rule for inventory reorder alerting.
        """
        return self.stock_quantity <= self.reorder_level

    @property
    def is_out_of_stock(self) -> bool:
        """True if stock is completely depleted."""
        return self.stock_quantity == 0

    @property
    def stock_status(self) -> str:
        """Categorical health status indicator for UI badge rendering."""
        if self.stock_quantity == 0:
            return 'out_of_stock'
        if self.stock_quantity <= self.reorder_level:
            return 'low_stock'
        return 'in_stock'

    def clean(self):
        """Enforces application-level normalization and validation rules."""
        if self.sku:
            self.sku = self.sku.strip().upper()
            if not self.sku:
                raise ValidationError({'sku': 'SKU cannot be empty or whitespace.'})

        if self.name:
            self.name = self.name.strip()
            if not self.name:
                raise ValidationError({'name': 'Product name cannot be empty or whitespace.'})

        if self.price is not None and self.price < Decimal('0.00'):
            raise ValidationError({'price': 'Product price must be greater than or equal to 0.00.'})

        if self.stock_quantity is not None and self.stock_quantity < 0:
            raise ValidationError({'stock_quantity': 'Stock quantity cannot be negative.'})

        if self.reorder_level is not None and self.reorder_level < 0:
            raise ValidationError({'reorder_level': 'Reorder level cannot be negative.'})

        if self.target_stock_level is not None and self.target_stock_level < 0:
            raise ValidationError({'target_stock_level': 'Target stock level cannot be negative.'})

    def save(self, *args, **kwargs):
        """Execute validation before committing to database."""
        self.clean()
        super().save(*args, **kwargs)


class InventoryTransaction(models.Model):
    """
    Immutable audit ledger of stock movements and inventory adjustments.

    Database Integrity & Normalization:
    - Tracks every stock quantity change with prior and post snapshot values.
    - Captures the operational type: ADD, REMOVE, or ADJUSTMENT.
    - Enforces relational protection on Product (models.PROTECT) to avoid data loss.
    - Check constraints guarantee non-negative quantities and stock counts.
    - B-Tree composite indexes for fast audit querying and reporting.
    """

    class TransactionType(models.TextChoices):
        ADD = 'ADD', 'Stock Added'
        REMOVE = 'REMOVE', 'Stock Removed'
        ADJUSTMENT = 'ADJUSTMENT', 'Stock Adjustment'

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='stock_transactions',
        db_index=True,
        help_text='The product SKU affected by this stock transaction.',
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices,
        db_index=True,
        help_text='Nature of the stock movement (added, removed, adjustment).',
    )
    quantity = models.PositiveIntegerField(
        help_text='Quantity units moved or delta adjusted.',
    )
    previous_stock = models.PositiveIntegerField(
        help_text='Stock quantity immediately prior to this transaction.',
    )
    new_stock = models.PositiveIntegerField(
        help_text='Stock quantity immediately following this transaction.',
    )
    reference = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Reference code or identifier (e.g. PO, receipt, audit tag).',
    )
    notes = models.TextField(
        blank=True,
        default='',
        help_text='Operational explanation or reason for the inventory change.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='inventory_transactions',
        help_text='Staff or manager who authorized/executed this stock movement.',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text='Timestamp when the transaction was committed.',
    )

    class Meta:
        verbose_name = 'Inventory Transaction'
        verbose_name_plural = 'Inventory Transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at'], name='idx_inv_tx_prod_date'),
            models.Index(fields=['transaction_type', '-created_at'], name='idx_inv_tx_type_date'),
            models.Index(fields=['-created_at'], name='idx_inv_tx_created'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0),
                name='check_inv_tx_qty_non_negative',
            ),
            models.CheckConstraint(
                condition=models.Q(previous_stock__gte=0),
                name='check_inv_tx_prev_non_neg',
            ),
            models.CheckConstraint(
                condition=models.Q(new_stock__gte=0),
                name='check_inv_tx_new_non_neg',
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.get_transaction_type_display()}: {self.quantity} units for "
            f"{self.product.sku} ({self.previous_stock} -> {self.new_stock})"
        )

    def clean(self):
        """Model validation ensuring non-negative values."""
        if self.quantity is not None and self.quantity < 0:
            raise ValidationError({'quantity': 'Transaction quantity cannot be negative.'})
        if self.previous_stock is not None and self.previous_stock < 0:
            raise ValidationError({'previous_stock': 'Previous stock snapshot cannot be negative.'})
        if self.new_stock is not None and self.new_stock < 0:
            raise ValidationError({'new_stock': 'New stock snapshot cannot be negative.'})

    def save(self, *args, **kwargs):
        """Ensure clean validation before persisting."""
        self.clean()
        super().save(*args, **kwargs)


class Sale(models.Model):
    """
    Commercial sales transaction record.

    Database Integrity & Normalization:
    - Globally unique order/sale identifier (`order_identifier`).
    - Customer information recorded directly on the transaction header.
    - Protected transaction lifecycle statuses.
    - Safe backend monetary total amount with database check constraints.
    - Indexed on order_identifier, sale_date, status, and created_at for fast retrieval.
    """

    class Status(models.TextChoices):
        COMPLETED = 'COMPLETED', 'Completed'
        DRAFT = 'DRAFT', 'Draft'
        CANCELLED = 'CANCELLED', 'Cancelled'

    order_identifier = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text='Globally unique sale/order tracking identifier (e.g. SALE-YYYYMMDD-XXXXXX).',
    )
    customer_name = models.CharField(
        max_length=200,
        db_index=True,
        help_text='Full name or business identity of the purchasing customer.',
    )
    customer_email = models.EmailField(
        blank=True,
        default='',
        help_text='Optional customer email address for receipting.',
    )
    customer_phone = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text='Optional customer contact telephone number.',
    )
    sale_date = models.DateTimeField(
        db_index=True,
        help_text='Operational date and time of sale execution.',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.COMPLETED,
        db_index=True,
        help_text='Fulfillment and settlement lifecycle status of this sale.',
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Aggregate sum of all line item subtotals (calculated safely on backend).',
    )
    notes = models.TextField(
        blank=True,
        default='',
        help_text='Special instructions, shipping notes, or commercial context.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sales_created',
        help_text='Staff member or sales agent who processed this transaction.',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text='System record creation timestamp.',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text='System record modification timestamp.',
    )

    class Meta:
        verbose_name = 'Sale'
        verbose_name_plural = 'Sales'
        ordering = ['-sale_date', '-created_at']
        indexes = [
            models.Index(fields=['order_identifier'], name='idx_sale_order_id'),
            models.Index(fields=['sale_date'], name='idx_sale_date'),
            models.Index(fields=['status'], name='idx_sale_status'),
            models.Index(fields=['customer_name'], name='idx_sale_cust_name'),
            models.Index(fields=['-created_at'], name='idx_sale_created_at'),
            models.Index(fields=['status', '-sale_date'], name='idx_sale_status_date'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=Decimal('0.00')),
                name='check_sale_total_amount_non_negative',
            ),
            models.CheckConstraint(
                condition=~models.Q(order_identifier__exact=''),
                name='check_sale_order_id_not_empty',
            ),
            models.CheckConstraint(
                condition=~models.Q(customer_name__exact=''),
                name='check_sale_customer_name_not_empty',
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_identifier} - {self.customer_name} (${self.total_amount})"

    @property
    def total_items_count(self) -> int:
        """Total quantity of physical units across all line items."""
        return sum(item.quantity for item in self.items.all())

    def clean(self):
        """Model-level validation and normalization."""
        if self.order_identifier:
            self.order_identifier = self.order_identifier.strip().upper()
            if not self.order_identifier:
                raise ValidationError({'order_identifier': 'Order identifier cannot be empty.'})
        else:
            raise ValidationError({'order_identifier': 'Order identifier is required.'})

        if self.customer_name:
            self.customer_name = self.customer_name.strip()
            if not self.customer_name:
                raise ValidationError({'customer_name': 'Customer name cannot be empty or whitespace.'})
        else:
            raise ValidationError({'customer_name': 'Customer name is required.'})

        if self.customer_email:
            self.customer_email = self.customer_email.strip().lower()
            try:
                validate_email(self.customer_email)
            except ValidationError as e:
                raise ValidationError({'customer_email': 'Enter a valid customer email address.'}) from e

        if self.customer_phone:
            self.customer_phone = self.customer_phone.strip()

        if self.total_amount is not None and self.total_amount < Decimal('0.00'):
            raise ValidationError({'total_amount': 'Total amount cannot be negative.'})

    def save(self, *args, **kwargs):
        """Execute validation before saving to database."""
        self.clean()
        super().save(*args, **kwargs)


class SaleItem(models.Model):
    """
    Individual line item associating a product SKU with a sale transaction.

    Database Integrity & Normalization:
    - Composite uniqueness on `('sale', 'product')` prevents duplicate line entries for the same product.
    - Foreign key to Product uses `on_delete=models.PROTECT` ensuring product SKU deletions
      do not destroy historical financial and ledger records.
    - Foreign key to Sale uses `on_delete=models.CASCADE` ensuring complete order cleanup.
    - Check constraints enforce positive quantities and non-negative pricing.
    - Stores locked unit price and computed subtotal at time of transaction to maintain
      financial integrity regardless of future product price changes.
    """
    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        related_name='items',
        db_index=True,
        help_text='Parent sale order transaction.',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='sale_items',
        db_index=True,
        help_text='Inventory product item purchased.',
    )
    quantity = models.PositiveIntegerField(
        help_text='Quantity of units purchased (must be >= 1).',
    )
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text='Historical unit price snapshot at time of sale.',
    )
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text='Line total computed as quantity * unit_price.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Sale Item'
        verbose_name_plural = 'Sale Items'
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(
                fields=['sale', 'product'],
                name='unique_product_per_sale',
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='check_sale_item_qty_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=Decimal('0.00')),
                name='check_sale_item_unit_price_non_neg',
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=Decimal('0.00')),
                name='check_sale_item_subtotal_non_neg',
            ),
        ]
        indexes = [
            models.Index(fields=['sale', 'product'], name='idx_sale_item_sale_prod'),
            models.Index(fields=['product'], name='idx_sale_item_prod'),
        ]

    def __str__(self) -> str:
        return f"{self.quantity}x {self.product.name} @ ${self.unit_price} (${self.subtotal})"

    def clean(self):
        """Validate numeric integrity and subtotal correctness."""
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({'quantity': 'Quantity must be at least 1 unit.'})

        if self.unit_price is not None and self.unit_price < Decimal('0.00'):
            raise ValidationError({'unit_price': 'Unit price cannot be negative.'})

        if self.quantity is not None and self.unit_price is not None:
            expected_subtotal = Decimal(str(self.quantity)) * Decimal(str(self.unit_price))
            if self.subtotal is None or self.subtotal != expected_subtotal:
                self.subtotal = expected_subtotal

    def save(self, *args, **kwargs):
        """Execute validation and safe subtotal calculation before persisting."""
        if self.quantity is not None and self.unit_price is not None:
            self.subtotal = Decimal(str(self.quantity)) * Decimal(str(self.unit_price))
        self.clean()
        super().save(*args, **kwargs)


