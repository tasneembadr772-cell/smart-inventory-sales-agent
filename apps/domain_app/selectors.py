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

from .models import Category, Product, Supplier, InventoryTransaction


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
        elif status_key in ('attention', 'requiring_attention'):
            if is_privileged:
                qs = qs.filter(
                    Q(stock_quantity__lte=F('reorder_level')) |
                    Q(is_active=False, stock_quantity__gt=0)
                )
            else:
                qs = qs.filter(stock_quantity__lte=F('reorder_level'))

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


def get_inventory_kpis(user=None) -> Dict[str, Any]:
    """
    Calculates system-wide inventory KPI metrics using single-query database aggregations.
    Guarantees O(1) single-query efficiency using database aggregate functions.

    Respects Role-Based Access Control (RBAC):
    - Standard users calculate metrics strictly across active catalog items.
    - Managers / Admins / Superusers calculate across the entire inventory.
    """
    is_privileged = False
    if user and user.is_authenticated:
        is_privileged = user.is_superuser or getattr(user, 'role', '') in ('ADMIN', 'MANAGER')

    base_qs = Product.objects.all()
    if user and user.is_authenticated and not is_privileged:
        base_qs = base_qs.filter(is_active=True)

    # Calculate attention filter condition
    if is_privileged:
        attention_q = Q(stock_quantity__lte=F('reorder_level')) | Q(is_active=False, stock_quantity__gt=0)
    else:
        attention_q = Q(stock_quantity__lte=F('reorder_level'))

    aggregates = base_qs.aggregate(
        total_products=Count('id'),
        active_products=Count('id', filter=Q(is_active=True)),
        low_stock_count=Count(
            'id',
            filter=Q(stock_quantity__gt=0, stock_quantity__lte=F('reorder_level'))
        ),
        out_of_stock_count=Count('id', filter=Q(stock_quantity=0)),
        total_reorder_needed=Count('id', filter=Q(stock_quantity__lte=F('reorder_level'))),
        attention_count=Count('id', filter=attention_q),
        total_units=Coalesce(Sum('stock_quantity'), 0),
        total_valuation=Coalesce(
            Sum(F('stock_quantity') * F('price'), output_field=DecimalField()),
            Value(Decimal('0.00'), output_field=DecimalField())
        ),
    )
    # Add alias total_stock for total_units
    aggregates['total_stock'] = aggregates['total_units']
    return aggregates


# ==============================================================================
# Low Stock & Inventory Selectors (Reusable by AI Agent)
# ==============================================================================

def get_low_stock_products(
    user=None,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    include_out_of_stock: bool = True,
) -> QuerySet[Product]:
    """
    Retrieves inventory products where current stock is at or below the reorder level.
    
    Business Rule:
    A product is low-stock when current quantity <= reorder level.
    
    Reusable by the AI Agent for inventory monitoring, low-stock notifications,
    and replenishment planning.
    """
    qs = Product.objects.select_related('category', 'supplier')

    # RBAC visibility
    is_privileged = False
    if user and user.is_authenticated:
        is_privileged = user.is_superuser or user.role in ('ADMIN', 'MANAGER')

    if not is_privileged:
        qs = qs.filter(is_active=True)

    # Core low-stock business rule: current quantity <= reorder level
    if include_out_of_stock:
        qs = qs.filter(stock_quantity__lte=F('reorder_level'))
    else:
        qs = qs.filter(stock_quantity__gt=0, stock_quantity__lte=F('reorder_level'))

    # Filters
    if search:
        term = search.strip()
        if term:
            qs = qs.filter(
                Q(name__icontains=term) |
                Q(sku__icontains=term) |
                Q(description__icontains=term)
            )

    if category_id:
        try:
            qs = qs.filter(category_id=int(category_id))
        except (ValueError, TypeError):
            pass

    if supplier_id:
        try:
            qs = qs.filter(supplier_id=int(supplier_id))
        except (ValueError, TypeError):
            pass

    return qs.order_by('stock_quantity', 'name')


def get_out_of_stock_products(
    user=None,
    category_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
) -> QuerySet[Product]:
    """Retrieves products with zero physical units in stock."""
    return get_low_stock_products(
        user=user,
        category_id=category_id,
        supplier_id=supplier_id,
        include_out_of_stock=True
    ).filter(stock_quantity=0)


