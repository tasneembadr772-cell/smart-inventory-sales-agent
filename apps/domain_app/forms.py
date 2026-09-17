"""
Forms for Inventory Product and Category Management.

Provides HTML widget styling, validation error mapping, and form sanitation.
"""

from decimal import Decimal
from django import forms
from django.db import models
from .models import Category, Product, Supplier


class SupplierForm(forms.ModelForm):
    """Form for creating and updating Suppliers."""

    class Meta:
        model = Supplier
        fields = [
            'name',
            'contact_person',
            'email',
            'phone',
            'address',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g., Apex Global Components Ltd.',
                'required': True,
                'autocomplete': 'off',
            }),
            'contact_person': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g., John Smith (Lead Account Executive)',
                'autocomplete': 'off',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g., supplier@apexcomponents.com',
                'required': True,
                'autocomplete': 'off',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g., +1 (555) 234-5678',
                'required': True,
                'autocomplete': 'off',
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 3,
                'placeholder': 'Factory, distribution warehouse, or physical address...',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-checkbox',
            }),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError("Supplier name cannot be empty.")
        return name

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise forms.ValidationError("Supplier email cannot be empty.")
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if not phone:
            raise forms.ValidationError("Supplier phone number cannot be empty.")
        return phone


class CategoryForm(forms.ModelForm):
    """Form for creating and updating Categories."""

    class Meta:
        model = Category
        fields = ['name', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g., Electronics, Audio Equipment',
                'required': True,
                'autocomplete': 'off',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 4,
                'placeholder': 'Describe this category taxonomy and scope...',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-checkbox',
            }),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError("Category name cannot be empty.")
        
        # Check uniqueness case-insensitively
        qs = Category.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"A category named '{name}' already exists.")
        return name


class ProductForm(forms.ModelForm):
    """Form for creating and updating Products."""

    class Meta:
        model = Product
        fields = [
            'name',
            'sku',
            'category',
            'supplier',
            'price',
            'stock_quantity',
            'reorder_level',
            'is_active',
            'description',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g., Wireless Mechanical Keyboard',
                'required': True,
            }),
            'sku': forms.TextInput(attrs={
                'class': 'form-input font-mono',
                'placeholder': 'e.g., KB-MECH-001',
                'required': True,
                'autocomplete': 'off',
            }),
            'category': forms.Select(attrs={
                'class': 'form-select',
                'required': True,
            }),
            'supplier': forms.Select(attrs={
                'class': 'form-select',
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.01',
                'min': '0.00',
                'placeholder': '0.00',
                'required': True,
            }),
            'stock_quantity': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0',
                'step': '1',
                'placeholder': '0',
                'required': True,
            }),
            'reorder_level': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0',
                'step': '1',
                'placeholder': '10',
                'required': True,
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 4,
                'placeholder': 'Detailed specifications, dimensions, features...',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-checkbox',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # When creating a product, only offer active categories.
        # When editing, also permit the currently assigned category even if inactive.
        if self.instance.pk and self.instance.category_id:
            self.fields['category'].queryset = Category.objects.filter(
                models.Q(is_active=True) | models.Q(pk=self.instance.category_id)
            )
        else:
            self.fields['category'].queryset = Category.objects.filter(is_active=True)

        # Supplier choice configuration
        self.fields['supplier'].required = False
        self.fields['supplier'].empty_label = 'No Supplier (Direct / Internal)'
        if self.instance.pk and self.instance.supplier_id:
            self.fields['supplier'].queryset = Supplier.objects.filter(
                models.Q(is_active=True) | models.Q(pk=self.instance.supplier_id)
            )
        else:
            self.fields['supplier'].queryset = Supplier.objects.filter(is_active=True)

    def clean_sku(self):
        sku = self.cleaned_data.get('sku', '').strip().upper()
        if not sku:
            raise forms.ValidationError("SKU cannot be empty.")
        qs = Product.objects.filter(sku=sku)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"A product with SKU '{sku}' already exists.")
        return sku

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None and price < Decimal('0.00'):
            raise forms.ValidationError("Price must be greater than or equal to 0.00.")
        return price

    def clean_stock_quantity(self):
        stock = self.cleaned_data.get('stock_quantity')
        if stock is not None and stock < 0:
            raise forms.ValidationError("Stock quantity cannot be negative.")
        return stock

    def clean_reorder_level(self):
        level = self.cleaned_data.get('reorder_level')
        if level is not None and level < 0:
            raise forms.ValidationError("Reorder level cannot be negative.")
        return level


class ProductFilterForm(forms.Form):
    """GET Filter form for product listings."""
    STOCK_STATUS_CHOICES = [
        ('', 'All Stock Levels'),
        ('in_stock', 'In Stock'),
        ('low_stock', 'Low Stock Alert'),
        ('out_of_stock', 'Out of Stock'),
    ]

    STATUS_CHOICES = [
        ('', 'All Statuses'),
        ('active', 'Active Only'),
        ('inactive', 'Inactive Only'),
    ]

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'search-input',
            'placeholder': 'Search by Name, SKU, or Description...',
            'autocomplete': 'off',
            'id': 'productSearchInput',
        })
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        empty_label='All Categories',
        widget=forms.Select(attrs={
            'class': 'filter-select',
            'id': 'categoryFilterSelect',
        })
    )
    stock_status = forms.ChoiceField(
        choices=STOCK_STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'filter-select',
            'id': 'stockFilterSelect',
        })
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'filter-select',
            'id': 'statusFilterSelect',
        })
    )


class SupplierFilterForm(forms.Form):
    """GET Filter form for supplier catalog listings."""
    STATUS_CHOICES = [
        ('', 'All Statuses'),
        ('active', 'Active Only'),
        ('inactive', 'Inactive Only'),
    ]

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'search-input',
            'placeholder': 'Search by Name, Contact, Email, Phone...',
            'autocomplete': 'off',
            'id': 'supplierSearchInput',
        })
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'filter-select',
            'id': 'statusFilterSelect',
        })
    )

