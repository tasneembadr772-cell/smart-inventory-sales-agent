"""
Django Administration Configuration for Inventory Domain Models.
"""

from django.contrib import admin
from .models import Category, Product, Supplier, InventoryTransaction


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'contact_person',
        'email',
        'phone',
        'is_active',
        'total_products_count',
        'created_at',
    )
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'contact_person', 'email', 'phone', 'address')
    readonly_fields = ('created_at', 'updated_at')

    def total_products_count(self, obj):
        return obj.products.count()
    total_products_count.short_description = 'Supplied Products'


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'total_products_count', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at', 'updated_at')

    def total_products_count(self, obj):
        return obj.products.count()
    total_products_count.short_description = 'Products Count'


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'sku',
        'name',
        'category',
        'supplier',
        'price',
        'stock_quantity',
        'reorder_level',
        'target_stock_level',
        'stock_health_badge',
        'is_active',
        'created_at',
    )
    list_filter = ('is_active', 'category', 'supplier', 'created_at')
    search_fields = ('name', 'sku', 'description')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)

    def stock_health_badge(self, obj):
        return obj.stock_status.replace('_', ' ').title()
    stock_health_badge.short_description = 'Stock Health'


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'product',
        'transaction_type',
        'quantity',
        'previous_stock',
        'new_stock',
        'reference',
        'created_by',
    )
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('product__name', 'product__sku', 'reference', 'notes')
    readonly_fields = (
        'product',
        'transaction_type',
        'quantity',
        'previous_stock',
        'new_stock',
        'reference',
        'notes',
        'created_by',
        'created_at',
    )
    ordering = ('-created_at',)