def get_products_requiring_attention(
    user=None,
    limit: Optional[int] = None,
) -> list[Dict[str, Any]]:
    """
    Retrieves inventory products requiring immediate operational attention.
    
    Attention Criteria:
    - CRITICAL: Out-of-stock products (stock == 0).
    - WARNING: Low-stock products (0 < stock <= reorder_level).
    - AUDIT: Inactive products with stranded physical stock (for Managers/Admins).

    Guarantees N+1 prevention with `select_related('category', 'supplier')`.
    Returns rich dictionary representations with deficit calculations and operational reasons.
    """
    is_privileged = False
    if user and user.is_authenticated:
        is_privileged = user.is_superuser or getattr(user, 'role', '') in ('ADMIN', 'MANAGER')

    qs = Product.objects.select_related('category', 'supplier')

    if not is_privileged:
        # Standard users only see active products needing replenishment
        attention_condition = Q(is_active=True, stock_quantity__lte=F('reorder_level'))
    else:
        # Elevated users also see inactive products with trapped physical stock
        attention_condition = (
            Q(stock_quantity__lte=F('reorder_level')) |
            Q(is_active=False, stock_quantity__gt=0)
        )

    qs = qs.filter(attention_condition).order_by('stock_quantity', 'reorder_level', 'name')

    if limit:
        qs = qs[:limit]

    attention_list = []
    for p in qs:
        deficit_to_reorder = max(0, p.reorder_level - p.stock_quantity)
        target = p.target_stock_level if p.target_stock_level is not None else p.reorder_level * 2
        deficit_to_target = max(0, target - p.stock_quantity)

        if p.stock_quantity == 0:
            urgency = 'CRITICAL'
            urgency_label = 'Critical Out of Stock'
            reason = 'Stock depleted. Immediate replenishment required.'
        elif not p.is_active and p.stock_quantity > 0:
            urgency = 'AUDIT'
            urgency_label = 'Inactive With Stock'
            reason = f'Inactive catalog SKU with {p.stock_quantity} stranded physical units.'
        else:
            urgency = 'WARNING'
            urgency_label = 'Low Stock'
            reason = f'Stock ({p.stock_quantity}) at or below reorder threshold ({p.reorder_level}).'

        attention_list.append({
            'product': p,
            'product_id': p.pk,
            'name': p.name,
            'sku': p.sku,
            'category': p.category,
            'category_name': p.category.name if p.category else '',
            'supplier': p.supplier,
            'supplier_name': p.supplier.name if p.supplier else None,
            'supplier_email': p.supplier.email if p.supplier else None,
            'stock_quantity': p.stock_quantity,
            'reorder_level': p.reorder_level,
            'target_stock_level': p.target_stock_level,
            'deficit_to_reorder': deficit_to_reorder,
            'deficit_to_target': deficit_to_target,
            'suggested_reorder_qty': deficit_to_target if deficit_to_target > 0 else (deficit_to_reorder + 10),
            'price': p.price,
            'urgency': urgency,
            'urgency_label': urgency_label,
            'reason': reason,
            'is_active': p.is_active,
        })

    return attention_list


def get_low_stock_report(
    user=None,
    category_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    include_out_of_stock: bool = True,
) -> list[Dict[str, Any]]:
    """
    Returns structured, serializable data representing low-stock products.
    Specifically crafted for direct consumption by the AI Agent and external integrations.
    Calculates replenishment deficits against reorder levels and target levels.
    """
    qs = get_low_stock_products(
        user=user,
        category_id=category_id,
        supplier_id=supplier_id,
        include_out_of_stock=include_out_of_stock,
    )

    report = []
    for p in qs:
        deficit_to_reorder = max(0, p.reorder_level - p.stock_quantity)
        target = p.target_stock_level if p.target_stock_level is not None else p.reorder_level * 2
        deficit_to_target = max(0, target - p.stock_quantity)
        urgency = 'CRITICAL' if p.stock_quantity == 0 else 'HIGH'

        report.append({
            'product_id': p.id,
            'name': p.name,
            'sku': p.sku,
            'category_id': p.category_id,
            'category_name': p.category.name,
            'supplier_id': p.supplier_id,
            'supplier_name': p.supplier.name if p.supplier else None,
            'supplier_email': p.supplier.email if p.supplier else None,
            'current_stock': p.stock_quantity,
            'reorder_level': p.reorder_level,
            'target_stock_level': p.target_stock_level,
            'deficit_to_reorder': deficit_to_reorder,
            'deficit_to_target': deficit_to_target,
            'suggested_reorder_qty': deficit_to_target if deficit_to_target > 0 else (deficit_to_reorder + 10),
            'unit_price': float(p.price),
            'urgency': urgency,
            'is_active': p.is_active,
        })
    return report


def get_inventory_transactions_queryset(
    user=None,
    product_id: Optional[int] = None,
    transaction_type: Optional[str] = None,
    search: Optional[str] = None,
) -> QuerySet[InventoryTransaction]:
    """
    Retrieves filtered and optimized QuerySet of inventory stock movements.
    Prevents N+1 database queries through `select_related('product', 'created_by', 'product__category')`.
    """
    qs = InventoryTransaction.objects.select_related(
        'product', 'created_by', 'product__category', 'product__supplier'
    ).all()

    if product_id:
        try:
            qs = qs.filter(product_id=int(product_id))
        except (ValueError, TypeError):
            pass

    if transaction_type:
        tx_clean = transaction_type.strip().upper()
        if tx_clean in InventoryTransaction.TransactionType.values:
            qs = qs.filter(transaction_type=tx_clean)

    if search:
        term = search.strip()
        if term:
            qs = qs.filter(
                Q(product__name__icontains=term) |
                Q(product__sku__icontains=term) |
                Q(reference__icontains=term) |
                Q(notes__icontains=term)
            )

    return qs.order_by('-created_at')


