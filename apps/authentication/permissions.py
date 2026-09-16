"""
Role-Based Access Control (RBAC) Permission Decorators and Mixins.

Enforces role restrictions across views to prevent unauthorized access
and both horizontal and vertical privilege escalation.
"""

from functools import wraps
from django.conf import settings
from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def role_required(*allowed_roles):
    """
    Decorator for views that checks if a user is logged in and possesses
    at least one of the specified roles (or is a superuser).

    - If user is NOT authenticated: Redirects to login page with `next` query parameter.
    - If user IS authenticated but lacks role: Raises PermissionDenied (HTTP 403 Forbidden).
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(
                    request.get_full_path(),
                    login_url=settings.LOGIN_URL
                )

            # Check if user has an allowed role or is superuser
            if request.user.is_superuser or request.user.role in allowed_roles:
                return view_func(request, *args, **kwargs)

            # Violation of role boundary -> HTTP 403 Forbidden
            raise PermissionDenied(
                f"Access denied. This action requires one of the following roles: "
                f"{', '.join(allowed_roles)}. Your current role is: {request.user.get_role_display()}."
            )

        return _wrapped_view
    return decorator


def admin_required(view_func):
    """Decorator restricting access exclusively to Admin users or superusers."""
    from .models import User
    return role_required(User.Role.ADMIN)(view_func)


def manager_required(view_func):
    """Decorator restricting access to Manager and Admin users."""
    from .models import User
    return role_required(User.Role.ADMIN, User.Role.MANAGER)(view_func)


class RoleRequiredMixin(AccessMixin):
    """
    CBV mixin verifying that the current user has one of the allowed roles.
    """
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not (request.user.is_superuser or request.user.role in self.allowed_roles):
            raise PermissionDenied(
                f"Access denied. Allowed roles: {', '.join(self.allowed_roles)}. "
                f"Your role: {request.user.get_role_display()}."
            )

        return super().dispatch(request, *args, **kwargs)
