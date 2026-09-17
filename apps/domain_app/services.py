"""
Domain Services for Inventory & Sales Management System.

Handles domain write operations, business rule enforcement, and transactional integrity.
Encapsulates mutations away from views to satisfy clean architecture requirements.
"""

from decimal import Decimal
from typing import Optional, Dict, Any
from django.core.exceptions import ValidationError
from django.db import transaction, models

from .models import Category, Product, Supplier, InventoryTransaction

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

