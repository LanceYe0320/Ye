"""Tests for agent result formatting and data classes (no API calls)."""
from __future__ import annotations

from app.agents import AgentResult, format_group_results


class TestAgentResult:
    def test_success_fields(self):
        r = AgentResult(role="explore", task="find bugs", success=True,
                        output="found 3 bugs", duration_seconds=1.5)
        assert r.success is True
        assert r.role == "explore"
        assert r.duration_seconds == 1.5

    def test_failure_fields(self):
        r = AgentResult(role="general", task="do thing", success=False,
                        output="Agent failed: timeout", duration_seconds=10.0)
        assert r.success is False


class TestFormatGroupResults:
    def test_empty_results(self):
        out = format_group_results([])
        assert "0/0" in out

    def test_mixed_success_failure(self):
        results = [
            AgentResult(role="explore", task="task one", success=True,
                        output="done one", duration_seconds=1.0),
            AgentResult(role="general", task="task two", success=False,
                        output="failed two", duration_seconds=2.0),
        ]
        out = format_group_results(results)
        assert "1/2" in out
        assert "task one" in out
        assert "task two" in out
        assert "OK" in out
        assert "FAILED" in out

    def test_long_task_truncated(self):
        long_task = "x" * 200
        r = AgentResult(role="explore", task=long_task, success=True,
                        output="out", duration_seconds=1.0)
        out = format_group_results([r])
        assert "..." in out
