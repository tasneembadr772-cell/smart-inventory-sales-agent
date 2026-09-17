"""
Domain Selectors for Inventory & Sales Management System.

Encapsulates data retrieval logic, complex query filters, and ORM aggregations.
Prevents N+1 database queries through `select_related` and `prefetch_related`.
Keeps queries separated from views for clean architecture and code defense.
"""

from decimal import Decimal
from typing import Optional, Dict, Any
from django.db.models import QuerySet, Q, F, Count, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404

from .models import Category, Product, Supplier


def get_products_queryset(
    user=None,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    stock_status: Optional[str] = None,
    status_filter: Optional[str] = None,
) -> QuerySet[Product]:
    """
    Retrieves filtered and optimized QuerySet of products.

    - Uses `select_related('category', 'supplier')` to prevent N+1 queries.
    - Applies RBAC visibility rules: Standard users are restricted to active products
      unless elevated privileges (Manager/Admin) allow viewing inactive items.
    - Applies search filters against Name, SKU, and Description.
    - Applies categorical, supplier, and inventory health status filters.
    """
    qs = Product.objects.select_related('category', 'supplier').all()

    # RBAC visibility boundary
    is_privileged = False
    if user and user.is_authenticated:
        is_privileged = user.is_superuser or user.role in ('ADMIN', 'MANAGER')

    if not is_privileged:
        # Standard users only see active catalog items
        qs = qs.filter(is_active=True)
    elif status_filter:
        if status_filter.lower() == 'active':
            qs = qs.filter(is_active=True)
        elif status_filter.lower() == 'inactive':
            qs = qs.filter(is_active=False)

    # Search filtering across Name, SKU, and Description
    if search:
        search_term = search.strip()
        if search_term:
            qs = qs.filter(
                Q(name__icontains=search_term) |
                Q(sku__icontains=search_term) |
                Q(description__icontains=search_term)
            )

    # Category filtering
    if category_id:
        try:
            cat_id_int = int(category_id)
            qs = qs.filter(category_id=cat_id_int)
        except (ValueError, TypeError):
            pass

    # Supplier filtering
    if supplier_id:
        try:
            supp_id_int = int(supplier_id)
            qs = qs.filter(supplier_id=supp_id_int)
        except (ValueError, TypeError):
            pass

    # Stock health filtering
    if stock_status:
        status_key = stock_status.strip().lower()
        if status_key == 'out_of_stock':
            qs = qs.filter(stock_quantity=0)
        elif status_key == 'low_stock':
            qs = qs.filter(
                stock_quantity__gt=0,
                stock_quantity__lte=F('reorder_level')
            )
        elif status_key == 'in_stock':
            qs = qs.filter(stock_quantity__gt=F('reorder_level'))

    return qs


def get_product_by_id(product_id: int, user=None) -> Product:
    """
    Fetches a single product with category and supplier relationships pre-loaded.
    Raises Http404 if not found or if user lacks visibility permissions.
    """
    qs = Product.objects.select_related('category', 'supplier')
    if user and user.is_authenticated and not (user.is_superuser or user.role in ('ADMIN', 'MANAGER')):
        qs = qs.filter(is_active=True)
    return get_object_or_404(qs, pk=product_id)


def get_categories_queryset(
    include_inactive: bool = True,
    search: Optional[str] = None
) -> QuerySet[Category]:
    """
    Retrieves categories with annotated product counts to eliminate N+1 queries.
    """
    qs = Category.objects.annotate(
        total_products=Count('products'),
        active_products=Count('products', filter=Q(products__is_active=True)),
    )

    if not include_inactive:
        qs = qs.filter(is_active=True)

    if search:
        search_term = search.strip()
        if search_term:
            qs = qs.filter(
                Q(name__icontains=search_term) |
                Q(description__icontains=search_term)
            )

    return qs


def get_category_by_id(category_id: int) -> Category:
    """Retrieves a single category by primary key."""
    return get_object_or_404(Category, pk=category_id)


def get_suppliers_queryset(
    user=None,
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    include_inactive: Optional[bool] = None,
) -> QuerySet[Supplier]:
    """
    Retrieves suppliers with annotated product counts to eliminate N+1 queries.
    Applies RBAC visibility boundary and search across name, contact_person, email, and phone.
    """
    qs = Supplier.objects.annotate(
        total_products=Count('products'),
        active_products=Count('products', filter=Q(products__is_active=True)),
    ).order_by('name')

    is_privileged = False
    if user and user.is_authenticated:
        is_privileged = user.is_superuser or user.role in ('ADMIN', 'MANAGER')

    if include_inactive is not None:
        if not include_inactive:
            qs = qs.filter(is_active=True)
    elif not is_privileged:
        qs = qs.filter(is_active=True)
    elif status_filter:
        if status_filter.lower() == 'active':
            qs = qs.filter(is_active=True)
        elif status_filter.lower() == 'inactive':
            qs = qs.filter(is_active=False)

    if search:
        search_term = search.strip()
        if search_term:
            qs = qs.filter(
                Q(name__icontains=search_term) |
                Q(contact_person__icontains=search_term) |
                Q(email__icontains=search_term) |
                Q(phone__icontains=search_term)
            )

    return qs


def get_supplier_by_id(supplier_id: int, user=None) -> Supplier:
    """
    Retrieves a single supplier by primary key with products pre-loaded.
    Enforces RBAC visibility if standard user.
    """
    qs = Supplier.objects.prefetch_related('products__category')
    if user and user.is_authenticated and not (user.is_superuser or user.role in ('ADMIN', 'MANAGER')):
        qs = qs.filter(is_active=True)
    return get_object_or_404(qs, pk=supplier_id)


def get_supplier_kpis() -> Dict[str, Any]:
    """
    Calculates supplier metrics using O(1) database aggregations.
    """
    return Supplier.objects.aggregate(
        total_suppliers=Count('id'),
        active_suppliers=Count('id', filter=Q(is_active=True)),
        inactive_suppliers=Count('id', filter=Q(is_active=False)),
    )


def get_inventory_kpis() -> Dict[str, Any]:
    """
    Calculates system-wide inventory KPI metrics using database aggregations.
    Guarantees O(1) single-query efficiency using database aggregate functions.
    """
    aggregates = Product.objects.aggregate(
        total_products=Count('id'),
        active_products=Count('id', filter=Q(is_active=True)),
        low_stock_count=Count(
            'id',
            filter=Q(stock_quantity__gt=0, stock_quantity__lte=F('reorder_level'))
        ),
        out_of_stock_count=Count('id', filter=Q(stock_quantity=0)),
        total_units=Coalesce(Sum('stock_quantity'), 0),
        total_valuation=Coalesce(
            Sum(F('stock_quantity') * F('price'), output_field=DecimalField()),
            Value(Decimal('0.00'), output_field=DecimalField())
        ),
    )
    return aggregates

