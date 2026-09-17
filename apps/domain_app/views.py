"""
Views for Inventory Product and Category Management.

Adheres strictly to the MVT architecture with separation of concerns:
- Delegates read logic and query optimization to `selectors.py`
- Delegates write operations and transaction boundaries to `services.py`
- Enforces Role-Based Access Control (RBAC) via authentication decorators
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

from apps.authentication.permissions import admin_required, manager_required
from .forms import ProductForm, CategoryForm, ProductFilterForm, SupplierForm, SupplierFilterForm
from .models import Product, Category, Supplier
from . import selectors, services


# ==============================================================================
# Product Views
# ==============================================================================

@login_required(login_url=settings.LOGIN_URL)
@require_http_methods(["GET"])
def product_list(request):
    """
    Renders product inventory catalog with search, filtering, pagination, and KPIs.
    Accessible to all authenticated users (Admin, Manager, Standard User).
    """
    filter_form = ProductFilterForm(request.GET)
    search_query = request.GET.get('search', '').strip()
    category_id = request.GET.get('category', '').strip()
    stock_status = request.GET.get('stock_status', '').strip()
    status_filter = request.GET.get('status', '').strip()

    # Query products via selector (enforcing RBAC visibility and N+1 prevention)
    products_qs = selectors.get_products_queryset(
        user=request.user,
        search=search_query,
        category_id=category_id if category_id else None,
        stock_status=stock_status if stock_status else None,
        status_filter=status_filter if status_filter else None,
    )

    # Paginate results (20 products per page)
    paginator = Paginator(products_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Inventory KPIs for metric summary cards
    kpis = selectors.get_inventory_kpis()
    categories = selectors.get_categories_queryset(include_inactive=False)

    context = {
        'page_obj': page_obj,
        'products': page_obj.object_list,
        'filter_form': filter_form,
        'kpis': kpis,
        'categories': categories,
        'search_query': search_query,
        'selected_category': category_id,
        'selected_stock': stock_status,
        'selected_status': status_filter,
    }
    return render(request, 'domain_app/product_list.html', context)


@login_required(login_url=settings.LOGIN_URL)
@require_http_methods(["GET"])
def product_detail(request, pk: int):
    """
    Displays full details of a specific inventory product.
    Accessible to all authenticated users (subject to visibility rules).
    """
    product = selectors.get_product_by_id(product_id=pk, user=request.user)
    context = {
        'product': product,
    }
    return render(request, 'domain_app/product_detail.html', context)


@manager_required
@require_http_methods(["GET", "POST"])
def product_create(request):
    """
    Creates a new Product.
    Restricted to Managers and Admins.
    """
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            try:
                product = services.create_product(
                    name=form.cleaned_data['name'],
                    sku=form.cleaned_data['sku'],
                    category=form.cleaned_data['category'],
                    supplier=form.cleaned_data.get('supplier'),
                    price=form.cleaned_data['price'],
                    stock_quantity=form.cleaned_data['stock_quantity'],
                    reorder_level=form.cleaned_data['reorder_level'],
                    is_active=form.cleaned_data['is_active'],
                    description=form.cleaned_data['description'],
                )
                messages.success(request, f"Product '{product.name}' (SKU: {product.sku}) created successfully.")
                return redirect('domain_app:product_detail', pk=product.pk)
            except ValidationError as err:
                for field, error_list in err.message_dict.items():
                    for error in error_list:
                        form.add_error(field if field in form.fields else None, error)
    else:
        form = ProductForm()

    context = {
        'form': form,
        'title': 'Create New Product',
        'is_edit': False,
    }
    return render(request, 'domain_app/product_form.html', context)


@manager_required
@require_http_methods(["GET", "POST"])
def product_update(request, pk: int):
    """
    Updates an existing Product.
    Restricted to Managers and Admins.
    """
    product = selectors.get_product_by_id(product_id=pk)

    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            try:
                services.update_product(
                    product,
                    name=form.cleaned_data['name'],
                    sku=form.cleaned_data['sku'],
                    category=form.cleaned_data['category'],
                    supplier=form.cleaned_data.get('supplier'),
                    price=form.cleaned_data['price'],
                    stock_quantity=form.cleaned_data['stock_quantity'],
                    reorder_level=form.cleaned_data['reorder_level'],
                    is_active=form.cleaned_data['is_active'],
                    description=form.cleaned_data['description'],
                )
                messages.success(request, f"Product '{product.name}' updated successfully.")
                return redirect('domain_app:product_detail', pk=product.pk)
            except ValidationError as err:
                for field, error_list in err.message_dict.items():
                    for error in error_list:
                        form.add_error(field if field in form.fields else None, error)
    else:
        form = ProductForm(instance=product)

    context = {
        'form': form,
        'product': product,
        'title': f"Edit Product: {product.name}",
        'is_edit': True,
    }
    return render(request, 'domain_app/product_form.html', context)


@admin_required
@require_http_methods(["GET", "POST"])
def product_delete(request, pk: int):
    """
    Deletes an inventory Product.
    Strictly restricted to Admins.
    """
    product = selectors.get_product_by_id(product_id=pk)

    if request.method == 'POST':
        product_name = product.name
        product_sku = product.sku
        services.delete_product(product)
        messages.success(request, f"Product '{product_name}' (SKU: {product_sku}) was permanently deleted.")
        return redirect('domain_app:product_list')

    context = {
        'product': product,
    }
    return render(request, 'domain_app/product_confirm_delete.html', context)


# ==============================================================================
# Category Views
# ==============================================================================

@login_required(login_url=settings.LOGIN_URL)
@require_http_methods(["GET"])
def category_list(request):
    """
    Lists product categories with item count metrics.
    Accessible to all authenticated users.
    """
    search_query = request.GET.get('search', '').strip()
    categories = selectors.get_categories_queryset(
        include_inactive=request.user.is_superuser or request.user.role in ('ADMIN', 'MANAGER'),
        search=search_query,
    )
    context = {
        'categories': categories,
        'search_query': search_query,
    }
    return render(request, 'domain_app/category_list.html', context)


@manager_required
@require_http_methods(["GET", "POST"])
def category_create(request):
    """
    Creates a new Category entity.
    Restricted to Managers and Admins.
    """
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            try:
                category = services.create_category(
                    name=form.cleaned_data['name'],
                    description=form.cleaned_data['description'],
                    is_active=form.cleaned_data['is_active'],
                )
                messages.success(request, f"Category '{category.name}' created successfully.")
                return redirect('domain_app:category_list')
            except ValidationError as err:
                for field, error_list in err.message_dict.items():
                    for error in error_list:
                        form.add_error(field if field in form.fields else None, error)
    else:
        form = CategoryForm()

    context = {
        'form': form,
        'title': 'Create Category',
        'is_edit': False,
    }
    return render(request, 'domain_app/category_form.html', context)


@manager_required
@require_http_methods(["GET", "POST"])
def category_update(request, pk: int):
    """
    Updates an existing Category entity.
    Restricted to Managers and Admins.
    """
    category = selectors.get_category_by_id(category_id=pk)

    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            try:
                services.update_category(
                    category,
                    name=form.cleaned_data['name'],
                    description=form.cleaned_data['description'],
                    is_active=form.cleaned_data['is_active'],
                )
                messages.success(request, f"Category '{category.name}' updated successfully.")
                return redirect('domain_app:category_list')
            except ValidationError as err:
                for field, error_list in err.message_dict.items():
                    for error in error_list:
                        form.add_error(field if field in form.fields else None, error)
    else:
        form = CategoryForm(instance=category)

    context = {
        'form': form,
        'category': category,
        'title': f"Edit Category: {category.name}",
        'is_edit': True,
    }
    return render(request, 'domain_app/category_form.html', context)


@admin_required
@require_http_methods(["GET", "POST"])
def category_delete(request, pk: int):
    """
    Deletes a Category entity.
    Strictly restricted to Admins.
    Guards against deleting categories referencing existing products.
    """
    category = selectors.get_category_by_id(category_id=pk)

    if request.method == 'POST':
        try:
            category_name = category.name
            services.delete_category(category)
            messages.success(request, f"Category '{category_name}' was deleted successfully.")
            return redirect('domain_app:category_list')
        except services.ProtectedCategoryError as err:
            messages.error(request, str(err))
            return redirect('domain_app:category_list')

    context = {
        'category': category,
        'product_count': category.products.count(),
    }
    return render(request, 'domain_app/category_confirm_delete.html', context)


# ==============================================================================
# Supplier Views
# ==============================================================================

@login_required(login_url=settings.LOGIN_URL)
@require_http_methods(["GET"])
def supplier_list(request):
    """
    Renders supplier catalog with search, status filtering, and KPIs.
    Accessible to all authenticated users (Admin, Manager, Standard User).
    """
    filter_form = SupplierFilterForm(request.GET)
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()

    suppliers_qs = selectors.get_suppliers_queryset(
        user=request.user,
        search=search_query,
        status_filter=status_filter if status_filter else None,
    )

    paginator = Paginator(suppliers_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    kpis = selectors.get_supplier_kpis()

    context = {
        'page_obj': page_obj,
        'suppliers': page_obj.object_list,
        'filter_form': filter_form,
        'kpis': kpis,
        'search_query': search_query,
        'selected_status': status_filter,
    }
    return render(request, 'domain_app/supplier_list.html', context)


@login_required(login_url=settings.LOGIN_URL)
@require_http_methods(["GET"])
def supplier_detail(request, pk: int):
    """
    Displays full details of a specific supplier and its linked products.
    Accessible to all authenticated users.
    """
    supplier = selectors.get_supplier_by_id(supplier_id=pk, user=request.user)
    context = {
        'supplier': supplier,
        'products': supplier.products.all(),
    }
    return render(request, 'domain_app/supplier_detail.html', context)


@manager_required
@require_http_methods(["GET", "POST"])
def supplier_create(request):
    """
    Creates a new Supplier entity.
    Restricted to Managers and Admins (RBAC). Standard users receive 403 Forbidden.
    """
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            try:
                supplier = services.create_supplier(
                    name=form.cleaned_data['name'],
                    contact_person=form.cleaned_data.get('contact_person', ''),
                    email=form.cleaned_data['email'],
                    phone=form.cleaned_data['phone'],
                    address=form.cleaned_data.get('address', ''),
                    is_active=form.cleaned_data.get('is_active', True),
                )
                messages.success(request, f"Supplier '{supplier.name}' created successfully.")
                return redirect('domain_app:supplier_detail', pk=supplier.pk)
            except ValidationError as err:
                for field, error_list in err.message_dict.items():
                    for error in error_list:
                        form.add_error(field if field in form.fields else None, error)
    else:
        form = SupplierForm()

    context = {
        'form': form,
        'title': 'Add New Supplier',
        'is_edit': False,
    }
    return render(request, 'domain_app/supplier_form.html', context)


@manager_required
@require_http_methods(["GET", "POST"])
def supplier_update(request, pk: int):
    """
    Updates an existing Supplier entity.
    Restricted to Managers and Admins (RBAC). Standard users receive 403 Forbidden.
    """
    supplier = selectors.get_supplier_by_id(supplier_id=pk)

    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            try:
                services.update_supplier(
                    supplier,
                    name=form.cleaned_data['name'],
                    contact_person=form.cleaned_data.get('contact_person', ''),
                    email=form.cleaned_data['email'],
                    phone=form.cleaned_data['phone'],
                    address=form.cleaned_data.get('address', ''),
                    is_active=form.cleaned_data.get('is_active', True),
                )
                messages.success(request, f"Supplier '{supplier.name}' updated successfully.")
                return redirect('domain_app:supplier_detail', pk=supplier.pk)
            except ValidationError as err:
                for field, error_list in err.message_dict.items():
                    for error in error_list:
                        form.add_error(field if field in form.fields else None, error)
    else:
        form = SupplierForm(instance=supplier)

    context = {
        'form': form,
        'supplier': supplier,
        'title': f"Edit Supplier: {supplier.name}",
        'is_edit': True,
    }
    return render(request, 'domain_app/supplier_form.html', context)


@manager_required
@require_http_methods(["GET", "POST"])
def supplier_delete(request, pk: int):
    """
    Deletes a Supplier entity.
    Restricted to Managers and Admins (RBAC). Standard users receive 403 Forbidden.
    Products referencing this supplier will have their foreign key set to NULL.
    """
    supplier = selectors.get_supplier_by_id(supplier_id=pk)

    if request.method == 'POST':
        supplier_name = supplier.name
        services.delete_supplier(supplier)
        messages.success(request, f"Supplier '{supplier_name}' was deleted successfully.")
        return redirect('domain_app:supplier_list')

    context = {
        'supplier': supplier,
        'product_count': supplier.products.count(),
    }
    return render(request, 'domain_app/supplier_confirm_delete.html', context)

