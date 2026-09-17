"""
Domain Models for Inventory & Sales Management System.

Defines normalized, relational database models for Category and Product
with strict database-level constraints, composite indexes, and data validation
suitable for academic code defense and production-grade reliability.
"""

from decimal import Decimal
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
        """True if current stock is at or below the reorder threshold (and > 0)."""
        return 0 < self.stock_quantity <= self.reorder_level

    @property
    def is_out_of_stock(self) -> bool:
        """True if stock is completely depleted."""
        return self.stock_quantity == 0

    @property
    def stock_status(self) -> str:
        """Categorical health status indicator for UI rendering."""
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

    def save(self, *args, **kwargs):
        """Execute validation before committing to database."""
        self.clean()
        super().save(*args, **kwargs)
