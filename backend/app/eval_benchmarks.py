"""Benchmark test cases and regression suite for Ye eval system.

Provides:
  - Canonical test cases (input -> expected behavior patterns)
  - Benchmark runner for evaluating traces against expected patterns
  - Regression suite for detecting score degradation over time
  - Historical result persistence
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.eval import eval_task_completion, eval_trajectory


_BENCHMARKS_DIR = Path.home() / ".ye" / "benchmarks"


# ---------------------------------------------------------------------------
# Benchmark case definition
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkCase:
    """A canonical test case for benchmarking agent behavior."""
    id: str
    category: str  # "code_fix", "code_create", "research", "refactor", "review"
    user_input: str
    expected_tools: list[str]  # Tools that SHOULD appear
    forbidden_tools: list[str]  # Tools that should NOT appear
    expected_keywords: list[str]  # Keywords expected in output
    min_completion_score: float  # Minimum acceptable completeness
    min_trajectory_score: float  # Minimum acceptable trajectory score
    description: str = ""


# ---------------------------------------------------------------------------
# Canonical benchmark suite
# ---------------------------------------------------------------------------


def get_benchmark_cases() -> list[BenchmarkCase]:
    """Return the canonical benchmark test suite."""
    return [
        BenchmarkCase(
            id="fix_simple_bug",
            category="code_fix",
            user_input="Fix the null pointer error in app/main.py line 42",
            expected_tools=["read_file", "edit_file"],
            forbidden_tools=["write_file"],
            expected_keywords=["null", "check", "fix", "None"],
            min_completion_score=0.6,
            min_trajectory_score=0.4,
            description="Simple bug fix: read-edit-verify pattern",
        ),
        BenchmarkCase(
            id="add_feature",
            category="code_create",
            user_input="Add input validation to the login endpoint in app/api/auth.py",
            expected_tools=["read_file", "edit_file"],
            forbidden_tools=[],
            expected_keywords=["validation", "input", "check"],
            min_completion_score=0.5,
            min_trajectory_score=0.4,
            description="Feature addition: research + implement",
        ),
        BenchmarkCase(
            id="code_review",
            category="review",
            user_input="Review the security of the authentication module",
            expected_tools=["read_file", "grep", "glob"],
            forbidden_tools=["edit_file", "write_file"],
            expected_keywords=["security", "vulnerability", "recommendation"],
            min_completion_score=0.5,
            min_trajectory_score=0.5,
            description="Code review should be read-only",
        ),
        BenchmarkCase(
            id="research_codebase",
            category="research",
            user_input="Explain how the memory system works in this project",
            expected_tools=["read_file", "grep", "glob"],
            forbidden_tools=["edit_file", "write_file"],
            expected_keywords=["memory", "retention", "prune"],
            min_completion_score=0.4,
            min_trajectory_score=0.3,
            description="Research should explore without modifying",
        ),
        BenchmarkCase(
            id="refactor_module",
            category="refactor",
            user_input="Refactor tool_executor.py to reduce the run_agentic_loop method size",
            expected_tools=["read_file", "edit_file", "glob", "grep"],
            forbidden_tools=[],
            expected_keywords=["refactor", "extract", "method"],
            min_completion_score=0.5,
            min_trajectory_score=0.4,
            description="Refactoring: understand, edit, verify",
        ),
    ]


# ---------------------------------------------------------------------------
# Benchmark result
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    """Result of evaluating a single benchmark case."""
    case_id: str
    category: str
    passed: bool
    completion_score: float
    trajectory_score: float
    llm_scores: dict[str, float] | None = None
    tool_match_pct: float = 0.0
    violations: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def run_benchmark_case(
    case: BenchmarkCase,
    trace_entries: list[dict],
    agent_output: str,
) -> BenchmarkResult:
    """Evaluate a single benchmark case against actual agent behavior."""
    traj_score = eval_trajectory(trace_entries)
    comp_score = eval_task_completion(case.user_input, agent_output, trace_entries)

    # Tool usage check
    tools_used = [e.get("tool", "") for e in trace_entries if e.get("event") == "tool_call"]
    expected_found = sum(1 for t in case.expected_tools if t in tools_used)
    tool_match = expected_found / max(1, len(case.expected_tools))

    # Forbidden tool violations
    violations = [t for t in tools_used if t in case.forbidden_tools]

    # Keyword check
    output_lower = agent_output.lower()
    keywords_found = sum(1 for kw in case.expected_keywords if kw.lower() in output_lower)

    # Pass/fail determination
    passed = (
        traj_score.score >= case.min_trajectory_score
        and comp_score.completeness >= case.min_completion_score
        and len(violations) == 0
        and keywords_found >= len(case.expected_keywords) * 0.5
    )

    issues = []
    if traj_score.score < case.min_trajectory_score:
        issues.append(f"Trajectory {traj_score.score:.2f} < min {case.min_trajectory_score}")
    if comp_score.completeness < case.min_completion_score:
        issues.append(f"Completion {comp_score.completeness:.2f} < min {case.min_completion_score}")
    if violations:
        issues.append(f"Used forbidden tools: {violations}")
    if keywords_found < len(case.expected_keywords) * 0.5:
        issues.append(f"Keywords: {keywords_found}/{len(case.expected_keywords)} found")

    return BenchmarkResult(
        case_id=case.id,
        category=case.category,
        passed=passed,
        completion_score=comp_score.completeness,
        trajectory_score=traj_score.score,
        tool_match_pct=tool_match,
        violations=violations,
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Result persistence & regression
# ---------------------------------------------------------------------------


def save_benchmark_result(result: BenchmarkResult):
    """Save a benchmark result for regression tracking."""
    _BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
    results_file = _BENCHMARKS_DIR / f"{result.case_id}.json"

    history: list[dict] = []
    if results_file.is_file():
        try:
            history = json.loads(results_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    history.append({
        "timestamp": time.time(),
        "passed": result.passed,
        "completion_score": result.completion_score,
        "trajectory_score": result.trajectory_score,
        "tool_match_pct": result.tool_match_pct,
        "violations": result.violations,
        "issues": result.issues,
    })

    if len(history) > 50:
        history = history[-50:]

    results_file.write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def run_regression_check() -> str:
    """Check if recent results show regression vs historical baseline.

    Compares the latest run against the average of the previous 5 runs.
    """
    cases = get_benchmark_cases()
    lines = ["Regression Check Report", "=" * 40]
    regressions = []
    improvements = []

    for case in cases:
        results_file = _BENCHMARKS_DIR / f"{case.id}.json"
        if not results_file.is_file():
            lines.append(f"\n  {case.id}: No historical data")
            continue

        try:
            history = json.loads(results_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        if len(history) < 2:
            lines.append(f"\n  {case.id}: Need >= 2 runs for regression check")
            continue

        latest = history[-1]
        baseline = history[-6:-1]
        if not baseline:
            baseline = [history[0]]

        avg_comp = sum(r["completion_score"] for r in baseline) / len(baseline)
        avg_traj = sum(r["trajectory_score"] for r in baseline) / len(baseline)

        comp_delta = latest["completion_score"] - avg_comp
        traj_delta = latest["trajectory_score"] - avg_traj

        status = "OK"
        if comp_delta < -0.1 or traj_delta < -0.1:
            status = "REGRESSION"
            regressions.append(case.id)
        elif comp_delta > 0.05 or traj_delta > 0.05:
            status = "IMPROVED"
            improvements.append(case.id)

        lines.append(
            f"\n  {case.id}: {status}\n"
            f"    Completion: {latest['completion_score']:.2f} "
            f"(baseline: {avg_comp:.2f}, delta: {comp_delta:+.2f})\n"
            f"    Trajectory: {latest['trajectory_score']:.2f} "
            f"(baseline: {avg_traj:.2f}, delta: {traj_delta:+.2f})"
        )

    lines.append(f"\nSummary: {len(regressions)} regressions, {len(improvements)} improvements")
    return "\n".join(lines)
