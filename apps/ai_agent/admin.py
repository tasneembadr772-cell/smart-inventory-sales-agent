"""
Django Admin Registration for AI Agent Models.
"""

from django.contrib import admin
from .models import AgentAuditLog


@admin.register(AgentAuditLog)
class AgentAuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tool_name', 'user', 'status', 'short_summary')
    list_filter = ('status', 'tool_name', 'created_at')
    search_fields = ('tool_name', 'user__username', 'response_summary')
    readonly_fields = ('created_at', 'user', 'tool_name', 'parameters', 'status', 'response_summary')
    ordering = ('-created_at',)

    def short_summary(self, obj):
        if not obj.response_summary:
            return '-'
        return (obj.response_summary[:75] + '...') if len(obj.response_summary) > 75 else obj.response_summary
    short_summary.short_description = 'Response Summary'

    def has_add_permission(self, request):
        # Audit logs should only be created via agent execution, not manually in admin
        return False
