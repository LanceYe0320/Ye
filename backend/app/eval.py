"""Agent Evaluation System — 4-layer quality assessment.


Article reference: "Harness 第四层 — 评估体系，不要只看答案，要看轨迹"

Layers:
  1. Component Eval — single tool/agent call quality
  2. Trajectory Eval — execution path analysis
  3. Task Completion — did the agent achieve the goal?
  4. End-to-End — user-facing business metrics

"成熟 Eval 一定是混合的：确定性检查 + LLM-as-Judge + 人工抽检"
"""

from __future__ import annotations
import logging

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.execution_trace import read_traces


# ---------------------------------------------------------------------------
# Layer 1: Component Eval — evaluate a single tool call or agent step
# ---------------------------------------------------------------------------


logger = logging.getLogger(__name__)
@dataclass
class ComponentScore:
    tool_name: str
    success: bool
    latency_ms: float
    error_type: str = ""  # "timeout", "permission", "invalid_args", "runtime", ""
    result_relevance: float = 0.5  # 0-1 heuristic
    issues: list[str] = field(default_factory=list)


def eval_tool_call(
    tool_name: str,
    arguments: dict,
    result: str,
    duration_ms: float,
    is_error: bool = False,
) -> ComponentScore:
    """Evaluate a single tool call."""
    score = ComponentScore(
        tool_name=tool_name,
        success=not is_error,
        latency_ms=duration_ms,
    )

    # Check for common issues
    if is_error:
        if "timeout" in result.lower():
            score.error_type = "timeout"
        elif "permission" in result.lower() or "denied" in result.lower():
            score.error_type = "permission"
        elif "not found" in result.lower():
            score.error_type = "invalid_args"
        else:
            score.error_type = "runtime"
        score.issues.append(f"Tool failed: {result[:100]}")
    else:
        # Heuristic: empty or very short results from read tools are suspicious
        if tool_name in ("read_file", "grep", "glob", "list_files") and len(result.strip()) < 10:
            score.result_relevance = 0.2
            score.issues.append("Very short result from read tool")
        # Very long results may indicate poor targeting
        elif len(result) > 5000 and tool_name not in ("web_fetch", "web_search"):
            score.result_relevance = 0.4
            score.issues.append(f"Very long result ({len(result)} chars) — may need more specific query")
        else:
            score.result_relevance = 0.8

    # Latency check
    expected_max = {"read_file": 500, "grep": 5000, "run_command": 10000,
                    "web_search": 5000, "web_fetch": 10000, "glob": 2000}
    max_ms = expected_max.get(tool_name, 3000)
    if duration_ms > max_ms:
        score.issues.append(f"Slow: {duration_ms:.0f}ms (expected <{max_ms}ms)")

    return score


# ---------------------------------------------------------------------------
# Layer 2: Trajectory Eval — analyze execution path
# ---------------------------------------------------------------------------

@dataclass
class TrajectoryScore:
    total_steps: int
    total_tool_calls: int
    repeated_calls: int  # Same tool+args called multiple times
    unique_tools: int
    has_doom_loop: bool
    has_backtrack: bool  # Agent tried, failed, tried differently
    tool_diversity: float  # 0-1 ratio of unique tools used
    avg_step_duration_ms: float
    issues: list[str] = field(default_factory=list)
    score: float = 0.5  # 0-1 overall trajectory quality


