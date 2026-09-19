"""
URL Configuration for the AI Agent application.
Namespace: ai_agent
"""

from django.urls import path
from . import views

app_name = "ai_agent"

urlpatterns = [
    path("", views.agent_chat_view, name="chat"),
    path("api/run/", views.agent_api_run, name="api_run"),
]
