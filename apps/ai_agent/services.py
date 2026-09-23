"""
Autonomous Agent Service and Orchestration Layer.

Implements the multi-step Agentic Tool Calling workflow:
1. Receive user goal.
2. Provide LLM with backend tool declarations.
3. Allow LLM to iteratively select tools, passing arguments.
4. Execute tools through the security gateway (RBAC, validation, constraints).
5. Enforce explicit confirmation on sensitive actions (e.g. creating draft POs).
6. Feed structured tool results back to LLM.
7. Return clear final response and audit trail.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import google.generativeai as genai
from google.generativeai import types

from .prompts import SYSTEM_INSTRUCTION
from .tool_registry import execute_tool
from .tools import (
    can_user_execute_tool,
    get_gemini_function_declarations,
    is_tool_registered,
    is_tool_sensitive,
    record_tool_audit_log,
    MUTATION_TOOLS,
    SENSITIVE_TOOLS,
)
from .utils import make_json_serializable, proto_to_python

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """
    Structured outcome of an Agentic AI execution loop.
    """
    success: bool
    status: str  # "SUCCESS", "PENDING_CONFIRMATION", "ERROR", "UNAUTHORIZED", "MAX_ITERATIONS_REACHED", "CONFIG_ERROR"
    goal: str
    final_answer: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    tools_executed: List[str] = field(default_factory=list)
    pending_action: Optional[Dict[str, Any]] = None
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serializes result into clean dictionary suitable for API or UI rendering."""
        return {
            "success": self.success,
            "status": self.status,
            "goal": self.goal,
            "final_answer": self.final_answer,
            "steps": self.steps,
            "tools_executed": self.tools_executed,
            "pending_action": self.pending_action,
            "data": self.data,
            "error": self.error,
        }


