"""
Authentication and Profile Forms with Validation and Security Constraints.

Prevents privilege escalation by strictly disallowing client input on role or permission flags.
"""

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import User
from .services import register_new_user, update_user_profile


class UserRegistrationForm(forms.ModelForm):
    """
    Secure user self-registration form.
    Guarantees standard role assignment and applies full password validation.
    """
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'placeholder': 'name@example.com', 'class': 'form-input'})
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'placeholder': 'Choose a strong password', 'class': 'form-input'}),
        help_text='Must be at least 8 characters and contain letters and numbers.'
    )
    password_confirm = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'placeholder': 'Repeat password', 'class': 'form-input'}),
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'phone_number']
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Unique username', 'class': 'form-input'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'First name', 'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Last name', 'class': 'form-input'}),
            'phone_number': forms.TextInput(attrs={'placeholder': '+1234567890', 'class': 'form-input'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email address already exists.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm:
            if password != password_confirm:
                self.add_error('password_confirm', 'Passwords do not match.')
            else:
                # Apply Django configured password validators
                try:
                    # Construct temporary instance for similarity validation
                    temp_user = User(
                        username=cleaned_data.get('username', ''),
                        email=cleaned_data.get('email', ''),
                        first_name=cleaned_data.get('first_name', ''),
                        last_name=cleaned_data.get('last_name', ''),
                    )
                    validate_password(password, user=temp_user)
                except ValidationError as error:
                    for msg in error.messages:
                        self.add_error('password', msg)

        return cleaned_data

    def save(self, commit=True):
        """Delegates creation to service layer to guarantee STANDARD role assignment."""
        cleaned_data = self.cleaned_data
        user = register_new_user(
            username=cleaned_data['username'],
            email=cleaned_data['email'],
            password=cleaned_data['password'],
            first_name=cleaned_data.get('first_name', ''),
            last_name=cleaned_data.get('last_name', ''),
            phone_number=cleaned_data.get('phone_number', ''),
        )
        return user


class UserLoginForm(forms.Form):
    """
    Standard login form with user authentication validation.
    """
    username = forms.CharField(
        label='Username',
        widget=forms.TextInput(attrs={'placeholder': 'Username', 'class': 'form-input', 'autofocus': True}),
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'placeholder': 'Password', 'class': 'form-input'}),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        if username and password:
            self.user_cache = authenticate(self.request, username=username, password=password)
            if self.user_cache is None:
                raise forms.ValidationError('Invalid username or password.')
            elif not self.user_cache.is_active:
                raise forms.ValidationError('This account has been deactivated.')

        return cleaned_data

    def get_user(self):
        return self.user_cache


class UserProfileUpdateForm(forms.ModelForm):
    """
    Allows authenticated users to update their personal profile info.
    Notice that 'role', 'is_staff', and 'is_superuser' are completely absent,
    preventing any possibility of privilege tampering.
    """
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'bio']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-input'}),
            'bio': forms.Textarea(attrs={'class': 'form-input', 'rows': 4}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('This email address is already in use by another account.')
        return email

    def save(self, commit=True):
        cleaned_data = self.cleaned_data
        return update_user_profile(
            user=self.instance,
            first_name=cleaned_data.get('first_name'),
            last_name=cleaned_data.get('last_name'),
            email=cleaned_data.get('email'),
            phone_number=cleaned_data.get('phone_number'),
            bio=cleaned_data.get('bio'),
        )
