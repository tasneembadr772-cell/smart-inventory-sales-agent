"""
Authentication, Profile, and RBAC Protected Views.

Adheres to Django best practices:
- Uses Django's authentication and messages framework
- Explicit CSRF protection on forms
- Role enforcement decorators preventing horizontal and vertical privilege escalation
- Strict request.user binding for profile operations
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .forms import UserRegistrationForm, UserLoginForm, UserProfileUpdateForm
from .models import User
from .permissions import role_required, admin_required, manager_required
from .services import get_role_badge_info


@require_http_methods(['GET', 'POST'])
def register_view(request):
    """
    User self-registration view.
    Assigns STANDARD role by default. Redirects authenticated users.
    """
    if request.user.is_authenticated:
        return redirect('authentication:dashboard')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(
                request,
                f"Welcome to NexusERP, {user.username}! Your account has been registered with Standard User access."
            )
            return redirect('authentication:dashboard')
        else:
            messages.error(request, "Please correct the errors below to complete your registration.")
    else:
        form = UserRegistrationForm()

    return render(request, 'authentication/register.html', {'form': form})


@require_http_methods(['GET', 'POST'])
def login_view(request):
    """
    Authentication login view using secure password verification.
    """
    if request.user.is_authenticated:
        return redirect('authentication:dashboard')

    redirect_to = request.GET.get('next') or settings.LOGIN_REDIRECT_URL

    if request.method == 'POST':
        form = UserLoginForm(request=request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            messages.success(
                request,
                f"Welcome back, {user.get_full_name() or user.username}! "
                f"Logged in as {user.get_role_display()}."
            )
            return redirect(redirect_to)
        else:
            messages.error(request, "Invalid username or password. Please try again.")
    else:
        form = UserLoginForm(request=request)

    return render(request, 'authentication/login.html', {
        'form': form,
        'next': redirect_to,
    })


@require_http_methods(['GET', 'POST'])
def logout_view(request):
    """
    Terminates user session and redirects to login.
    Handles POST requests with CSRF protection, and gracefully logs out on GET.
    """
    if request.user.is_authenticated:
        username = request.user.username
        auth_logout(request)
        messages.info(request, f"Goodbye, {username}. You have been successfully logged out.")
    return redirect('authentication:login')


@login_required
@require_http_methods(['GET', 'POST'])
def profile_view(request):
    """
    Profile management view.

    Security Guarantee:
    - Binds strictly to request.user.
    - Prevents horizontal privilege escalation by never accepting a target user_id.
    - Prevents vertical privilege escalation by using UserProfileUpdateForm which
      excludes role and permissions.
    """
    user = request.user
    role_meta = get_role_badge_info(user.role)

    if request.method == 'POST':
        form = UserProfileUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile information has been successfully updated.")
            return redirect('authentication:profile')
        else:
            messages.error(request, "Please correct the errors in the profile form.")
    else:
        form = UserProfileUpdateForm(instance=user)

    return render(request, 'authentication/profile.html', {
        'form': form,
        'user': user,
        'role_meta': role_meta,
    })


@login_required
def dashboard_view(request):
    """
    Central authenticated dashboard.
    Visualizes user permissions, RBAC role boundaries, and key inventory metrics.
    """
    from apps.domain_app import selectors as domain_selectors

    user = request.user
    role_meta = get_role_badge_info(user.role)
    kpis = domain_selectors.get_inventory_kpis()
    low_stock_items = domain_selectors.get_low_stock_products(user=request.user, include_out_of_stock=True)[:5]

    return render(request, 'authentication/dashboard.html', {
        'user': user,
        'role_meta': role_meta,
        'kpis': kpis,
        'low_stock_items': low_stock_items,
    })


@manager_required
def manager_area_view(request):
    """
    Protected endpoint accessible ONLY to Manager and Admin roles.
    Standard Users will receive HTTP 403 Forbidden.
    """
    return render(request, 'authentication/manager_area.html', {
        'user': request.user,
        'role_meta': get_role_badge_info(request.user.role),
    })


@admin_required
def admin_area_view(request):
    """
    Protected endpoint accessible ONLY to Admin users.
    Both Managers and Standard Users will receive HTTP 403 Forbidden.
    """
    return render(request, 'authentication/admin_area.html', {
        'user': request.user,
        'role_meta': get_role_badge_info(request.user.role),
    })
