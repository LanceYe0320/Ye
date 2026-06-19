"""Tests for Eval benchmark suite and trend analysis.

Covers:
  - BenchmarkCase definitions
  - run_benchmark_case: pass, forbidden tool, low score
  - Benchmark result persistence
  - Trend analysis with synthetic data
"""

import json
import tempfile
import time
from pathlib import Path

import pytest

from app.eval import SessionMetrics, analyze_trends, record_session_metrics
from app.eval_benchmarks import (
    BenchmarkResult,
    get_benchmark_cases,
    run_benchmark_case,
    run_regression_check,
    save_benchmark_result,
)


class TestBenchmarkCases:
    def test_five_cases_defined(self):
        cases = get_benchmark_cases()
        assert len(cases) == 5
        ids = {c.id for c in cases}
        assert "fix_simple_bug" in ids
        assert "code_review" in ids

    def test_all_cases_have_valid_thresholds(self):
        for case in get_benchmark_cases():
            assert 0 <= case.min_completion_score <= 1
            assert 0 <= case.min_trajectory_score <= 1


class TestRunBenchmarkCase:
    def test_pass_with_good_trace(self):
        case = get_benchmark_cases()[0]  # fix_simple_bug
        trace = [
            {"event": "tool_call", "tool": "read_file", "arguments": {"path": "main.py"}},
            {"event": "tool_result", "tool": "read_file", "duration_ms": 100},
            {"event": "tool_call", "tool": "edit_file", "arguments": {"file_path": "main.py"}},
            {"event": "tool_result", "tool": "edit_file", "duration_ms": 200},
            {"event": "step_end"},
        ]
        output = "Successfully fixed the null pointer error in app/main.py by adding a None check on line 42"
        result = run_benchmark_case(case, trace, output)
        assert result.passed
        assert result.completion_score > 0.5

    def test_fail_with_forbidden_tool(self):
        case = get_benchmark_cases()[2]  # code_review — read-only
        trace = [
            {"event": "tool_call", "tool": "read_file", "arguments": {"path": "auth.py"}},
            {"event": "tool_result", "tool": "read_file", "duration_ms": 100},
            {"event": "tool_call", "tool": "edit_file", "arguments": {"file_path": "auth.py"}},
            {"event": "tool_result", "tool": "edit_file", "duration_ms": 200},
            {"event": "step_end"},
        ]
        output = "Found a security vulnerability and fixed it."
        result = run_benchmark_case(case, trace, output)
        assert not result.passed
        assert "edit_file" in result.violations

    def test_fail_with_low_scores(self):
        case = get_benchmark_cases()[3]  # research
        trace = [{"event": "step_end"}]
        output = "idk"
        result = run_benchmark_case(case, trace, output)
        assert not result.passed

    def test_tool_match_calculation(self):
        case = get_benchmark_cases()[0]
        trace = [
            {"event": "tool_call", "tool": "read_file", "arguments": {}},
            {"event": "step_end"},
        ]
        result = run_benchmark_case(case, trace, "Fixed")
        # read_file matched, edit_file missing -> 50%
        assert result.tool_match_pct == 0.5


class TestBenchmarkPersistence:
    def test_save_and_load(self, tmp_path, monkeypatch):
        import app.eval_benchmarks as eb
        monkeypatch.setattr(eb, "_BENCHMARKS_DIR", tmp_path)

        result = BenchmarkResult(
            case_id="test_case", category="test", passed=True,
            completion_score=0.8, trajectory_score=0.7,
        )
        save_benchmark_result(result)

        data = json.loads((tmp_path / "test_case.json").read_text())
        assert len(data) == 1
        assert data[0]["passed"]

    def test_accumulates_results(self, tmp_path, monkeypatch):
        import app.eval_benchmarks as eb
        monkeypatch.setattr(eb, "_BENCHMARKS_DIR", tmp_path)

        for i in range(3):
            save_benchmark_result(BenchmarkResult(
                case_id="test", category="test", passed=True,
                completion_score=0.5 + i * 0.1, trajectory_score=0.5,
            ))

        data = json.loads((tmp_path / "test.json").read_text())
        assert len(data) == 3


class TestTrendAnalysis:
    def test_detects_declining_scores(self, tmp_path, monkeypatch):
        import app.eval as em
        monkeypatch.setattr(em, "_METRICS_FILE", tmp_path / "metrics.json")

        for i in range(10):
            score = 0.8 - i * 0.05
            record_session_metrics(SessionMetrics(
                session_id=f"s_{i}", tasks_completed=1 if score > 0.5 else 0,
                avg_trajectory_score=score, avg_completion_score=score,
            ))

        report = analyze_trends(window=10)
        assert "declining" in report.lower()

    def test_needs_minimum_sessions(self, tmp_path, monkeypatch):
        import app.eval as em
        monkeypatch.setattr(em, "_METRICS_FILE", tmp_path / "metrics.json")

        report = analyze_trends()
        assert "3 sessions" in report or "No metrics" in report

    def test_no_degradation_stable(self, tmp_path, monkeypatch):
        import app.eval as em
        monkeypatch.setattr(em, "_METRICS_FILE", tmp_path / "metrics.json")

        for i in range(10):
            record_session_metrics(SessionMetrics(
                session_id=f"s_{i}", tasks_completed=1,
                avg_trajectory_score=0.7, avg_completion_score=0.7,
            ))

        report = analyze_trends(window=10)
        assert "No significant degradation" in report
