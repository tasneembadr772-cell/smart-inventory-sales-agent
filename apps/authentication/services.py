"""
Business Logic & Service Layer for Authentication and Access Control.

Separates user management, role governance, and profile business logic from views.
"""

from typing import Dict, Any, Optional
from django.core.exceptions import ValidationError
from .models import User


def register_new_user(
    username: str,
    email: str,
    password: str,
    first_name: str = '',
    last_name: str = '',
    phone_number: str = '',
    bio: str = '',
) -> User:
    """
    Registers a new standard user securely.

    Security Guarantee:
    - Enforces User.Role.STANDARD unconditionally.
    - Unset is_staff and is_superuser to prevent vertical privilege escalation.
    - Uses Django's create_user method ensuring PBKDF2 password hashing.
    """
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError({'username': 'A user with that username already exists.'})

    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError({'email': 'A user with that email address already exists.'})

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
    )

    # Enforce standard role
    user.role = User.Role.STANDARD
    user.is_staff = False
    user.is_superuser = False
    user.phone_number = phone_number
    user.bio = bio
    user.save()

    return user


def update_user_profile(
    user: User,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    phone_number: Optional[str] = None,
    bio: Optional[str] = None,
) -> User:
    """
    Updates editable profile fields on the target user.

    Security Guarantee:
    - Role and permission flags (is_staff, is_superuser, role) are strictly protected
      and cannot be altered through profile updates.
    """
    if email and email.lower() != user.email.lower():
        if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
            raise ValidationError({'email': 'This email address is already in use by another account.'})
        user.email = email

    if first_name is not None:
        user.first_name = first_name

    if last_name is not None:
        user.last_name = last_name

    if phone_number is not None:
        user.phone_number = phone_number

    if bio is not None:
        user.bio = bio

    user.save()
    return user


def get_role_badge_info(role: str) -> Dict[str, str]:
    """
    Returns presentation metadata for a given role (badge styling, description).
    """
    info_map = {
        User.Role.ADMIN: {
            'label': 'System Administrator',
            'badge_class': 'badge-admin',
            'color': '#ef4444',
            'description': 'Full access to all system modules, user role assignments, and settings.',
        },
        User.Role.MANAGER: {
            'label': 'Inventory Manager',
            'badge_class': 'badge-manager',
            'color': '#38bdf8',
            'description': 'Access to inventory supervision, operational workflows, and manager reports.',
        },
        User.Role.STANDARD: {
            'label': 'Standard User',
            'badge_class': 'badge-standard',
            'color': '#10b981',
            'description': 'Standard access to operational views without administrative privileges.',
        },
    }
    return info_map.get(
        role,
        {
            'label': 'User',
            'badge_class': 'badge-standard',
            'color': '#64748b',
            'description': 'General system user.',
        }
    )
