"""Tests for the Multi-Agent Harness system.

Covers:
  - TokenBudget: zone transitions, model degradation, circuit breaker
  - ToolRegistry: permissions, rate limiting, agent filtering
  - FailureHandler: classification, retry strategies, escalation
  - ExecutionTrace: event recording, serialization
  - Eval: trajectory scoring, task completion scoring
  - Integration: ToolExecutor with full Harness wired up
"""

import time

import pytest

from app.budget import BudgetConfig, BudgetZone, TokenBudget
from app.eval import eval_task_completion, eval_tool_call, eval_trajectory
from app.execution_trace import ExecutionTrace
from app.failure import FailureAction, FailureHandler, FailureType
from app.tool_registry import RiskLevel, ToolRegistry, get_registry


# ---------------------------------------------------------------------------
# TokenBudget
# ---------------------------------------------------------------------------


class TestTokenBudget:
    def test_starts_in_green_zone(self):
        budget = TokenBudget(BudgetConfig(max_total_tokens=100_000))
        budget.start()
        assert budget.check_zone() == BudgetZone.GREEN

    def test_transitions_to_yellow_at_60pct(self):
        budget = TokenBudget(BudgetConfig(max_total_tokens=100_000))
        budget.start()
        budget.record_usage(prompt_tokens=55_000, completion_tokens=5_000)
        assert budget.check_zone() == BudgetZone.YELLOW

    def test_transitions_to_red_at_85pct(self):
        budget = TokenBudget(BudgetConfig(max_total_tokens=100_000))
        budget.start()
        budget.record_usage(prompt_tokens=86_000, completion_tokens=0)
        assert budget.check_zone() == BudgetZone.RED

    def test_circuit_breaker_at_95pct(self):
        budget = TokenBudget(BudgetConfig(max_total_tokens=100_000))
        budget.start()
        budget.record_usage(prompt_tokens=96_000, completion_tokens=0)
        assert budget.check_zone() == BudgetZone.BREAKER
        assert budget.should_stop()

    def test_no_model_degradation_red_stops_only(self):
        """Budget does NOT degrade model — only warns and eventually stops."""
        budget = TokenBudget(BudgetConfig(max_total_tokens=100_000))
        budget.start()
        budget.record_usage(prompt_tokens=86_000, completion_tokens=0)
        zone = budget.check_zone()
        assert zone == BudgetZone.RED
        assert not budget.should_stop()  # RED warns but doesn't stop
        # Push to breaker
        budget.record_usage(prompt_tokens=10_000, completion_tokens=0)
        budget.check_zone()
        assert budget.should_stop()

    def test_tool_call_limit_triggers_breaker(self):
        budget = TokenBudget(BudgetConfig(max_tool_calls=5))
        budget.start()
        for _ in range(5):
            budget.record_tool_call()
        budget.check_zone()
        assert budget.should_stop()

    def test_disabled_budget_always_green(self):
        budget = TokenBudget(BudgetConfig(enabled=False))
        budget.start()
        budget.record_usage(prompt_tokens=999_000, completion_tokens=999_000)
        assert budget.check_zone() == BudgetZone.GREEN
        assert not budget.should_stop()

    def test_warnings_accumulate(self):
        budget = TokenBudget(BudgetConfig(max_total_tokens=100_000))
        budget.start()
        budget.record_usage(prompt_tokens=65_000, completion_tokens=0)
        budget.check_zone()
        assert len(budget.state.warnings) >= 1


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_register_and_retrieve(self):
        registry = ToolRegistry()
        registry.register(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            handler=lambda: "",
            risk_level="low",
        )
        spec = registry.get("test_tool")
        assert spec is not None
        assert spec.risk_level == RiskLevel.LOW

    def test_permission_allowed(self):
        registry = ToolRegistry()
        registry.register(
            name="read_file",
            description="Read a file",
            parameters={},
            handler=lambda: "",
            risk_level="low",
            allowed_agents=["explore", "general", "code"],
        )
        perm = registry.check_permission("read_file", "explore")
        assert perm["allowed"]

    def test_permission_denied_for_wrong_agent(self):
        registry = ToolRegistry()
        registry.register(
            name="run_command",
            description="Run command",
            parameters={},
            handler=lambda: "",
            risk_level="critical",
            allowed_agents=["general"],
        )
        perm = registry.check_permission("run_command", "explore")
        assert not perm["allowed"]

    def test_unknown_tool_denied(self):
        registry = ToolRegistry()
        perm = registry.check_permission("nonexistent", "general")
        assert not perm["allowed"]

    def test_definitions_for_agent_filters(self):
        registry = ToolRegistry()
        registry.register("read", "R", {}, lambda: "", risk_level="low", allowed_agents=["explore"])
        registry.register("write", "W", {}, lambda: "", risk_level="high", allowed_agents=["general"])
        defs = registry.definitions_for_agent("explore")
        # definitions_for_agent returns list[dict], not objects
        names = [d["name"] for d in defs]
        assert "read" in names
        assert "write" not in names

    def test_get_registry_singleton(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2


# ---------------------------------------------------------------------------
# FailureHandler
# ---------------------------------------------------------------------------


class TestFailureHandler:
    def test_classify_timeout(self):
        handler = FailureHandler()
        ft = handler.classify("run_command", "timeout after 60s")
        assert ft == FailureType.TOOL_TIMEOUT

    def test_classify_permission(self):
        handler = FailureHandler()
        ft = handler.classify("write_file", "permission denied for /etc/passwd")
        assert ft == FailureType.PERMISSION_DENIED

    def test_classify_rate_limit(self):
        handler = FailureHandler()
        ft = handler.classify("web_search", "rate limit exceeded 429")
        assert ft == FailureType.RATE_LIMITED

    def test_non_retryable_abort(self):
        handler = FailureHandler()
        action = handler.handle("write_file", "permission denied", FailureType.PERMISSION_DENIED)
        assert action == FailureAction.ABORT

    def test_doom_loop_abort(self):
        handler = FailureHandler()
        action = handler.handle("read_file", "doom loop detected", FailureType.DOOM_LOOP)
        assert action == FailureAction.ABORT

    def test_runtime_error_retries(self):
        handler = FailureHandler()
        a1 = handler.handle("read_file", "some error", FailureType.RUNTIME_ERROR)
        assert a1 == FailureAction.RETRY
        # After max retries, should escalate
        for _ in range(2):
            handler.handle("read_file", "some error", FailureType.RUNTIME_ERROR)
        final = handler.handle("read_file", "some error", FailureType.RUNTIME_ERROR)
        assert final == FailureAction.ABORT

    def test_history_tracking(self):
        handler = FailureHandler()
        handler.handle("tool1", "err1")
        handler.handle("tool2", "err2")
        history = handler.get_history()
        assert len(history) == 2

    def test_reset_clears_retries(self):
        handler = FailureHandler()
        handler.handle("read_file", "err", FailureType.RUNTIME_ERROR)
        handler.reset()
        history = handler.get_history()
        assert len(history) == 1
        # After reset, should get retry again
        action = handler.handle("read_file", "err", FailureType.RUNTIME_ERROR)
        assert action == FailureAction.RETRY


# ---------------------------------------------------------------------------
# ExecutionTrace
# ---------------------------------------------------------------------------


class TestExecutionTrace:
    def test_record_events(self):
        trace = ExecutionTrace(session_id="test")
        trace.start("hello")
        trace.step_start(1, "glm-4-plus")
        trace.tool_call("read_file", {"path": "main.py"}, risk="low")
        trace.tool_result("read_file", "file contents", duration_ms=50)
        trace.step_end(1, True, 100)

        # Check entries BEFORE finish() — finish() calls save() which clears entries
        events = [e.event for e in trace.entries]
        assert "trace_start" in events
        assert "tool_call" in events
        assert "tool_result" in events

    def test_finish_saves_and_clears(self):
        trace = ExecutionTrace(session_id="test")
        trace.start("hello")
        trace.finish(output="done", success=True)
        # After finish, entries are cleared (saved to disk)
        assert len(trace.entries) == 0

    def test_doom_loop_event(self):
        trace = ExecutionTrace()
        trace.doom_loop("read_file", 3)
        events = [e.event for e in trace.entries]
        assert "doom_loop" in events

    def test_circuit_break_event(self):
        trace = ExecutionTrace()
        trace.circuit_break("token budget exhausted")
        events = [e.event for e in trace.entries]
        assert "circuit_break" in events

    def test_budget_event(self):
        trace = ExecutionTrace()
        trace.budget_event("yellow", 60000)
        budget_events = [e for e in trace.entries if e.event == "budget"]
        assert len(budget_events) == 1
        assert budget_events[0].data["zone"] == "yellow"

    def test_summary(self):
        trace = ExecutionTrace()
        trace.start("test")
        trace.tool_call("t1", {}, risk="low")
        trace.tool_call("t2", {}, risk="medium")
        summary = trace.get_summary()
        assert summary["tool_calls"] == 2


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------


class TestComponentEval:
    def test_successful_tool_call(self):
        score = eval_tool_call("read_file", {"path": "a.py"}, "contents...", 100)
        assert score.success
        assert score.result_relevance >= 0.5

    def test_failed_tool_call(self):
        score = eval_tool_call("read_file", {"path": "a.py"}, "timeout", 5000, is_error=True)
        assert not score.success
        assert score.error_type == "timeout"

    def test_slow_tool_call(self):
        score = eval_tool_call("read_file", {"path": "a.py"}, "contents...", 10000)
        assert any("Slow" in i for i in score.issues)


class TestTrajectoryEval:
    def test_clean_trajectory(self):
        entries = [
            {"event": "tool_call", "tool": "read_file", "arguments": {"path": "a.py"}},
            {"event": "tool_result", "tool": "read_file", "duration_ms": 100},
            {"event": "tool_call", "tool": "grep", "arguments": {"pattern": "test"}},
            {"event": "tool_result", "tool": "grep", "duration_ms": 200},
            {"event": "step_end"},
        ]
        score = eval_trajectory(entries)
        assert score.total_tool_calls == 2
        assert score.unique_tools == 2
        assert not score.has_doom_loop
        assert score.score > 0.4

    def test_doom_loop_penalty(self):
        entries = [
            {"event": "tool_call", "tool": "read_file", "arguments": {"path": "a.py"}},
            {"event": "doom_loop", "tool": "read_file", "count": 3},
            {"event": "step_end"},
        ]
        score = eval_trajectory(entries)
        assert score.has_doom_loop
        assert score.score < 0.4

    def test_repeated_calls_penalty(self):
        entries = []
        for i in range(5):
            entries.append({"event": "tool_call", "tool": "read_file",
                            "arguments": {"path": "same.py"}})
            entries.append({"event": "tool_result", "tool": "read_file", "duration_ms": 100})
        entries.append({"event": "step_end"})
        score = eval_trajectory(entries)
        assert score.repeated_calls >= 4


class TestTaskCompletion:
    def test_successful_code_task(self):
        entries = [
            {"event": "tool_call", "tool": "edit_file", "arguments": {"file_path": "a.py"}},
            {"event": "tool_result", "tool": "edit_file"},
            {"event": "tool_call", "tool": "read_file", "arguments": {"path": "a.py"}},
            {"event": "tool_result", "tool": "read_file"},
        ]
        score = eval_task_completion(
            user_input="fix the bug in a.py",
            agent_output="Successfully fixed the bug in a.py by adding null check.",
            trace_entries=entries,
        )
        assert score.has_code_changes
        assert score.has_verification
        assert score.goal_met

    def test_code_task_without_changes(self):
        score = eval_task_completion(
            user_input="fix the bug in main.py",
            agent_output="I found the issue but couldn't fix it.",
            trace_entries=[],
        )
        assert not score.has_code_changes
        assert any("no file modifications" in i for i in score.issues)


# ---------------------------------------------------------------------------
# Integration: ToolExecutor with Harness
# ---------------------------------------------------------------------------


class _StubProvider:
    """Minimal provider stub for ToolExecutor tests (avoids abstract class issues)."""
    pass


class TestToolExecutorHarness:
    """Test that ToolExecutor properly integrates all Harness components."""

    def test_executor_accepts_harness(self):
        from app.llm.tool_executor import ToolExecutor

        executor = ToolExecutor(_StubProvider())
        budget = TokenBudget(BudgetConfig())
        trace = ExecutionTrace()
        handler = FailureHandler()
        registry = ToolRegistry()

        executor.set_budget(budget)
        executor.set_trace(trace)
        executor.set_failure_handler(handler)
        executor.set_registry(registry)

        assert executor._budget is budget
        assert executor._trace is trace
        assert executor._failure_handler is handler
        assert executor._registry is registry

    def test_tool_registration_with_governance(self):
        from app.llm.tool_executor import ToolExecutor

        executor = ToolExecutor(_StubProvider())
        registry = ToolRegistry()
        executor.set_registry(registry)

        executor.register(
            name="test_tool",
            description="Test",
            parameters={"type": "object", "properties": {}},
            handler=lambda: "ok",
            risk_level="critical",
            allowed_agents=["general"],
            timeout=60,
            requires_approval=True,
        )

        spec = registry.get("test_tool")
        assert spec is not None
        assert spec.risk_level == RiskLevel.CRITICAL

        # Other agents should be denied
        perm = registry.check_permission("test_tool", "explore")
        assert not perm["allowed"]

        # General agent should be allowed
        perm = registry.check_permission("test_tool", "general")
        assert perm["allowed"]

    def test_doom_loop_detection(self):
        from app.llm.tool_executor import ToolExecutor, DOOM_LOOP_THRESHOLD

        executor = ToolExecutor(_StubProvider())

        # Build history with same call repeated
        history = [("read_file", '{"path": "x.py"}')] * (DOOM_LOOP_THRESHOLD + 1)
        result = executor._check_doom_loop(history)
        assert result == "read_file"

    def test_no_doom_loop_with_varied_calls(self):
        from app.llm.tool_executor import ToolExecutor

        executor = ToolExecutor(_StubProvider())

        history = [
            ("read_file", '{"path": "a.py"}'),
            ("grep", '{"pattern": "test"}'),
            ("read_file", '{"path": "b.py"}'),
        ]
        result = executor._check_doom_loop(history)
        assert result is None

    def test_truncation_for_model(self):
        from app.llm.tool_executor import ToolExecutor

        executor = ToolExecutor(_StubProvider())
        long_content = "x" * 20000
        truncated = executor._truncate_for_model(long_content)
        assert len(truncated) < len(long_content)
        assert "[truncated" in truncated