class AgentService:
    """
    Agentic Orchestration Service for Inventory & Sales Management.

    Binds the authenticated user's permission context to all tool invocations,
    interfaces with Gemini's function calling API, and manages the multi-step
    reasoning-action loop.
    """

    DEFAULT_MODEL = "gemini-2.0-flash"
    DEFAULT_MAX_ITERATIONS = 6

    def __init__(
        self,
        user,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        max_iterations: Optional[int] = None,
        model: Optional[Any] = None,
    ):
        """
        Initializes the agent service for a specific authenticated user session.
        """
        self.user = user
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        self.model_name = model_name or os.getenv("GEMINI_MODEL", self.DEFAULT_MODEL).strip()
        self.max_iterations = max_iterations or int(os.getenv("AGENT_MAX_ITERATIONS", str(self.DEFAULT_MAX_ITERATIONS)))
        self._custom_model = model

    def run(
        self,
        goal: str,
        confirmed_actions: Optional[List[str]] = None,
        auto_confirm: bool = False,
        chat_history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """
        Executes the agentic tool calling loop to accomplish the requested user goal.

        Args:
            goal: Natural language goal (e.g. "Check low stock products and prepare draft purchase orders").
            confirmed_actions: List of tool names that the user has explicitly pre-approved or confirmed.
            auto_confirm: If True, bypasses confirmation pauses (for automated tests or batch tasks).
            chat_history: Optional list of prior conversation messages [{"role": "user"|"assistant", "content": "..."}].
            context: Optional dictionary of application context (e.g. user role, inventory KPIs, active page).

        Returns:
            AgentResult detailing execution status, final response, steps, and tool outputs.
        """
        # ── 1. Authentication Gate ──────────────────────────────────────────
        if self.user is None or not getattr(self.user, "is_authenticated", False):
            logger.warning("AgentService rejected unauthenticated execution attempt.")
            return AgentResult(
                success=False,
                status="UNAUTHORIZED",
                goal=goal,
                final_answer="Authentication required. You must be logged in to interact with the Inventory AI Agent.",
                error="UNAUTHORIZED",
            )

        # Standard users cannot auto-confirm state-changing actions
        user_is_privileged = getattr(self.user, "has_role", lambda *r: False)("ADMIN", "MANAGER")
        if not user_is_privileged:
            auto_confirm = False

        confirmed_actions_set = set(confirmed_actions or [])

        # ── 2. Initialize Model and Chat Session ────────────────────────────
        try:
            chat = self._get_chat_session()
        except ValueError as val_err:
            logger.error("AgentService configuration error: %s", val_err)
            return AgentResult(
                success=False,
                status="CONFIG_ERROR",
                goal=goal,
                final_answer=str(val_err),
                error="CONFIG_ERROR",
            )
        except Exception as exc:
            logger.exception("Failed to initialize Gemini model session.")
            return AgentResult(
                success=False,
                status="ERROR",
                goal=goal,
                final_answer=f"Could not initialize AI Agent session: {str(exc)}",
                error=str(exc),
            )

        # ── 3. The Agentic Reasoning & Action Loop ──────────────────────────
        iteration = 0
        steps: List[Dict[str, Any]] = []
        tools_executed: List[str] = []
        seen_tool_calls: set[str] = set()
        structured_data: Dict[str, Any] = {
            "affected_records": [],
            "created_orders": [],
            "summary": {},
            "errors": [],
        }

        # Construct context-aware initial prompt if conversation history or context is supplied
        context_blocks = []
        if context:
            user_info = context.get("user") or {}
            inv_info = context.get("inventory") or {}
            summary_items = []
            if user_info.get("role"):
                summary_items.append(f"User Role: {user_info.get('role')}")
            if inv_info:
                inv_str = ", ".join(f"{k}: {v}" for k, v in inv_info.items() if v is not None)
                if inv_str:
                    summary_items.append(f"Live Inventory Snapshot: {inv_str}")
            if context.get("current_page"):
                summary_items.append(f"Current Page: {context.get('current_page')}")
            if summary_items:
                context_blocks.append("[System Session Context: " + " | ".join(summary_items) + "]")

        if chat_history:
            history_lines = ["[Recent Conversation History]"]
            for turn in chat_history[-6:]:
                role = "User" if turn.get("role") == "user" else "Assistant"
                content = (turn.get("content") or "").strip()
                if content:
                    history_lines.append(f"{role}: {content}")
            if len(history_lines) > 1:
                context_blocks.append("\n".join(history_lines))

        if context_blocks:
            context_blocks.append(f"[Current Request]\n{goal}")
            current_input: Any = "\n\n".join(context_blocks)
        else:
            current_input = goal

        logger.info(
            "AgentService starting loop for user '%s' (role: %s) with goal: '%s'",
            self.user.username,
            getattr(self.user, "role", "UNKNOWN"),
            goal,
        )

        while iteration < self.max_iterations:
            iteration += 1

            try:
                # Dispatch message to the LLM
                response = chat.send_message(current_input)
            except Exception as llm_err:
                logger.exception("LLM API call failed during iteration %d", iteration)
                err_str = str(llm_err)
                safe_err = re.sub(r'key=[A-Za-z0-9_-]+', 'key=********', err_str)
                safe_err = re.sub(r'AIza[0-9A-Za-z-_]{35}', '********', safe_err)
                return AgentResult(
                    success=False,
                    status="ERROR",
                    goal=goal,
                    final_answer=f"An error occurred while communicating with the AI model: {safe_err}",
                    steps=steps,
                    tools_executed=tools_executed,
                    data=structured_data,
                    error=safe_err,
                )

            # Inspect response candidates
            candidate = response.candidates[0] if (hasattr(response, "candidates") and response.candidates) else None
            if not candidate or not hasattr(candidate, "content") or not candidate.content or not candidate.content.parts:
                logger.warning("LLM returned empty candidate response at iteration %d", iteration)
                break

            text_snippets: List[str] = []
            function_calls: List[Any] = []

            for part in candidate.content.parts:
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    function_calls.append(fc)
                elif getattr(part, "text", None):
                    text_snippets.append(part.text)

            thought = " ".join(text_snippets).strip()

            # If the LLM didn't request any tool calls, it has reached its final answer!
            if not function_calls:
                final_answer = thought or "Goal completed successfully."
                # Anti-hallucination: If any mutation tool failed, prevent LLM text from claiming false success
                mutation_failed = any(
                    step.get("tool") in MUTATION_TOOLS and step.get("status") == "FAILURE"
                    for step in steps
                )
                if mutation_failed and any(w in thought.lower() for w in ("successfully created", "order has been created", "po created", "draft order created")):
                    final_answer = (
                        "The purchase order could NOT be created due to permission or validation errors. "
                        "Please inspect the execution trace for details."
                    )

                logger.info("Agent reached final answer at iteration %d", iteration)
                return AgentResult(
                    success=True,
                    status="SUCCESS",
                    goal=goal,
                    final_answer=final_answer,
                    steps=steps,
                    tools_executed=tools_executed,
                    data=structured_data,
                )

            # ── 4. Process Function Calls ───────────────────────────────────
            tool_response_parts: List[Any] = []

            for fc in function_calls:
                tool_name = fc.name
                raw_args = proto_to_python(getattr(fc, "args", {})) or {}
                if isinstance(raw_args, dict):
                    # Never trust confirmation booleans injected by the LLM inside tool arguments
                    raw_args.pop("confirmed", None)
                    raw_args.pop("confirm", None)
                    raw_args.pop("auto_confirm", None)

                # Guard 1: Verify tool is in the approved registry whitelist
                if not is_tool_registered(tool_name):
                    err_payload = {
                        "success": False,
                        "error": {
                            "code": "UNKNOWN_TOOL",
                            "detail": f"Tool '{tool_name}' is not registered or allowed.",
                        },
                    }
                    record_tool_audit_log(
                        user=self.user,
                        tool_name=str(tool_name)[:100],
                        parameters=raw_args,
                        status="FAILED",
                        response_summary=f"Tool '{tool_name}' is not registered or allowed.",
                    )
                    structured_data["errors"].append(f"Tool '{tool_name}' is not registered or allowed.")
                    steps.append({
                        "iteration": iteration,
                        "thought": thought,
                        "tool": tool_name,
                        "args": raw_args,
                        "result": err_payload,
                        "status": "ERROR",
                    })
                    tool_response_parts.append(
                        types.protos.Part(
                            function_response=types.protos.FunctionResponse(
                                name=tool_name,
                                response={"result": err_payload},
                            )
                        )
                    )
                    continue

                # Guard 2: RBAC Governance Gate (Standard users restricted to read-only queries)
                allowed, denial_reason = can_user_execute_tool(self.user, tool_name)
                if not allowed:
                    logger.warning(
                        "AgentService RBAC denied '%s' for user '%s'",
                        tool_name,
                        getattr(self.user, "username", "unknown"),
                    )
                    record_tool_audit_log(
                        user=self.user,
                        tool_name=tool_name,
                        parameters=raw_args,
                        status="DENIED",
                        response_summary=denial_reason,
                    )
                    structured_data["errors"].append(denial_reason)
                    err_payload = {
                        "success": False,
                        "error": {
                            "code": "PERMISSION_DENIED",
                            "detail": denial_reason,
                        },
                        "message": denial_reason,
                    }
                    steps.append({
                        "iteration": iteration,
                        "thought": thought,
                        "tool": tool_name,
                        "args": raw_args,
                        "result": err_payload,
                        "status": "FAILURE",
                    })
                    tool_response_parts.append(
                        types.protos.Part(
                            function_response=types.protos.FunctionResponse(
                                name=tool_name,
                                response={"result": err_payload},
                            )
                        )
                    )
                    continue

                # Guard 2.5: Loop Safety — Repeated Identical Tool Call Protection
                call_signature = f"{tool_name}:{json.dumps(raw_args, sort_keys=True, default=str)}"
                if call_signature in seen_tool_calls:
                    logger.warning("AgentService: repeated identical tool call prevented: %s", tool_name)
                    err_payload = {
                        "success": False,
                        "error": {
                            "code": "REPEATED_TOOL_CALL",
                            "detail": f"Repeated execution of tool '{tool_name}' with identical parameters was prevented.",
                        },
                        "message": f"Repeated call to '{tool_name}' with identical parameters was prevented.",
                    }
                    steps.append({
                        "iteration": iteration,
                        "thought": thought,
                        "tool": tool_name,
                        "args": raw_args,
                        "result": err_payload,
                        "status": "FAILURE",
                    })
                    tool_response_parts.append(
                        types.protos.Part(
                            function_response=types.protos.FunctionResponse(
                                name=tool_name,
                                response={"result": err_payload},
                            )
                        )
                    )
                    continue
                seen_tool_calls.add(call_signature)

                # Guard 3: Require confirmation for sensitive/state-modifying operations
                is_authorized = (auto_confirm and user_is_privileged) or (tool_name in confirmed_actions_set)
                if is_tool_sensitive(tool_name) and not is_authorized:
                    pending_action = {
                        "tool_name": tool_name,
                        "params": raw_args,
                        "summary": (
                            f"Create draft purchase order for supplier #{raw_args.get('supplier_id')} "
                            f"containing {len(raw_args.get('items', []))} line item(s)."
                        ),
                    }
                    steps.append({
                        "iteration": iteration,
                        "thought": thought,
                        "tool": tool_name,
                        "args": raw_args,
                        "status": "PENDING_CONFIRMATION",
                        "confirmation_required": True,
                    })
                    logger.info("Sensitive action '%s' paused awaiting user confirmation.", tool_name)
                    return AgentResult(
                        success=True,
                        status="PENDING_CONFIRMATION",
                        goal=goal,
                        final_answer=(
                            f"{thought}\n\n"
                            f"⚠️ **Action Requires Confirmation**: I am ready to execute `{tool_name}` "
                            f"for supplier ID {raw_args.get('supplier_id')} with {len(raw_args.get('items', []))} item(s). "
                            f"Please confirm to proceed."
                        ).strip(),
                        steps=steps,
                        tools_executed=tools_executed,
                        pending_action=pending_action,
                        data=structured_data,
                    )

                # Guard 4: Execute tool via security-hardened backend registry
                try:
                    tool_result = execute_tool(tool_name, user=self.user, params=raw_args)
                except Exception as exec_err:
                    logger.exception("Unexpected error executing tool '%s'", tool_name)
                    tool_result = {
                        "success": False,
                        "error": {
                            "code": "INTERNAL_EXECUTION_ERROR",
                            "detail": str(exec_err),
                        },
                    }

                tools_executed.append(tool_name)
                steps.append({
                    "iteration": iteration,
                    "thought": thought,
                    "tool": tool_name,
                    "args": raw_args,
                    "result": tool_result,
                    "status": "SUCCESS" if tool_result.get("success") else "FAILURE",
                })

                # Capture verified backend data for structured output
                if tool_result.get("success"):
                    if tool_name == "create_draft_purchase_order":
                        po_data = tool_result.get("data") or {}
                        po_id = po_data.get("purchase_order_id")
                        po_num = po_data.get("order_number")
                        if po_id and po_num:
                            structured_data["affected_records"].append({
                                "type": "PurchaseOrder",
                                "id": po_id,
                                "order_number": po_num,
                            })
                            structured_data["created_orders"].append(po_data)
                    elif tool_name in ("check_low_stock_products", "get_inventory_summary"):
                        structured_data["summary"][tool_name] = tool_result.get("data")
                else:
                    err_info = tool_result.get("error") or {}
                    err_msg = err_info.get("detail") if isinstance(err_info, dict) else str(err_info)
                    structured_data["errors"].append(str(err_msg or tool_result.get("message", "Tool execution failed.")))

                # Prepare function response part to feed back to LLM
                serializable = make_json_serializable(tool_result)
                tool_response_parts.append(
                    types.protos.Part(
                        function_response=types.protos.FunctionResponse(
                            name=tool_name,
                            response={"result": serializable},
                        )
                    )
                )

            # Pass tool results back to LLM for next reasoning turn
            current_input = tool_response_parts

        # ── 5. Max Iterations Exceeded ──────────────────────────────────────
        logger.warning("AgentService reached maximum iterations (%d) for goal: '%s'", self.max_iterations, goal)
        return AgentResult(
            success=False,
            status="MAX_ITERATIONS_REACHED",
            goal=goal,
            final_answer="The agent reached the maximum permitted tool execution iterations before completing the goal.",
            steps=steps,
            tools_executed=tools_executed,
            data=structured_data,
            error="MAX_ITERATIONS_REACHED",
        )

    def _get_chat_session(self):
        """Constructs or returns the Gemini chat session with declared tools."""
        if self._custom_model:
            return self._custom_model.start_chat(enable_automatic_function_calling=False)

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not configured.")

        genai.configure(api_key=self.api_key)
        declarations = get_gemini_function_declarations()
        gemini_tools = [types.Tool(function_declarations=declarations)]

        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=SYSTEM_INSTRUCTION,
            tools=gemini_tools,
        )
        return model.start_chat(enable_automatic_function_calling=False)
