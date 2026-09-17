"""
Domain Services for Inventory & Sales Management System.

Handles domain write operations, business rule enforcement, and transactional integrity.
Encapsulates mutations away from views to satisfy clean architecture requirements.
"""

from decimal import Decimal
from typing import Optional, Dict, Any
from django.core.exceptions import ValidationError
from django.db import transaction, models

from .models import Category, Product, Supplier

_UNSET = object()


class DomainServiceError(Exception):
    """Base exception for domain business logic failures."""
    pass


class ProtectedCategoryError(DomainServiceError):
    """Raised when an attempt is made to delete a category that still contains products."""
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
    is_active: bool = True,
    description: str = "",
) -> Product:
    """
    Creates and persists a new Product entity with validation.
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
        is_active=is_active,
        description=description.strip() if description else "",
    )
    product.full_clean()
    product.save()
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
    if is_active is not None:
        product.is_active = is_active
    if description is not None:
        product.description = description.strip()

    product.full_clean()
    product.save()
    return product


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

