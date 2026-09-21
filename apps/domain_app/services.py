"""
Domain Services for Inventory & Sales Management System.

Handles domain write operations, business rule enforcement, and transactional integrity.
Encapsulates mutations away from views to satisfy clean architecture requirements.
"""

from decimal import Decimal
from typing import Optional, Dict, Any, List
import uuid
from django.core.exceptions import ValidationError
from django.db import transaction, models
from django.utils import timezone

from .models import Category, Product, Supplier, InventoryTransaction, Sale, SaleItem, PurchaseOrder, PurchaseOrderItem

_UNSET = object()


class DomainServiceError(Exception):
    """Base exception for domain business logic failures."""
    pass


class ProtectedCategoryError(DomainServiceError):
    """Raised when an attempt is made to delete a category that still contains products."""
    pass


class InsufficientStockError(DomainServiceError, ValidationError):
    """Raised when an operation attempts to decrement stock beyond available units."""
    pass


class InvalidStockAdjustmentError(DomainServiceError, ValidationError):
    """Raised when a stock adjustment violates business rules or constraints."""
    pass


# ==============================================================================
# Product Service Operations
# ==============================================================================

@transaction.atomic
def create_product(
    *,
    name: str,
    sku: str,
    category: Category,
    price: Decimal,
    supplier: Optional[Supplier] = None,
    stock_quantity: int = 0,
    reorder_level: int = 10,
    target_stock_level: Optional[int] = None,
    is_active: bool = True,
    description: str = "",
    created_by=None,
) -> Product:
    """
    Creates and persists a new Product entity with validation.
    Optionally records initial stock transaction if initial units > 0.
    """
    cleaned_sku = sku.strip().upper()
    if Product.objects.filter(sku=cleaned_sku).exists():
        raise ValidationError({'sku': f"A product with SKU '{cleaned_sku}' already exists."})

    product = Product(
        name=name.strip(),
        sku=cleaned_sku,
        category=category,
        supplier=supplier,
        price=price,
        stock_quantity=stock_quantity,
        reorder_level=reorder_level,
        target_stock_level=target_stock_level,
        is_active=is_active,
        description=description.strip() if description else "",
    )
    product.full_clean()
    product.save()

    if stock_quantity > 0:
        InventoryTransaction.objects.create(
            product=product,
            transaction_type=InventoryTransaction.TransactionType.ADD,
            quantity=stock_quantity,
            previous_stock=0,
            new_stock=stock_quantity,
            reference='INITIAL-STOCK',
            notes='Initial stock balance recorded upon SKU creation.',
            created_by=created_by if created_by and created_by.is_authenticated else None,
        )

    return product


@transaction.atomic
def update_product(
    product: Product,
    *,
    name: Optional[str] = None,
    sku: Optional[str] = None,
    category: Optional[Category] = None,
    supplier: Any = _UNSET,
    price: Optional[Decimal] = None,
    stock_quantity: Optional[int] = None,
    reorder_level: Optional[int] = None,
    target_stock_level: Any = _UNSET,
    is_active: Optional[bool] = None,
    description: Optional[str] = None,
) -> Product:
    """
    Updates an existing Product entity.
    """
    if name is not None:
        product.name = name.strip()
    if sku is not None:
        cleaned_sku = sku.strip().upper()
        if Product.objects.filter(sku=cleaned_sku).exclude(pk=product.pk).exists():
            raise ValidationError({'sku': f"A product with SKU '{cleaned_sku}' already exists."})
        product.sku = cleaned_sku
    if category is not None:
        product.category = category
    if supplier is not _UNSET:
        product.supplier = supplier
    if price is not None:
        product.price = price
    if stock_quantity is not None:
        product.stock_quantity = stock_quantity
    if reorder_level is not None:
        product.reorder_level = reorder_level
    if target_stock_level is not _UNSET:
        product.target_stock_level = target_stock_level
    if is_active is not None:
        product.is_active = is_active
    if description is not None:
        product.description = description.strip()

    product.full_clean()
    product.save()
    return product


# ==============================================================================
# Inventory & Stock Movement Operations
# ==============================================================================

