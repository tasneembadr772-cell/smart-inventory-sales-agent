"""
AI Agent Database Models.

Defines persistence and auditing models for the Autonomous Inventory & Procurement AI Agent.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class AgentAuditLog(models.Model):
    """
    Audit trail for AI agent tool invocations.

    Guarantees full accountability for LLM-driven actions:
    - Identifies runtime authenticated user triggering the tool call.
    - Persists sanitized input arguments.
    - Records tool execution outcome (SUCCESS, DENIED, FAILED).
    - Preserves execution response summary and exact timestamp.
    """

    class Status(models.TextChoices):
        SUCCESS = 'SUCCESS', 'Success'
        DENIED = 'DENIED', 'Permission Denied'
        FAILED = 'FAILED', 'Execution Error'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_audit_logs',
        null=True,
        blank=True,
        help_text='Authenticated user who initiated or authorized this AI tool action.',
    )
    tool_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text='Name of the registered backend tool invoked.',
    )
    parameters = models.JSONField(
        default=dict,
        help_text='Sanitized JSON parameters passed into the tool.',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        help_text='Outcome status of the tool execution attempt.',
    )
    response_summary = models.TextField(
        blank=True,
        default='',
        help_text='Summary or error detail produced by the tool execution.',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text='Timestamp when the tool invocation was recorded.',
    )

    class Meta:
        verbose_name = 'Agent Audit Log'
        verbose_name_plural = 'Agent Audit Logs'
        ordering = ['-created_at']

    def __str__(self) -> str:
        username = self.user.username if self.user else '<anonymous>'
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.tool_name} by {username} ({self.status})"
