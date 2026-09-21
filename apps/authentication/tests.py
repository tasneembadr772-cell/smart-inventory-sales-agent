"""
Comprehensive Unit and Integration Test Suite for Authentication and RBAC.

Covers:
1. User Model & Role Verification
2. Self-Registration & Privilege Escalation Prevention
3. Authentication Flow (Login & Logout)
4. Profile Protection & Horizontal Isolation
5. Role-Based Access Control (RBAC) Enforcement (Admin, Manager, Standard)
6. Password Security & PBKDF2 Hashing
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.test import TestCase, Client
from django.urls import reverse

User = get_user_model()


class UserModelTestCase(TestCase):
    """Verifies User model attributes, role constraints, and RBAC properties."""

    def test_create_standard_user(self):
        user = User.objects.create_user(
            username='johndoe',
            email='john@example.com',
            password='SecurePassword123!',
            first_name='John',
            last_name='Doe',
        )
        self.assertEqual(user.role, User.Role.STANDARD)
        self.assertTrue(user.is_standard_role)
        self.assertFalse(user.is_manager_role)
        self.assertFalse(user.is_admin_role)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(check_password('SecurePassword123!', user.password))
        self.assertIn('Standard User', str(user))

    def test_create_manager_user(self):
        manager = User.objects.create_user(
            username='manager_jane',
            email='jane@example.com',
            password='SecurePassword123!',
            role=User.Role.MANAGER,
        )
        self.assertEqual(manager.role, User.Role.MANAGER)
        self.assertTrue(manager.is_manager_role)
        self.assertFalse(manager.is_standard_role)
        self.assertFalse(manager.is_admin_role)
        self.assertTrue(manager.can_access_manager_area())
        self.assertFalse(manager.can_access_admin_area())

    def test_create_admin_user(self):
        admin = User.objects.create_user(
            username='admin_boss',
            email='admin@example.com',
            password='SecurePassword123!',
            role=User.Role.ADMIN,
        )
        self.assertEqual(admin.role, User.Role.ADMIN)
        self.assertTrue(admin.is_admin_role)
        self.assertTrue(admin.can_access_manager_area())
        self.assertTrue(admin.can_access_admin_area())
        self.assertTrue(admin.is_staff)

    def test_superuser_auto_sync_role(self):
        superuser = User.objects.create_superuser(
            username='root_super',
            email='root@example.com',
            password='RootPassword123!',
        )
        self.assertEqual(superuser.role, User.Role.ADMIN)
        self.assertTrue(superuser.is_admin_role)
        self.assertTrue(superuser.can_access_manager_area())
        self.assertTrue(superuser.can_access_admin_area())


class RegistrationTestCase(TestCase):
    """Verifies registration and vertical privilege escalation prevention."""

    def setUp(self):
        self.client = Client()
        self.register_url = reverse('authentication:register')

    def test_successful_registration_defaults_to_standard_user(self):
        response = self.client.post(self.register_url, {
            'username': 'new_candidate',
            'email': 'candidate@example.com',
            'first_name': 'New',
            'last_name': 'Candidate',
            'password': 'StrongPassword2026!',
            'password_confirm': 'StrongPassword2026!',
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='new_candidate')
        self.assertEqual(user.role, User.Role.STANDARD)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_vertical_privilege_escalation_prevented_on_registration(self):
        """Attacker attempts to post role='ADMIN' or is_staff=True during registration."""
        response = self.client.post(self.register_url, {
            'username': 'hacker_user',
            'email': 'hacker@example.com',
            'password': 'StrongPassword2026!',
            'password_confirm': 'StrongPassword2026!',
            'role': 'ADMIN',
            'is_staff': 'True',
            'is_superuser': 'True',
        })
        self.assertEqual(response.status_code, 302)
        hacker = User.objects.get(username='hacker_user')
        # Crucial: the user is created strictly as STANDARD user
        self.assertEqual(hacker.role, User.Role.STANDARD)
        self.assertFalse(hacker.is_staff)
        self.assertFalse(hacker.is_superuser)

    def test_registration_duplicate_email_rejected(self):
        User.objects.create_user(
            username='existing_user',
            email='duplicate@example.com',
            password='Password123!',
        )
        response = self.client.post(self.register_url, {
            'username': 'new_user',
            'email': 'duplicate@example.com',
            'password': 'Password123!',
            'password_confirm': 'Password123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'email', 'An account with this email address already exists.')


class AuthenticationFlowTestCase(TestCase):
    """Tests login, logout, and session lifecycle."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='ValidPassword123!',
        )
        self.login_url = reverse('authentication:login')
        self.logout_url = reverse('authentication:logout')

    def test_successful_login(self):
        response = self.client.post(self.login_url, {
            'username': 'testuser',
            'password': 'ValidPassword123!',
        })
        self.assertEqual(response.status_code, 302)
        # Check that user is authenticated in session
        self.assertTrue('_auth_user_id' in self.client.session)

    def test_invalid_password_login_rejected(self):
        response = self.client.post(self.login_url, {
            'username': 'testuser',
            'password': 'WrongPassword!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_logout_terminates_session(self):
        self.client.login(username='testuser', password='ValidPassword123!')
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse('_auth_user_id' in self.client.session)


class ProfileSecurityTestCase(TestCase):
    """Tests profile management and horizontal/vertical privilege isolation."""

    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='Password123!',
            role=User.Role.STANDARD,
        )
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='Password123!',
            role=User.Role.ADMIN,
        )
        self.profile_url = reverse('authentication:profile')

    def test_unauthenticated_profile_redirects_to_login(self):
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('authentication:login'), response.url)

    def test_horizontal_escalation_prevented(self):
        """Profile view strictly reads and updates request.user; query params are ignored."""
        self.client.force_login(self.user1)
        response = self.client.get(f"{self.profile_url}?user_id={self.user2.id}")
        self.assertEqual(response.status_code, 200)
        # The profile shown must be user1, not user2
        self.assertEqual(response.context['user'].id, self.user1.id)

    def test_vertical_escalation_prevented_on_profile_update(self):
        """Attacker attempts to tamper with role parameter in profile update."""
        self.client.force_login(self.user1)
        response = self.client.post(self.profile_url, {
            'first_name': 'Updated',
            'last_name': 'Name',
            'email': 'user1_new@example.com',
            'phone_number': '+15551234567',
            'bio': 'Updated bio',
            'role': 'ADMIN',
            'is_staff': 'True',
            'is_superuser': 'True',
        })
        self.assertEqual(response.status_code, 302)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.first_name, 'Updated')
        self.assertEqual(self.user1.role, User.Role.STANDARD)
        self.assertFalse(self.user1.is_staff)
        self.assertFalse(self.user1.is_superuser)