@transaction.atomic
def record_stock_movement(
    *,
    product: Product,
    transaction_type: str,
    quantity: int,
    user=None,
    reference: str = "",
    notes: str = "",
    new_stock: Optional[int] = None,
) -> InventoryTransaction:
    """
    Executes an atomic, concurrency-safe stock movement with audit logging.

    Guarantees:
    - ACID transaction: Locks the product row via `select_for_update()`.
    - Non-negative invariant: Rejects removals or adjustments producing negative stock.
    - Audit integrity: Persists an immutable InventoryTransaction record.
    """
    # Concurrency lock on product row to serialize updates and prevent race conditions
    locked_product = Product.objects.select_for_update().get(pk=product.pk)
    previous_stock = locked_product.stock_quantity

    if transaction_type == InventoryTransaction.TransactionType.ADD:
        if quantity <= 0:
            raise ValidationError({'quantity': 'Stock addition quantity must be greater than zero.'})
        calculated_new_stock = previous_stock + quantity
        actual_quantity = quantity

    elif transaction_type == InventoryTransaction.TransactionType.REMOVE:
        if quantity <= 0:
            raise ValidationError({'quantity': 'Stock removal quantity must be greater than zero.'})
        if previous_stock < quantity:
            raise InsufficientStockError(
                f"Insufficient stock for product '{locked_product.name}' (SKU: {locked_product.sku}). "
                f"Requested to remove: {quantity}, Available on hand: {previous_stock}."
            )
        calculated_new_stock = previous_stock - quantity
        actual_quantity = quantity

    elif transaction_type == InventoryTransaction.TransactionType.ADJUSTMENT:
        if new_stock is not None:
            if new_stock < 0:
                raise InvalidStockAdjustmentError('Adjusted stock quantity cannot be negative.')
            calculated_new_stock = new_stock
            actual_quantity = abs(new_stock - previous_stock)
        else:
            # Quantity delta mode
            calculated_new_stock = previous_stock + quantity
            if calculated_new_stock < 0:
                raise InvalidStockAdjustmentError(
                    f"Resulting stock quantity ({calculated_new_stock}) cannot be negative."
                )
            actual_quantity = abs(quantity)
    else:
        raise ValidationError({'transaction_type': f"Invalid transaction type: '{transaction_type}'."})

    # Update product stock quantity
    locked_product.stock_quantity = calculated_new_stock
    locked_product.full_clean()
    locked_product.save(update_fields=['stock_quantity', 'updated_at'])

    # Synchronize passed-in product instance in memory
    product.stock_quantity = calculated_new_stock

    # Create immutable audit transaction record
    tx = InventoryTransaction.objects.create(
        product=locked_product,
        transaction_type=transaction_type,
        quantity=actual_quantity,
        previous_stock=previous_stock,
        new_stock=calculated_new_stock,
        reference=reference.strip() if reference else "",
        notes=notes.strip() if notes else "",
        created_by=user if user and user.is_authenticated else None,
    )
    return tx


@transaction.atomic
def add_stock(
    *,
    product: Product,
    quantity: int,
    user=None,
    reference: str = "",
    notes: str = "",
) -> InventoryTransaction:
    """Convenience service to record incoming stock / replenishment."""
    return record_stock_movement(
        product=product,
        transaction_type=InventoryTransaction.TransactionType.ADD,
        quantity=quantity,
        user=user,
        reference=reference,
        notes=notes,
    )


@transaction.atomic
def remove_stock(
    *,
    product: Product,
    quantity: int,
    user=None,
    reference: str = "",
    notes: str = "",
) -> InventoryTransaction:
    """Convenience service to record outgoing stock / dispatch / wastage."""
    return record_stock_movement(
        product=product,
        transaction_type=InventoryTransaction.TransactionType.REMOVE,
        quantity=quantity,
        user=user,
        reference=reference,
        notes=notes,
    )


@transaction.atomic
def adjust_stock(
    *,
    product: Product,
    new_quantity: int,
    user=None,
    reference: str = "",
    notes: str = "",
) -> InventoryTransaction:
    """Convenience service to calibrate physical stock count following audit."""
    return record_stock_movement(
        product=product,
        transaction_type=InventoryTransaction.TransactionType.ADJUSTMENT,
        quantity=0,
        new_stock=new_quantity,
        user=user,
        reference=reference,
        notes=notes,
    )


@transaction.atomic
def delete_product(product: Product) -> None:
    """
    Deletes a product entity.
    """
    product.delete()


# ==============================================================================
# Category Service Operations
# ==============================================================================

@transaction.atomic
def create_category(
    *,
    name: str,
    description: str = "",
    is_active: bool = True,
) -> Category:
    """
    Creates and persists a new Category entity with validation.
    """
    cleaned_name = name.strip()
    if Category.objects.filter(name__iexact=cleaned_name).exists():
        raise ValidationError({'name': f"A category named '{cleaned_name}' already exists."})

    category = Category(
        name=cleaned_name,
        description=description.strip() if description else "",
        is_active=is_active,
    )
    category.full_clean()
    category.save()
    return category


