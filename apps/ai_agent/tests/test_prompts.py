"""
Tests for AI Agent Production Prompts, Sections, and Evolution Log.
"""

from django.test import TestCase

from apps.ai_agent.prompts import (
    SYSTEM_INSTRUCTION,
    SYSTEM_PERSONA,
    SECURITY_GUARDRAILS,
    TOOL_USAGE_RULES,
    BUSINESS_RULES,
    OUTPUT_FORMAT_DIRECTIVE,
    PROMPT_REASONING,
    PROMPT_EVOLUTION_LOG,
    get_system_instruction,
    get_prompt_sections,
    get_prompt_evolution_log,
    get_prompt_reasoning,
)


class PromptsModuleTests(TestCase):
    """Verifies that production prompts are complete, structured, and compliant."""

    def test_system_instruction_contains_all_core_sections(self):
        compiled = get_system_instruction()
        self.assertIsInstance(compiled, str)
        self.assertGreater(len(compiled), 500)

        # Check for presence of all 5 required prompt sections
        self.assertIn("1. SYSTEM PERSONA", compiled)
        self.assertIn("2. SECURITY GUARDRAILS", compiled)
        self.assertIn("3. TOOL USAGE RULES", compiled)
        self.assertIn("4. INVENTORY & PROCUREMENT BUSINESS RULES", compiled)
        self.assertIn("5. STRUCTURED RESPONSE FORMAT", compiled)

    def test_security_guardrails_coverage(self):
        guardrails = SECURITY_GUARDRAILS
        # Required security guardrails
        self.assertIn("PROMPT CONFIDENTIALITY", guardrails)
        self.assertIn("NO DIRECT DATABASE ACCESS", guardrails)
        self.assertIn("NO ARBITRARY CODE EXECUTION", guardrails)
        self.assertIn("RESPECT USER PERMISSION BOUNDARIES", guardrails)
        self.assertIn("GROUND TRUTH ENFORCEMENT", guardrails)
        self.assertIn("NO FALSE SUCCESS CONFIRMATION", guardrails)

    def test_tool_usage_rules_coverage(self):
        tools_section = TOOL_USAGE_RULES
        self.assertIn("check_low_stock_products", tools_section)
        self.assertIn("create_draft_purchase_order", tools_section)
        self.assertIn("get_inventory_summary", tools_section)
        self.assertIn("supplier_id", tools_section)
        self.assertIn("items", tools_section)

    def test_business_rules_coverage(self):
        business_rules = BUSINESS_RULES
        self.assertIn("current_stock <= reorder_level", business_rules)
        self.assertIn("DRAFT", business_rules)
        self.assertIn("confirmation", business_rules.lower())

    def test_output_format_sections(self):
        output_format = OUTPUT_FORMAT_DIRECTIVE
        self.assertIn("Action:", output_format)
        self.assertIn("Status:", output_format)
        self.assertIn("Affected Records:", output_format)
        self.assertIn("Summary:", output_format)
        self.assertIn("Errors / Notes:", output_format)

    def test_prompt_sections_accessor(self):
        sections = get_prompt_sections()
        self.assertIn("persona", sections)
        self.assertIn("security_guardrails", sections)
        self.assertIn("tool_usage_rules", sections)
        self.assertIn("business_rules", sections)
        self.assertIn("output_format", sections)

    def test_prompt_reasoning_documentation(self):
        reasoning = get_prompt_reasoning()
        self.assertIn("prompt_confidentiality", reasoning)
        self.assertIn("no_direct_database_access", reasoning)
        self.assertIn("no_arbitrary_code_execution", reasoning)
        self.assertIn("anti_hallucination_ground_truth", reasoning)
        self.assertIn("no_false_success_claims", reasoning)
        self.assertIn("supplier_isolation_rule", reasoning)
        self.assertIn("confirmation_gate_rule", reasoning)

    def test_prompt_evolution_log_integrity(self):
        log = get_prompt_evolution_log()
        self.assertIsInstance(log, list)
        self.assertGreaterEqual(len(log), 4)

        for entry in log:
            self.assertIn("version", entry)
            self.assertIn("initial_prompt_problem", entry)
            self.assertIn("observed_failure", entry)
            self.assertIn("prompt_improvement", entry)
            self.assertIn("result", entry)
