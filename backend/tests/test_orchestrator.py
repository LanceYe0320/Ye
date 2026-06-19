"""Tests for Orchestrator — robust plan generation with retry and repair.

Covers:
  - _extract_json: direct, markdown, balanced brace, noise rejection
  - _validate_and_repair_plan: missing keys, alias remapping, auto-wrap
  - generate_plan: retry with error feedback, fallback
"""

from __future__ import annotations

import json

import pytest

from app.orchestrator import (
    _AGENT_ALIASES,
    _AGENT_CAPABILITIES,
    _extract_json,
    _validate_and_repair_plan,
    ExecutionPlan,
    Orchestrator,
    PlanStep,
)


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_direct_json(self):
        text = '{"steps": [{"step": 1, "intent": "research", "agent": "explore", "input": "read main.py"}]}'
        assert _extract_json(text) is not None
        data = json.loads(_extract_json(text))
        assert len(data["steps"]) == 1

    def test_markdown_code_block(self):
        text = 'Here is your plan:\n```json\n{"steps": []}\n```'
        result = _extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data["steps"] == []

    def test_markdown_without_language_tag(self):
        text = '```\n{"steps": []}\n```'
        result = _extract_json(text)
        assert result is not None

    def test_balanced_brace_extraction(self):
        text = 'Sure! Here is the plan: {"steps": [{"step": 1}]} hope that helps!'
        result = _extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data["steps"][0]["step"] == 1

    def test_ignores_stray_braces(self):
        # Text has stray { and } that are NOT balanced JSON objects
        text = 'Use function foo() { return x; } for this. The plan is: {"steps": []}'
        result = _extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert "steps" in data

    def test_nested_braces_balanced(self):
        text = '{"steps": [{"step": 1, "args": {"key": "value"}}]}'
        result = _extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data["steps"][0]["args"]["key"] == "value"

    def test_no_json_returns_none(self):
        text = "I don't know how to plan this task."
        assert _extract_json(text) is None

    def test_empty_string(self):
        assert _extract_json("") is None

    def test_multiple_code_blocks_picks_valid(self):
        text = '```\nnot json\n```\n```json\n{"steps": []}\n```'
        result = _extract_json(text)
        assert result is not None

    def test_trailing_comma_is_not_valid(self):
        # Standard JSON does not allow trailing commas
        text = '{"steps": [{"step": 1},]}'
        # This should fail direct parse and brace scan
        assert _extract_json(text) is None


# ---------------------------------------------------------------------------
# _validate_and_repair_plan
# ---------------------------------------------------------------------------


class TestValidateAndRepair:
    def test_valid_plan_passes(self):
        data = {"steps": [
            {"step": 1, "intent": "research", "agent": "explore", "input": "read files"},
        ]}
        result = _validate_and_repair_plan(data, "test")
        assert result is not None
        assert result[0]["agent"] == "explore"

    def test_missing_steps_key_auto_wraps(self):
        data = {"step": 1, "intent": "research", "agent": "explore", "input": "read files"}
        result = _validate_and_repair_plan(data, "test")
        assert result is not None
        assert len(result) == 1
        assert result[0]["agent"] == "explore"

    def test_unknown_agent_remapped_via_alias(self):
        data = {"steps": [
            {"step": 1, "intent": "research", "agent": "researcher", "input": "find bugs"},
        ]}
        result = _validate_and_repair_plan(data, "test")
        assert result is not None
        assert result[0]["agent"] == "explore"

    def test_completely_unknown_agent_defaults_to_general(self):
        data = {"steps": [
            {"step": 1, "intent": "research", "agent": "wizard", "input": "magic"},
        ]}
        result = _validate_and_repair_plan(data, "test")
        assert result is not None
        assert result[0]["agent"] == "general"

    def test_missing_intent_gets_first_capability(self):
        data = {"steps": [
            {"step": 1, "agent": "explore", "input": "search code"},
        ]}
        result = _validate_and_repair_plan(data, "test")
        assert result is not None
        assert result[0]["intent"] in _AGENT_CAPABILITIES["explore"]

    def test_missing_input_falls_back_to_user_input(self):
        data = {"steps": [
            {"step": 1, "intent": "research", "agent": "explore"},
        ]}
        result = _validate_and_repair_plan(data, "fix the bug")
        assert result is not None
        assert result[0]["input"] == "fix the bug"

    def test_empty_steps_returns_none(self):
        assert _validate_and_repair_plan({"steps": []}, "test") is None

    def test_non_dict_returns_none(self):
        assert _validate_and_repair_plan("not a dict", "test") is None

    def test_step_number_cast_from_string(self):
        data = {"steps": [
            {"step": "3", "intent": "research", "agent": "explore", "input": "look"},
        ]}
        result = _validate_and_repair_plan(data, "test")
        assert result is not None
        assert result[0]["step"] == 3

    def test_all_aliases_map_to_valid_agents(self):
        for alias, canonical in _AGENT_ALIASES.items():
            assert canonical in _AGENT_CAPABILITIES, f"Alias '{alias}' maps to invalid agent '{canonical}'"


