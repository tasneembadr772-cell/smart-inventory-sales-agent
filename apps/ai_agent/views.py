"""
Views for the AI Agent Interaction and Execution.

Provides both an interactive UI and a JSON API endpoint for users to submit
goals, inspect tool executions in real-time, and approve sensitive draft actions.
"""

import json
import logging
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .services import AgentService
from .tool_registry import list_tools

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["GET", "POST"])
def agent_chat_view(request: HttpRequest) -> HttpResponse:
    """
    Renders the Agentic AI interface and handles interactive goal execution.
    Inherits request.user permission context directly.
    """
    tools = list_tools()
    result = None

    if request.method == "POST":
        goal = request.POST.get("goal", "").strip()
        auto_confirm = request.POST.get("auto_confirm") == "true"
        confirmed_tool = request.POST.get("confirmed_tool", "").strip()
        confirmed_actions = [confirmed_tool] if confirmed_tool else []

        if goal:
            service = AgentService(user=request.user)
            result = service.run(
                goal=goal,
                confirmed_actions=confirmed_actions,
                auto_confirm=auto_confirm,
            )

    return render(
        request,
        "ai_agent/agent_chat.html",
        {
            "tools": tools,
            "result": result,
        },
    )


@login_required
@require_http_methods(["POST"])
def agent_api_run(request: HttpRequest) -> JsonResponse:
    """
    RESTful JSON API endpoint for executing agent goals.
    Strictly verifies authenticated session and returns structured JSON.
    """
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON request body."},
            status=400,
        )

    goal = data.get("goal", "").strip()
    if not goal:
        return JsonResponse(
            {"success": False, "error": "Field 'goal' is required."},
            status=400,
        )

    confirmed_actions = data.get("confirmed_actions", [])
    auto_confirm = bool(data.get("auto_confirm", False))

    service = AgentService(user=request.user)
    result = service.run(
        goal=goal,
        confirmed_actions=confirmed_actions,
        auto_confirm=auto_confirm,
    )

    status_code = 200 if result.success or result.status == "PENDING_CONFIRMATION" else 400
    if result.status == "UNAUTHORIZED":
        status_code = 403

    return JsonResponse(result.to_dict(), status=status_code)
