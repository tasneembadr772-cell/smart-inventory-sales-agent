"""
Views for the AI Agent Interaction and Execution.

Provides both an interactive UI and secure JSON API endpoints for:
1. Conversational Chatbot API (message history, context awareness, CSRF protected).
2. Live Application Context API (user role, stock health, smart suggestions).
3. Goal execution API (backward-compatible agent runner).
"""

import json
import logging
from typing import Any, Dict
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.domain_app import selectors
from .services import AgentService
from .tool_registry import list_tools

logger = logging.getLogger(__name__)


def _get_live_inventory_context(user) -> Dict[str, Any]:
    """
    Safely retrieves live inventory KPIs for application context injection.
    Restricted strictly to non-sensitive metrics appropriate for the user's role.
    """
    try:
        kpis = selectors.get_inventory_kpis(user=user)
        return {
            "total_products": kpis.get("total_products", 0),
            "active_products": kpis.get("active_products", 0),
            "low_stock_count": kpis.get("low_stock_count", 0),
            "out_of_stock_count": kpis.get("out_of_stock_count", 0),
            "total_units": kpis.get("total_units", 0),
            "attention_count": kpis.get("attention_count", 0),
        }
    except Exception as exc:
        logger.warning("Could not fetch inventory KPIs for agent context: %s", exc)
        return {
            "total_products": 0,
            "active_products": 0,
            "low_stock_count": 0,
            "out_of_stock_count": 0,
            "total_units": 0,
            "attention_count": 0,
        }


@login_required
@require_http_methods(["GET", "POST"])
def agent_chat_view(request: HttpRequest) -> HttpResponse:
    """
    Renders the dedicated Agentic AI interface and handles fallback form submissions.
    Inherits request.user permission context directly.
    """
    tools = list_tools()
    inventory_context = _get_live_inventory_context(request.user)
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
                context={
                    "user": {"role": request.user.get_role_display()},
                    "inventory": inventory_context,
                    "current_page": "ai_agent_chat",
                },
            )

    return render(
        request,
        "ai_agent/agent_chat.html",
        {
            "tools": tools,
            "result": result,
            "inventory_context": inventory_context,
        },
    )


@login_required
@require_http_methods(["POST"])
def agent_chat_api(request: HttpRequest) -> JsonResponse:
    """
    Asynchronous JSON API for the Embedded Context-Aware Chatbot.

    Enforces:
    - User authentication (via session cookie).
    - CSRF protection (via X-CSRFToken header).
    - Context injection (authenticated user, role, live stock health).
    - Structured tool execution result rendering.
    - Zero exposure of sensitive server secrets or credentials.
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"success": False, "error": "Malformed request: expected valid JSON body."},
            status=400,
        )

    # Accept either 'message' or 'goal'
    message = (data.get("message") or data.get("goal") or "").strip()
    if not message:
        return JsonResponse(
            {"success": False, "error": "Field 'message' is required and cannot be empty."},
            status=400,
        )

    # Optional conversational history and action approvals
    history = data.get("history", [])
    if not isinstance(history, list):
        history = []

    confirmed_actions = data.get("confirmed_actions", [])
    if not isinstance(confirmed_actions, list):
        confirmed_actions = []

    auto_confirm = bool(data.get("auto_confirm", False))
    client_context = data.get("context", {}) if isinstance(data.get("context"), dict) else {}

    # Build server-side trusted application context
    inventory_context = _get_live_inventory_context(request.user)
    app_context = {
        "user": {
            "username": request.user.username,
            "role": request.user.get_role_display(),
            "is_privileged": request.user.has_role("ADMIN", "MANAGER"),
        },
        "inventory": inventory_context,
        "current_page": client_context.get("current_page", "dashboard"),
    }

    service = AgentService(user=request.user)
    result = service.run(
        goal=message,
        confirmed_actions=confirmed_actions,
        auto_confirm=auto_confirm,
        chat_history=history,
        context=app_context,
    )

    status_code = 200 if result.success or result.status == "PENDING_CONFIRMATION" else 400
    if result.status == "UNAUTHORIZED":
        status_code = 403

    # Clean response strictly safe for frontend consumption
    payload = {
        "success": result.success,
        "status": result.status,
        "reply": result.final_answer,
        "steps": result.steps,
        "tools_executed": result.tools_executed,
        "pending_action": result.pending_action,
        "data": result.data,
        "context": {
            "username": request.user.username,
            "role": request.user.get_role_display(),
            "low_stock_count": inventory_context.get("low_stock_count", 0),
            "total_products": inventory_context.get("total_products", 0),
        },
        "error": result.error,
    }

    return JsonResponse(payload, status=status_code)


@login_required
@require_http_methods(["GET"])
def agent_context_api(request: HttpRequest) -> JsonResponse:
    """
    Returns live application context and role-specific smart prompt suggestions
    to bootstrap the chatbot UI on initialization.
    """
    inventory_context = _get_live_inventory_context(request.user)
    is_privileged = request.user.has_role("ADMIN", "MANAGER")

    # Smart, role-aware suggestions
    suggestions = [
        "Which products are low in stock?",
        "Provide an inventory health summary",
    ]
    if is_privileged:
        if inventory_context.get("low_stock_count", 0) > 0:
            suggestions.insert(1, "Prepare draft purchase orders for low-stock items")
        else:
            suggestions.append("Check low-stock products including zero stock")

    return JsonResponse({
        "success": True,
        "user": {
            "username": request.user.username,
            "role": request.user.get_role_display(),
            "is_privileged": is_privileged,
        },
        "inventory": inventory_context,
        "suggestions": suggestions,
    })


@login_required
@require_http_methods(["POST"])
def agent_api_run(request: HttpRequest) -> JsonResponse:
    """
    Backward-compatible RESTful JSON API endpoint for executing agent goals.
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
