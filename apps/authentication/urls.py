"""
URL routing configuration for the Authentication app.
"""

from django.urls import path
from . import views

app_name = 'authentication'

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('manager-area/', views.manager_area_view, name='manager_area'),
    path('admin-area/', views.admin_area_view, name='admin_area'),
]