def eval_trajectory(trace_entries: list) -> TrajectoryScore:
    """Evaluate the execution trajectory from trace entries (TraceEntry objects or dicts)."""
    # Normalize: convert TraceEntry objects to dicts
    normalized = []
    for e in trace_entries:
        if isinstance(e, dict):
            normalized.append(e)
        else:
            # TraceEntry dataclass
            normalized.append({"event": e.event, **e.data})

    result = TrajectoryScore(
        total_steps=0,
        total_tool_calls=0,
        repeated_calls=0,
        unique_tools=0,
        has_doom_loop=False,
        has_backtrack=False,
        tool_diversity=0.0,
        avg_step_duration_ms=0,
    )

    if not normalized:
        return result

    # Count events
    tool_calls = [e for e in normalized if e.get("event") == "tool_call"]
    tool_results = [e for e in normalized if e.get("event") == "tool_result"]
    step_ends = [e for e in normalized if e.get("event") == "step_end"]
    doom_loops = [e for e in normalized if e.get("event") == "doom_loop"]
    circuit_breaks = [e for e in normalized if e.get("event") == "circuit_break"]
    errors = [e for e in normalized if e.get("event") == "error"]

    result.total_steps = len(step_ends)
    result.total_tool_calls = len(tool_calls)
    result.has_doom_loop = len(doom_loops) > 0

    # Count unique tools and repeated calls
    seen_calls: list[tuple[str, str]] = []
    tool_names: set[str] = set()
    for tc in tool_calls:
        tool = tc.get("tool", "")
        args_str = json.dumps(tc.get("arguments", {}), sort_keys=True)[:100]
        call_sig = (tool, args_str)
        tool_names.add(tool)
        if call_sig in seen_calls:
            result.repeated_calls += 1
        seen_calls.append(call_sig)

    result.unique_tools = len(tool_names)
    result.tool_diversity = len(tool_names) / max(1, len(tool_calls))

    # Average duration
    durations = [tr.get("duration_ms", 0) for tr in tool_results if tr.get("duration_ms")]
    if durations:
        result.avg_step_duration_ms = sum(durations) / len(durations)

    # Detect backtracking: error followed by different tool
    if errors:
        result.has_backtrack = True

    # Score calculation
    score = 0.5

    # Penalty: doom loop
    if result.has_doom_loop:
        score -= 0.2
        result.issues.append("Doom loop detected — agent got stuck")

    # Penalty: circuit breaker
    if circuit_breaks:
        score -= 0.15
        result.issues.append("Circuit breaker triggered — budget exhausted")

    # Penalty: too many repeated calls
    if result.repeated_calls > 3:
        score -= 0.1
        result.issues.append(f"High repeated calls: {result.repeated_calls}")

    # Penalty: too many errors
    if len(errors) > 2:
        score -= 0.1
        result.issues.append(f"Multiple errors: {len(errors)}")

    # Bonus: good tool diversity
    if result.tool_diversity > 0.5 and result.total_tool_calls > 2:
        score += 0.15

    # Bonus: backtracking (shows adaptability)
    if result.has_backtrack and not result.has_doom_loop:
        score += 0.05

    result.score = max(0.0, min(1.0, score))
    return result


# ---------------------------------------------------------------------------
# Layer 3: Task Completion — did the agent achieve the goal?
# ---------------------------------------------------------------------------

@dataclass
class CompletionScore:
    goal_met: bool
    completeness: float  # 0-1
    output_quality: float  # 0-1 heuristic
    has_code_changes: bool
    has_verification: bool  # Agent verified its own work
    issues: list[str] = field(default_factory=list)


def eval_task_completion(
    user_input: str,
    agent_output: str,
    trace_entries: list,
) -> CompletionScore:
    """Evaluate whether the task was completed."""
    # Normalize
    normalized = []
    for e in trace_entries:
        if isinstance(e, dict):
            normalized.append(e)
        else:
            normalized.append({"event": e.event, **e.data})

    score = CompletionScore(
        goal_met=False,
        completeness=0.0,
        output_quality=0.5,
        has_code_changes=False,
        has_verification=False,
    )

    output_lower = agent_output.lower()
    input_lower = user_input.lower()

    # Check for code changes (write_file, edit_file in trace)
    tools_used = {e.get("tool", "") for e in normalized if e.get("event") == "tool_call"}
    score.has_code_changes = bool(tools_used & {"write_file", "edit_file"})

    # Check for verification (agent read file after writing)
    tool_sequence = [e.get("tool", "") for e in normalized if e.get("event") == "tool_call"]
    for i, tool in enumerate(tool_sequence):
        if tool in ("write_file", "edit_file") and i + 1 < len(tool_sequence):
            if tool_sequence[i + 1] == "read_file":
                score.has_verification = True
                break

    # Heuristic completeness checks
    # 1. Did the output address the user's request?
    input_keywords = set(re.findall(r'\w{3,}', input_lower))
    output_keywords = set(re.findall(r'\w{3,}', output_lower))
    overlap = len(input_keywords & output_keywords) / max(1, len(input_keywords))
    score.completeness = min(1.0, overlap * 1.5)

    # 2. Does the output have substance?
    if len(agent_output.strip()) < 20:
        score.output_quality = 0.1
        score.issues.append("Very short output")
    elif len(agent_output.strip()) > 50:
        score.output_quality = 0.7

    # 3. Did it error out?
    if "error" in output_lower and len(agent_output) < 100:
        score.output_quality = 0.2
        score.issues.append("Output is mostly error messages")
    elif "i couldn't" in output_lower or "无法" in output_lower or "failed" in output_lower:
        score.issues.append("Agent reported failure")
        score.output_quality = 0.3
    else:
        # Check for success indicators
        success_indicators = ["successfully", "done", "完成", "已修复", "fixed", "created", "implemented"]
        if any(si in output_lower for si in success_indicators):
            score.goal_met = True
            score.output_quality = min(1.0, score.output_quality + 0.2)

    # Code task without code changes
    if any(kw in input_lower for kw in ["fix", "implement", "写", "修", "改", "add"]):
        if not score.has_code_changes:
            score.issues.append("Code task but no file modifications detected")
            score.completeness *= 0.5

    return score


