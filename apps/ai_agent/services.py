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

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import google.generativeai as genai
from google.generativeai import types

from .prompts import SYSTEM_INSTRUCTION
from .tool_registry import execute_tool
from .tools import (
    get_gemini_function_declarations,
    is_tool_sensitive,
    is_tool_registered,
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

    DEFAULT_MODEL = "gemini-1.5-flash"
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
    ) -> AgentResult:
        """
        Executes the agentic tool calling loop to accomplish the requested user goal.

        Args:
            goal: Natural language goal (e.g. "Check low stock products and prepare draft purchase orders").
            confirmed_actions: List of tool names that the user has explicitly pre-approved or confirmed.
            auto_confirm: If True, bypasses confirmation pauses (for automated tests or batch tasks).

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
        current_input: Any = goal

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
                return AgentResult(
                    success=False,
                    status="ERROR",
                    goal=goal,
                    final_answer=f"An error occurred while communicating with the AI model: {str(llm_err)}",
                    steps=steps,
                    tools_executed=tools_executed,
                    error=str(llm_err),
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
                logger.info("Agent reached final answer at iteration %d", iteration)
                return AgentResult(
                    success=True,
                    status="SUCCESS",
                    goal=goal,
                    final_answer=final_answer,
                    steps=steps,
                    tools_executed=tools_executed,
                )

            # ── 4. Process Function Calls ───────────────────────────────────
            tool_response_parts: List[Any] = []

            for fc in function_calls:
                tool_name = fc.name
                raw_args = proto_to_python(getattr(fc, "args", {})) or {}

                # Guard 1: Verify tool is in the approved registry whitelist
                if not is_tool_registered(tool_name):
                    err_payload = {
                        "success": False,
                        "error": {
                            "code": "UNKNOWN_TOOL",
                            "detail": f"Tool '{tool_name}' is not registered or allowed.",
                        },
                    }
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

                # Guard 2: Require confirmation for sensitive/state-modifying operations
                is_authorized = auto_confirm or (tool_name in confirmed_actions_set)
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
                    )

                # Guard 3: Execute tool via security-hardened backend registry
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
