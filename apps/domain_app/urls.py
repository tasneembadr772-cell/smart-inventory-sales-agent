"""
URL Configuration for Inventory Product and Category Management.
Namespace: domain_app
"""

from django.urls import path
from . import views

app_name = 'domain_app'

urlpatterns = [
    # Inventory & Low-Stock Management Endpoints
    path('inventory/', views.inventory_dashboard, name='inventory_dashboard'),
    path('inventory/low-stock/', views.low_stock_list, name='low_stock_list'),
    path('inventory/transactions/', views.inventory_transactions_list, name='inventory_transactions'),
    path('products/<int:pk>/stock-adjustment/', views.stock_adjustment, name='product_stock_adjustment'),
    path('api/inventory/low-stock/', views.api_low_stock, name='api_low_stock'),

    # Product Endpoints
    path('products/', views.product_list, name='product_list'),
    path('products/create/', views.product_create, name='product_create'),
    path('products/<int:pk>/', views.product_detail, name='product_detail'),
    path('products/<int:pk>/edit/', views.product_update, name='product_update'),
    path('products/<int:pk>/delete/', views.product_delete, name='product_delete'),

    # Category Endpoints
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_update, name='category_update'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),

    # Supplier Endpoints
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:pk>/', views.supplier_detail, name='supplier_detail'),
    path('suppliers/<int:pk>/edit/', views.supplier_update, name='supplier_update'),
    path('suppliers/<int:pk>/delete/', views.supplier_delete, name='supplier_delete'),

    # Sales Management Endpoints
    path('sales/', views.sale_list, name='sale_list'),
    path('sales/create/', views.sale_create, name='sale_create'),
    path('sales/<int:pk>/', views.sale_detail, name='sale_detail'),

    # Purchase Order Endpoints
    path('purchase-orders/', views.purchase_order_list, name='po_list'),
    path('purchase-orders/create/', views.purchase_order_create, name='po_create'),
    path('purchase-orders/<int:pk>/', views.purchase_order_detail, name='po_detail'),
    path('purchase-orders/<int:pk>/update-status/', views.purchase_order_update_status, name='po_update_status'),
]
