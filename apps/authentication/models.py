"""
Custom User and Authentication Models for Inventory & Sales Management System.

Follows Django best practices for custom user models using AbstractUser.
Implements Role-Based Access Control (RBAC) with 3 primary roles:
- ADMIN: Full system administration and privilege management
- MANAGER: Inventory and operational oversight
- STANDARD: Standard user for regular operations
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model providing secure identity and role-based access control.
    """

    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        MANAGER = 'MANAGER', 'Manager'
        STANDARD = 'STANDARD', 'Standard User'

    email = models.EmailField(
        'email address',
        unique=True,
        error_messages={
            'unique': 'A user with that email address already exists.',
        },
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STANDARD,
        db_index=True,
        help_text='System role determining access permissions across the platform.',
    )

    phone_number = models.CharField(
        max_length=25,
        blank=True,
        default='',
        help_text='Contact phone number.',
    )

    bio = models.TextField(
        max_length=500,
        blank=True,
        default='',
        help_text='Short profile bio.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-date_joined']

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    # --------------------------------------------------------------------------
    # RBAC Convenience Properties & Methods
    # --------------------------------------------------------------------------

    @property
    def is_admin_role(self) -> bool:
        """Returns True if user has Admin role or is a superuser."""
        return self.is_authenticated and (self.role == self.Role.ADMIN or self.is_superuser)

    @property
    def is_manager_role(self) -> bool:
        """Returns True if user has Manager role."""
        return self.is_authenticated and self.role == self.Role.MANAGER

    @property
    def is_standard_role(self) -> bool:
        """Returns True if user has Standard User role."""
        return self.is_authenticated and self.role == self.Role.STANDARD

    def has_role(self, *allowed_roles) -> bool:
        """Check if user belongs to any of the specified roles or is superuser."""
        if not self.is_authenticated:
            return False
        if self.is_superuser:
            return True
        return self.role in allowed_roles

    def can_access_manager_area(self) -> bool:
        """Managers and Admins can access manager-level areas."""
        return self.has_role(self.Role.ADMIN, self.Role.MANAGER)

    def can_access_admin_area(self) -> bool:
        """Only Admins (and superusers) can access admin-level areas."""
        return self.has_role(self.Role.ADMIN)

    def save(self, *args, **kwargs):
        """
        Ensure consistency between superuser status and admin role, and
        keep staff status aligned with administration privileges.
        """
        # If created as superuser via CLI, grant ADMIN role
        if self.is_superuser and self.role != self.Role.ADMIN:
            self.role = self.Role.ADMIN

        # Admins must have is_staff set so they can access administrative tooling
        if self.role == self.Role.ADMIN:
            self.is_staff = True

        super().save(*args, **kwargs)