class RoleBasedAccessControlTestCase(TestCase):
    """
    Verifies strict Role-Based Access Control:
    - Standard User: Dashboard (OK), Manager Area (403), Admin Area (403)
    - Manager: Dashboard (OK), Manager Area (OK), Admin Area (403)
    - Admin: Dashboard (OK), Manager Area (OK), Admin Area (OK)
    """

    def setUp(self):
        self.client = Client()
        self.standard_user = User.objects.create_user(
            username='standard_alice',
            email='alice@example.com',
            password='Password123!',
            role=User.Role.STANDARD,
        )
        self.manager_user = User.objects.create_user(
            username='manager_bob',
            email='bob@example.com',
            password='Password123!',
            role=User.Role.MANAGER,
        )
        self.admin_user = User.objects.create_user(
            username='admin_charlie',
            email='charlie@example.com',
            password='Password123!',
            role=User.Role.ADMIN,
        )

        self.dashboard_url = reverse('authentication:dashboard')
        self.manager_url = reverse('authentication:manager_area')
        self.admin_url = reverse('authentication:admin_area')

    # --- Standard User Tests ---
    def test_standard_user_can_access_dashboard(self):
        self.client.force_login(self.standard_user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)

    def test_standard_user_forbidden_from_manager_area(self):
        self.client.force_login(self.standard_user)
        response = self.client.get(self.manager_url)
        self.assertEqual(response.status_code, 403)

    def test_standard_user_forbidden_from_admin_area(self):
        self.client.force_login(self.standard_user)
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, 403)

    # --- Manager Tests ---
    def test_manager_can_access_dashboard_and_manager_area(self):
        self.client.force_login(self.manager_user)
        response_dash = self.client.get(self.dashboard_url)
        self.assertEqual(response_dash.status_code, 200)

        response_mgr = self.client.get(self.manager_url)
        self.assertEqual(response_mgr.status_code, 200)

    def test_manager_forbidden_from_admin_area(self):
        self.client.force_login(self.manager_user)
        response = self.client.get(self.admin_url)
        self.assertEqual(response.status_code, 403)

    # --- Admin Tests ---
    def test_admin_can_access_all_areas(self):
        self.client.force_login(self.admin_user)
        response_dash = self.client.get(self.dashboard_url)
        self.assertEqual(response_dash.status_code, 200)

        response_mgr = self.client.get(self.manager_url)
        self.assertEqual(response_mgr.status_code, 200)

        response_admin = self.client.get(self.admin_url)
        self.assertEqual(response_admin.status_code, 200)

    # --- Role Aliases & Consistency Tests ---
    def test_role_aliases_and_convenience_properties(self):
        """Verifies that SALES and CASHIER aliases map correctly to STANDARD role."""
        self.assertTrue(self.standard_user.has_role('SALES'))
        self.assertTrue(self.standard_user.has_role('CASHIER'))
        self.assertTrue(self.standard_user.is_sales_role)
        self.assertTrue(self.standard_user.is_cashier_role)

        self.assertFalse(self.manager_user.has_role('SALES'))
        self.assertFalse(self.manager_user.has_role('CASHIER'))
        self.assertFalse(self.manager_user.is_sales_role)
        self.assertFalse(self.manager_user.is_cashier_role)

        # Superuser has all roles
        superuser = User.objects.create_superuser(
            username='super_alias',
            email='super_alias@example.com',
            password='Password123!',
        )
        self.assertTrue(superuser.has_role('SALES'))
        self.assertTrue(superuser.has_role('CASHIER'))