# ---------------------------------------------------------------------------
# Layer 4: End-to-End — session-level metrics (persistent)
# ---------------------------------------------------------------------------

_METRICS_FILE = Path.home() / ".ye" / "metrics.json"


@dataclass
class SessionMetrics:
    session_id: str
    tasks_attempted: int = 0
    tasks_completed: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    avg_trajectory_score: float = 0.0
    avg_completion_score: float = 0.0
    doom_loops: int = 0
    circuit_breaks: int = 0
    duration_seconds: float = 0


def record_session_metrics(metrics: SessionMetrics):
    """Append session metrics for trend analysis."""
    _METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if _METRICS_FILE.is_file():
        try:
            data = json.loads(_METRICS_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("suppressed", exc_info=True)
            pass

    sessions = data.setdefault("sessions", [])
    sessions.append({
        "id": metrics.session_id,
        "tasks_attempted": metrics.tasks_attempted,
        "tasks_completed": metrics.tasks_completed,
        "tokens": metrics.total_tokens,
        "tool_calls": metrics.total_tool_calls,
        "avg_traj_score": metrics.avg_trajectory_score,
        "avg_complete_score": metrics.avg_completion_score,
        "doom_loops": metrics.doom_loops,
        "circuit_breaks": metrics.circuit_breaks,
        "duration": round(metrics.duration_seconds, 1),
        "recorded_at": time.time(),
    })

    # Keep last 100 sessions
    if len(sessions) > 100:
        data["sessions"] = sessions[-100:]

    _METRICS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_eval_summary() -> str:
    """Get a summary of historical eval metrics."""
    if not _METRICS_FILE.is_file():
        return "No evaluation metrics recorded yet."

    try:
        data = json.loads(_METRICS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return "Error reading metrics."

    sessions = data.get("sessions", [])
    if not sessions:
        return "No evaluation metrics recorded yet."

    total = len(sessions)
    completed = sum(1 for s in sessions if s.get("tasks_completed", 0) > 0)
    avg_tokens = sum(s.get("tokens", 0) for s in sessions) / total
    avg_traj = sum(s.get("avg_traj_score", 0) for s in sessions) / total
    avg_complete = sum(s.get("avg_complete_score", 0) for s in sessions) / total
    doom_loops = sum(s.get("doom_loops", 0) for s in sessions)
    breaks = sum(s.get("circuit_breaks", 0) for s in sessions)

    lines = [
        f"  Sessions: {total}",
        f"  Completion Rate: {completed}/{total} ({completed*100//max(1,total)}%)",
        f"  Avg Tokens/Session: {avg_tokens:,.0f}",
        f"  Avg Trajectory Score: {avg_traj:.2f}/1.0",
        f"  Avg Completion Score: {avg_complete:.2f}/1.0",
        f"  Doom Loops (total): {doom_loops}",
        f"  Circuit Breaks (total): {breaks}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM-as-Judge (optional Layer 3 enhancement)
# ---------------------------------------------------------------------------


async def eval_task_completion_with_llm(
    user_input: str,
    agent_output: str,
    provider: Any,
    model: str = "",
) -> dict[str, float]:
    """Use LLM as Judge for semantic evaluation of task completion.

    Returns {"relevance": 0-1, "quality": 0-1, "completeness": 0-1}.
    Falls back to neutral scores on parse failure.
    """
    from app.llm.base_provider import ChatMessage

    judge_prompt = (
        "You are evaluating an AI coding assistant's response. "
        "Score the following on a 0-1 scale. "
        "Respond with ONLY a JSON object: "
        '{"relevance": 0.0, "quality": 0.0, "completeness": 0.0, "reason": "brief explanation"}\n\n'
        f"User request: {user_input}\n\n"
        f"Assistant response:\n{agent_output[:3000]}"
    )

    messages = [
        ChatMessage(role="system", content=judge_prompt),
        ChatMessage(role="user", content="Evaluate the above response."),
    ]

    response_text = ""
    async for chunk in provider.chat(
        messages=messages, model=model, max_tokens=300, temperature=0.1,
    ):
        if chunk.type == "text_delta":
            response_text += chunk.text

    # Parse the judge response
    try:
        json_match = re.search(r'\{[^{}]*\}', response_text)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "relevance": min(1.0, max(0.0, float(data.get("relevance", 0.5)))),
                "quality": min(1.0, max(0.0, float(data.get("quality", 0.5)))),
                "completeness": min(1.0, max(0.0, float(data.get("completeness", 0.5)))),
            }
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    return {"relevance": 0.5, "quality": 0.5, "completeness": 0.5}


# ---------------------------------------------------------------------------
# Trend analysis (Layer 4 enhancement)
# ---------------------------------------------------------------------------


def analyze_trends(window: int = 20) -> str:
    """Analyze session metrics for degradation patterns.

    Compares first half vs second half of recent sessions.
    Warns on: declining scores, increasing doom loops, rising error rates.
    """
    if not _METRICS_FILE.is_file():
        return "No metrics data available for trend analysis."

    try:
        data = json.loads(_METRICS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return "Error reading metrics for trend analysis."

    sessions = data.get("sessions", [])
    if len(sessions) < 3:
        return f"Need at least 3 sessions for trend analysis (have {len(sessions)})."

    recent = sessions[-window:]
    n = len(recent)
    mid = n // 2
    first_half = recent[:mid]
    second_half = recent[mid:]

    def avg(field: str, subset: list[dict]) -> float:
        vals = [s.get(field, 0) for s in subset]
        return sum(vals) / max(1, len(vals))

    comp_early = avg("avg_complete_score", first_half)
    comp_late = avg("avg_complete_score", second_half)
    comp_trend = comp_late - comp_early

    traj_early = avg("avg_traj_score", first_half)
    traj_late = avg("avg_traj_score", second_half)
    traj_trend = traj_late - traj_early

    doom_early = sum(s.get("doom_loops", 0) for s in first_half)
    doom_late = sum(s.get("doom_loops", 0) for s in second_half)

    lines = [
        f"Trend Analysis (last {n} sessions):",
        "",
        f"  Completion Score: {comp_early:.2f} -> {comp_late:.2f} ({comp_trend:+.2f})",
        f"  Trajectory Score: {traj_early:.2f} -> {traj_late:.2f} ({traj_trend:+.2f})",
        f"  Doom Loops: {doom_early} -> {doom_late}",
    ]

    warnings = []
    if comp_trend < -0.1:
        warnings.append("Completion scores declining significantly")
    if traj_trend < -0.1:
        warnings.append("Trajectory scores declining significantly")
    if doom_late > doom_early * 1.5 and doom_late > 2:
        warnings.append("Doom loop frequency increasing")

    if warnings:
        lines.append("")
        lines.append("  WARNINGS:")
        for w in warnings:
            lines.append(f"    - {w}")
    else:
        lines.append("")
        lines.append("  No significant degradation detected.")

    return "\n".join(lines)