@transaction.atomic
def update_category(
    category: Category,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Category:
    """
    Updates an existing Category entity.
    """
    if name is not None:
        cleaned_name = name.strip()
        if Category.objects.filter(name__iexact=cleaned_name).exclude(pk=category.pk).exists():
            raise ValidationError({'name': f"A category named '{cleaned_name}' already exists."})
        category.name = cleaned_name
    if description is not None:
        category.description = description.strip()
    if is_active is not None:
        category.is_active = is_active

    category.full_clean()
    category.save()
    return category


@transaction.atomic
def delete_category(category: Category) -> None:
    """
    Safely attempts to delete a category.
    Guards relational integrity: raises ProtectedCategoryError if products reference it.
    """
    product_count = category.products.count()
    if product_count > 0:
        raise ProtectedCategoryError(
            f"Cannot delete category '{category.name}' because it contains {product_count} "
            f"associated product(s). Please reassign or remove these products first."
        )

    try:
        category.delete()
    except models.ProtectedError as exc:
        raise ProtectedCategoryError(
            f"Database protection prevented deletion of category '{category.name}'."
        ) from exc


# ==============================================================================
# Supplier Service Operations
# ==============================================================================

@transaction.atomic
def create_supplier(
    *,
    name: str,
    email: str,
    phone: str,
    contact_person: str = "",
    address: str = "",
    is_active: bool = True,
) -> Supplier:
    """
    Creates and persists a new Supplier entity with validation.
    """
    supplier = Supplier(
        name=name.strip(),
        contact_person=contact_person.strip() if contact_person else "",
        email=email.strip().lower(),
        phone=phone.strip(),
        address=address.strip() if address else "",
        is_active=is_active,
    )
    supplier.full_clean()
    supplier.save()
    return supplier


@transaction.atomic
def update_supplier(
    supplier: Supplier,
    *,
    name: Optional[str] = None,
    contact_person: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    address: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Supplier:
    """
    Updates an existing Supplier entity.
    """
    if name is not None:
        supplier.name = name.strip()
    if contact_person is not None:
        supplier.contact_person = contact_person.strip()
    if email is not None:
        supplier.email = email.strip().lower()
    if phone is not None:
        supplier.phone = phone.strip()
    if address is not None:
        supplier.address = address.strip()
    if is_active is not None:
        supplier.is_active = is_active

    supplier.full_clean()
    supplier.save()
    return supplier


@transaction.atomic
def delete_supplier(supplier: Supplier) -> None:
    """
    Deletes a Supplier entity.
    Foreign key references in Product are set to NULL (on_delete=models.SET_NULL).
    """
    supplier.delete()


# ==============================================================================
# Sales Management Service Operations
# ==============================================================================

class SaleCreationError(DomainServiceError, ValidationError):
    """Raised when sale creation validation or business invariant fails."""
    pass


def generate_order_identifier() -> str:
    """
    Generates a human-readable, unique sale order identifier.
    Format: SALE-YYYYMMDD-XXXX (e.g., SALE-20260918-A7B2C1).
    """
    date_str = timezone.now().strftime('%Y%m%d')
    unique_suffix = uuid.uuid4().hex[:6].upper()
    return f"SALE-{date_str}-{unique_suffix}"


@transaction.atomic
def create_sale(
    *,
    customer_name: str,
    items_data: List[Dict[str, Any]],
    customer_email: str = "",
    customer_phone: str = "",
    sale_date: Optional[Any] = None,
    status: str = Sale.Status.COMPLETED,
    notes: str = "",
    user=None,
    order_identifier: Optional[str] = None,
) -> Sale:
    """
    Creates and records a commercial sales transaction with ACID transactional safety.

    Business Rules & Invariants:
    1. Validation of customer details and non-empty items payload.
    2. Prevention of duplicate items for the same product in a single sale transaction.
    3. Concurrency-Safe Stock Validation:
       - Obtains row-level locks via `Product.objects.select_for_update()` to serialize concurrent orders.
       - Rejects transactions with `InsufficientStockError` if requested units exceed available stock.
       - Prevents invalid, negative, or depleted stock states.
    4. Backend Calculation of Totals:
       - Evaluates line item subtotals as `Decimal(quantity) * Decimal(unit_price)`.
       - Aggregates overall `total_amount` safely on the backend.
    5. Inventory Mutation & Audit Trail:
       - If status is `COMPLETED`, atomically decrements physical `product.stock_quantity`.
       - Records an immutable `InventoryTransaction` of type `REMOVE` referencing the sale identifier.
    """
    # 1. Basic parameter sanitization
    clean_cust_name = customer_name.strip() if customer_name else ""
    if not clean_cust_name:
        raise SaleCreationError({'customer_name': 'Customer name is required.'})

    if not items_data or len(items_data) == 0:
        raise SaleCreationError({'items': 'At least one line item is required to complete a sale.'})

    if not order_identifier:
        # Generate unique identifier with collision fallback
        for _ in range(5):
            candidate_id = generate_order_identifier()
            if not Sale.objects.filter(order_identifier=candidate_id).exists():
                order_identifier = candidate_id
                break
        if not order_identifier:
            order_identifier = f"SALE-{int(timezone.now().timestamp())}"

    # 2. Extract and validate unique product IDs in items_data
    product_quantities: Dict[int, int] = {}
    custom_prices: Dict[int, Optional[Decimal]] = {}

    for index, item in enumerate(items_data):
        product_id = item.get('product_id') or (item.get('product').pk if isinstance(item.get('product'), Product) else None)
        if not product_id:
            raise SaleCreationError({'items': f"Line item #{index + 1} does not specify a valid product."})

        try:
            qty = int(item.get('quantity', 0))
        except (ValueError, TypeError):
            raise SaleCreationError({'items': f"Line item #{index + 1} quantity must be an integer."})

        if qty <= 0:
            raise SaleCreationError({'items': f"Quantity for product must be greater than zero (Item #{index + 1})."})

        if product_id in product_quantities:
            raise SaleCreationError({
                'items': f"Duplicate product line item detected. Please consolidate quantities for the same SKU."
            })

        product_quantities[product_id] = qty

        # Optional custom unit price override (defaulting to product.price if not provided)
        unit_price_val = item.get('unit_price')
        if unit_price_val is not None:
            try:
                dec_price = Decimal(str(unit_price_val))
                if dec_price < Decimal('0.00'):
                    raise SaleCreationError({'items': f"Unit price cannot be negative (Item #{index + 1})."})
                custom_prices[product_id] = dec_price
            except Exception:
                raise SaleCreationError({'items': f"Invalid unit price provided for item #{index + 1}."})
        else:
            custom_prices[product_id] = None

    # 3. Lock products and validate stock availability (SELECT FOR UPDATE)
    locked_products_qs = Product.objects.select_for_update().filter(pk__in=list(product_quantities.keys()))
    locked_products_map = {p.pk: p for p in locked_products_qs}

    # Verify that all requested product IDs exist
    for pid in product_quantities:
        if pid not in locked_products_map:
            raise SaleCreationError({'items': f"Product with ID {pid} was not found."})

    # Validate stock quantities for completed sales
    if status == Sale.Status.COMPLETED:
        insufficient_errors = []
        for pid, requested_qty in product_quantities.items():
            product = locked_products_map[pid]
            if not product.is_active:
                insufficient_errors.append(
                    f"Product '{product.name}' ({product.sku}) is currently inactive and cannot be sold."
                )
            elif product.stock_quantity < requested_qty:
                insufficient_errors.append(
                    f"Insufficient stock for '{product.name}' (SKU: {product.sku}). "
                    f"Requested: {requested_qty}, Available: {product.stock_quantity}."
                )

        if insufficient_errors:
            raise InsufficientStockError("; ".join(insufficient_errors))

    # 4. Compute totals and line item structures safely on backend
    line_items_to_create = []
    total_amount = Decimal('0.00')

    for pid, qty in product_quantities.items():
        product = locked_products_map[pid]
        unit_price = custom_prices[pid] if custom_prices[pid] is not None else product.price
        line_subtotal = Decimal(str(qty)) * Decimal(str(unit_price))
        total_amount += line_subtotal

        line_items_to_create.append({
            'product': product,
            'quantity': qty,
            'unit_price': unit_price,
            'subtotal': line_subtotal,
        })

    # 5. Create Sale header
    sale = Sale(
        order_identifier=order_identifier,
        customer_name=clean_cust_name,
        customer_email=customer_email.strip().lower() if customer_email else "",
        customer_phone=customer_phone.strip() if customer_phone else "",
        sale_date=sale_date if sale_date else timezone.now(),
        status=status,
        total_amount=total_amount,
        notes=notes.strip() if notes else "",
        created_by=user if user and user.is_authenticated else None,
    )
    sale.full_clean()
    sale.save()

    # 6. Create SaleItems & update inventory stock + audit ledger
    for item_info in line_items_to_create:
        product = item_info['product']
        qty = item_info['quantity']

        SaleItem.objects.create(
            sale=sale,
            product=product,
            quantity=qty,
            unit_price=item_info['unit_price'],
            subtotal=item_info['subtotal'],
        )

        if status == Sale.Status.COMPLETED:
            previous_stock = product.stock_quantity
            new_stock = previous_stock - qty

            # Invariant assertion
            if new_stock < 0:
                raise InsufficientStockError(
                    f"Critical invariant violation: resulting stock cannot be negative for {product.sku}."
                )

            product.stock_quantity = new_stock
            product.full_clean()
            product.save(update_fields=['stock_quantity', 'updated_at'])

            # Record stock movement audit trail
            InventoryTransaction.objects.create(
                product=product,
                transaction_type=InventoryTransaction.TransactionType.REMOVE,
                quantity=qty,
                previous_stock=previous_stock,
                new_stock=new_stock,
                reference=sale.order_identifier,
                notes=f"Order fulfillment: {qty} units sold to {sale.customer_name}.",
                created_by=user if user and user.is_authenticated else None,
            )

    return sale


# ==============================================================================
# Purchase Order Service Operations
# ==============================================================================

class PurchaseOrderError(DomainServiceError, ValidationError):
    """Raised when purchase order validation or business invariant fails."""
    pass


def generate_po_identifier() -> str:
    """
    Generates a human-readable, unique purchase order identifier.
    Format: PO-YYYYMMDD-XXXX (e.g., PO-20260918-A7B2C1).
    """
    date_str = timezone.now().strftime('%Y%m%d')
    unique_suffix = uuid.uuid4().hex[:6].upper()
    return f"PO-{date_str}-{unique_suffix}"


@transaction.atomic
def create_purchase_order(
    *,
    supplier: Supplier,
    items_data: List[Dict[str, Any]],
    status: str = PurchaseOrder.Status.DRAFT,
    notes: str = "",
    user=None,
) -> PurchaseOrder:
    """
    Creates and records a commercial purchase order transaction.

    Business Rules & Invariants:
    1. Validation of supplier and non-empty items payload.
    2. Prevention of duplicate items for the same product.
    3. Backend Calculation of Totals:
       - Evaluates line item subtotals as `Decimal(quantity) * Decimal(unit_cost)`.
       - Aggregates overall `total_amount` safely on the backend.
    """
    if not items_data or len(items_data) == 0:
        raise PurchaseOrderError({'items': 'At least one line item is required to create a purchase order.'})

    if not supplier.is_active:
        raise PurchaseOrderError({'supplier': f"Cannot create purchase order for inactive supplier '{supplier.name}'."})

    order_number = None
    for _ in range(5):
        candidate_id = generate_po_identifier()
        if not PurchaseOrder.objects.filter(order_number=candidate_id).exists():
            order_number = candidate_id
            break
    if not order_number:
        order_number = f"PO-{int(timezone.now().timestamp())}"

    product_quantities: Dict[int, int] = {}
    unit_costs: Dict[int, Decimal] = {}

    for index, item in enumerate(items_data):
        product_id = item.get('product_id') or (item.get('product').pk if isinstance(item.get('product'), Product) else None)
        if not product_id:
            raise PurchaseOrderError({'items': f"Line item #{index + 1} does not specify a valid product."})

        try:
            qty = int(item.get('quantity', 0))
        except (ValueError, TypeError):
            raise PurchaseOrderError({'items': f"Line item #{index + 1} quantity must be an integer."})

        if qty <= 0:
            raise PurchaseOrderError({'items': f"Quantity for product must be greater than zero (Item #{index + 1})."})

        if product_id in product_quantities:
            raise PurchaseOrderError({
                'items': f"Duplicate product line item detected. Please consolidate quantities for the same SKU."
            })

        product_quantities[product_id] = qty

        unit_cost_val = item.get('unit_cost')
        if unit_cost_val is None:
            raise PurchaseOrderError({'items': f"Unit cost is required for item #{index + 1}."})

        try:
            dec_cost = Decimal(str(unit_cost_val))
            if dec_cost < Decimal('0.00'):
                raise PurchaseOrderError({'items': f"Unit cost cannot be negative (Item #{index + 1})."})
            unit_costs[product_id] = dec_cost
        except Exception:
            raise PurchaseOrderError({'items': f"Invalid unit cost provided for item #{index + 1}."})

    products_qs = Product.objects.filter(pk__in=list(product_quantities.keys()))
    products_map = {p.pk: p for p in products_qs}

    for pid in product_quantities:
        if pid not in products_map:
            raise PurchaseOrderError({'items': f"Product with ID {pid} was not found."})

    line_items_to_create = []
    total_amount = Decimal('0.00')

    for pid, qty in product_quantities.items():
        product = products_map[pid]
        unit_cost = unit_costs[pid]
        line_subtotal = Decimal(str(qty)) * unit_cost
        total_amount += line_subtotal

        line_items_to_create.append({
            'product': product,
            'quantity': qty,
            'unit_cost': unit_cost,
            'subtotal': line_subtotal,
        })

    po = PurchaseOrder(
        order_number=order_number,
        supplier=supplier,
        status=status,
        total_amount=total_amount,
        notes=notes.strip() if notes else "",
        created_by=user if user and user.is_authenticated else None,
    )
    po.full_clean()
    po.save()

    for item_info in line_items_to_create:
        PurchaseOrderItem.objects.create(
            purchase_order=po,
            product=item_info['product'],
            quantity=item_info['quantity'],
            unit_cost=item_info['unit_cost'],
            subtotal=item_info['subtotal'],
        )

    return po
@transaction.atomic
def update_purchase_order_status(
    po: PurchaseOrder,
    new_status: str,
    user=None
) -> PurchaseOrder:
    """
    Update Purchase Order status following the allowed lifecycle.

    Draft -> Pending -> Approved -> Received
    Draft/Pending/Approved -> Cancelled

    When an order becomes Received, inventory is updated atomically.
    Serializes status changes via select_for_update row lock on the PurchaseOrder.
    """
    # Concurrency lock on PurchaseOrder row to serialize status transitions
    po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)

    if po.status == new_status:
        return po

    allowed_transitions = {
        PurchaseOrder.Status.DRAFT: {
            PurchaseOrder.Status.PENDING,
            PurchaseOrder.Status.CANCELLED,
        },
        PurchaseOrder.Status.PENDING: {
            PurchaseOrder.Status.APPROVED,
            PurchaseOrder.Status.CANCELLED,
        },
        PurchaseOrder.Status.APPROVED: {
            PurchaseOrder.Status.RECEIVED,
            PurchaseOrder.Status.CANCELLED,
        },
        PurchaseOrder.Status.RECEIVED: set(),
        PurchaseOrder.Status.CANCELLED: set(),
    }

    if new_status not in PurchaseOrder.Status.values:
        raise PurchaseOrderError("Invalid purchase order status.")

    if new_status not in allowed_transitions.get(po.status, set()):
        raise PurchaseOrderError(
            f"Cannot change purchase order status from "
            f"{po.get_status_display()} to "
            f"{po.__class__.Status(new_status).label}."
        )

    # Invariant: Inactive suppliers cannot receive active status advancements
    if new_status in (PurchaseOrder.Status.PENDING, PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.RECEIVED):
        if not po.supplier.is_active:
            raise PurchaseOrderError(
                f"Cannot advance purchase order for inactive supplier '{po.supplier.name}'."
            )

    if new_status == PurchaseOrder.Status.RECEIVED:
        po_items = po.items.all().select_related('product')
        product_ids = [item.product_id for item in po_items]

        locked_products = (
            Product.objects
            .select_for_update()
            .filter(pk__in=product_ids)
        )

        locked_products_map = {
            product.pk: product
            for product in locked_products
        }

        for item in po_items:
            product = locked_products_map[item.product_id]

            previous_stock = product.stock_quantity
            new_stock = previous_stock + item.quantity

            product.stock_quantity = new_stock
            product.full_clean()
            product.save(update_fields=['stock_quantity', 'updated_at'])

            InventoryTransaction.objects.create(
                product=product,
                transaction_type=InventoryTransaction.TransactionType.ADD,
                quantity=item.quantity,
                previous_stock=previous_stock,
                new_stock=new_stock,
                reference=po.order_number,
                notes=(
                    f"Purchase order received: "
                    f"{item.quantity} units from {po.supplier.name}."
                ),
                created_by=(
                    user if user and user.is_authenticated else None
                ),
            )

    po.status = new_status
    po.full_clean()
    po.save(update_fields=['status', 'updated_at'])

    return po