# ---------------------------------------------------------------------------
# Orchestrator.generate_plan — retry and fallback
# ---------------------------------------------------------------------------


class _StubProvider:
    """Provider that returns canned responses for testing."""

    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or []
        self._call_count = 0

    async def chat(self, messages=None, **kwargs):
        from app.llm.base_provider import StreamingChunk

        if self._call_count < len(self.responses):
            text = self.responses[self._call_count]
        else:
            text = '{"steps": []}'
        self._call_count += 1

        yield StreamingChunk(type="text_delta", text=text)
        yield StreamingChunk(type="done")


class TestGeneratePlan:
    @pytest.mark.asyncio
    async def test_valid_json_on_first_try(self):
        provider = _StubProvider([
            json.dumps({"steps": [
                {"step": 1, "intent": "research", "agent": "explore", "input": "read code"},
                {"step": 2, "intent": "implement", "agent": "code", "input": "write code"},
            ]}),
        ])
        orch = Orchestrator(provider, model="test")
        plan = await orch.generate_plan("fix the bug")
        assert len(plan.steps) == 2
        assert plan.steps[0].agent == "explore"
        assert plan.steps[1].agent == "code"

    @pytest.mark.asyncio
    async def test_retry_on_bad_json(self):
        provider = _StubProvider([
            "Here's my plan: {invalid json}",  # First attempt: bad JSON
            json.dumps({"steps": [              # Second attempt: valid JSON (retry)
                {"step": 1, "intent": "research", "agent": "explore", "input": "analyze"},
            ]}),
        ])
        orch = Orchestrator(provider, model="test")
        plan = await orch.generate_plan("fix the bug")
        assert len(plan.steps) == 1
        assert plan.steps[0].agent == "explore"

    @pytest.mark.asyncio
    async def test_fallback_on_both_failures(self):
        provider = _StubProvider([
            "I can't create a plan for this.",  # First: no JSON
            "Still can't do it.",               # Second: no JSON
        ])
        orch = Orchestrator(provider, model="test")
        plan = await orch.generate_plan("fix the bug")
        assert len(plan.steps) == 1
        assert plan.steps[0].agent == "general"
        assert plan.steps[0].intent == "general"

    @pytest.mark.asyncio
    async def test_auto_repairs_agent_aliases(self):
        provider = _StubProvider([
            json.dumps({"steps": [
                {"step": 1, "intent": "research", "agent": "researcher", "input": "look"},
                {"step": 2, "intent": "implement", "agent": "coder", "input": "code"},
            ]}),
        ])
        orch = Orchestrator(provider, model="test")
        plan = await orch.generate_plan("fix the bug")
        assert plan.steps[0].agent == "explore"  # researcher -> explore
        assert plan.steps[1].agent == "code"     # coder -> code

    @pytest.mark.asyncio
    async def test_markdown_wrapped_json(self):
        provider = _StubProvider([
            '```json\n{"steps": [{"step": 1, "intent": "research", "agent": "explore", "input": "read"}]}\n```',
        ])
        orch = Orchestrator(provider, model="test")
        plan = await orch.generate_plan("analyze code")
        assert len(plan.steps) == 1
        assert plan.steps[0].agent == "explore"
