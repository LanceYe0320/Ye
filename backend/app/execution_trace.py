"""Execution Trace — structured observability for Ye's agent loop.

Article reference: "Harness 第七层 — 可观测性和落地路线"

Records a complete trace of every agentic execution:
  - User input
  - Model routing decisions
  - Agent steps (input, output, duration)
  - Tool calls (name, args, result, duration, risk level)
  - Budget zone transitions
  - Failures and retries
  - Final output and eval hints

Traces are saved as JSONL to ~/.ye/traces/ and can be replayed for debugging.

"没有 Trace，就没有生产级 Agent。"
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_TRACE_DIR = Path.home() / ".ye" / "traces"


def _ensure_dir():
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TraceEntry:
    """A single entry in the execution trace."""
    timestamp: str
    event: str  # "step_start", "step_end", "tool_call", "tool_result", "budget", "error", "routing", "final"
    data: dict[str, Any] = field(default_factory=dict)


class ExecutionTrace:
    """Collects and persists a structured execution trace.

    Usage:
        trace = ExecutionTrace(session_id="20260527_120000")
        trace.start("user prompt here")

        # In the agentic loop:
        trace.tool_call("read_file", {"path": "main.py"}, risk="low")
        trace.tool_result("read_file", result_preview, duration_ms=120)
        trace.budget_event("yellow", tokens_used=60000)

        # At the end:
        trace.finish(output="final answer", success=True)
    """

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self.entries: list[TraceEntry] = []
        self._step_count = 0
        self._tool_call_count = 0
        self._start_time: float = 0

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _add(self, event: str, data: dict[str, Any] | None = None):
        self.entries.append(TraceEntry(
            timestamp=self._now(),
            event=event,
            data=data or {},
        ))

    def start(self, user_input: str):
        """Mark trace start with the user's input."""
        self._start_time = time.time()
        self._add("trace_start", {
            "session_id": self.session_id,
            "user_input": user_input[:500],
        })

    def step_start(self, step: int, model: str, budget_zone: str = "green"):
        """Mark the start of an agentic loop step."""
        self._step_count = step
        self._add("step_start", {
            "step": step,
            "model": model,
            "budget_zone": budget_zone,
        })

    def step_end(self, step: int, has_tool_calls: bool, text_length: int):
        """Mark the end of an agentic loop step."""
        self._add("step_end", {
            "step": step,
            "has_tool_calls": has_tool_calls,
            "text_length": text_length,
        })

    def tool_call(self, tool_name: str, arguments: dict, risk: str = "medium"):
        """Record a tool invocation."""
        self._tool_call_count += 1
        self._add("tool_call", {
            "tool": tool_name,
            "arguments": _truncate(arguments),
            "risk": risk,
            "call_index": self._tool_call_count,
        })

    def tool_result(self, tool_name: str, result: str, duration_ms: float = 0, blocked: bool = False):
        """Record a tool result."""
        self._add("tool_result", {
            "tool": tool_name,
            "result_preview": result[:300],
            "duration_ms": round(duration_ms, 1),
            "blocked": blocked,
        })

    def budget_event(self, zone: str, tokens_used: int, message: str = ""):
        """Record a budget zone transition."""
        self._add("budget", {
            "zone": zone,
            "tokens_used": tokens_used,
            "message": message,
        })

    def routing(self, from_model: str, to_model: str, reason: str):
        """Record a model routing decision."""
        self._add("routing", {
            "from_model": from_model,
            "to_model": to_model,
            "reason": reason,
        })

    def error(self, error_type: str, message: str, recoverable: bool = True):
        """Record an error."""
        self._add("error", {
            "type": error_type,
            "message": message,
            "recoverable": recoverable,
        })

    def finish(self, output: str = "", success: bool = True):
        """Mark trace completion and save to disk."""
        elapsed = time.time() - self._start_time if self._start_time else 0
        self._add("trace_end", {
            "success": success,
            "output_preview": output[:500],
            "total_steps": self._step_count,
            "total_tool_calls": self._tool_call_count,
            "duration_seconds": round(elapsed, 2),
        })
        self.save()

    def doom_loop(self, tool_name: str, repeat_count: int):
        """Record a doom loop detection."""
        self._add("doom_loop", {
            "tool": tool_name,
            "repeat_count": repeat_count,
        })

    def circuit_break(self, reason: str):
        """Record a circuit breaker event."""
        self._add("circuit_break", {"reason": reason})

    def save(self):
        """Persist the trace to ~/.ye/traces/. Synchronous version."""
        _ensure_dir()
        if not self.entries:
            return

        date_str = datetime.now().strftime("%Y%m%d")
        trace_file = _TRACE_DIR / f"{date_str}.jsonl"

        with open(trace_file, "a", encoding="utf-8", errors="surrogatepass") as f:
            for entry in self.entries:
                line = json.dumps({
                    "timestamp": entry.timestamp,
                    "event": entry.event,
                    "session_id": self.session_id,
                    **entry.data,
                }, ensure_ascii=False)
                f.write(line + "\n")

        self.entries.clear()

    async def async_save(self):
        """Async version of save() — offloads file I/O to a thread."""
        import asyncio
        await asyncio.to_thread(self.save)

    def get_summary(self) -> dict[str, Any]:
        """Get a quick summary of the trace (before saving)."""
        tool_calls = [e for e in self.entries if e.event == "tool_call"]
        errors = [e for e in self.entries if e.event == "error"]
        budget_events = [e for e in self.entries if e.event == "budget"]
        return {
            "steps": self._step_count,
            "tool_calls": len(tool_calls),
            "errors": len(errors),
            "budget_events": len(budget_events),
            "entries": len(self.entries),
        }


def _truncate(obj: Any, max_len: int = 200) -> Any:
    """Truncate strings in nested structures for logging."""
    if isinstance(obj, str):
        return obj[:max_len] + ("..." if len(obj) > max_len else "")
    if isinstance(obj, dict):
        return {k: _truncate(v, max_len) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate(v, max_len) for v in obj[:10]]
    return obj


def read_traces(date_str: str | None = None, limit: int = 50) -> list[dict]:
    """Read trace entries from disk for debugging/replay."""
    _ensure_dir()
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    trace_file = _TRACE_DIR / f"{date_str}.jsonl"
    if not trace_file.is_file():
        return []

    entries = []
    with open(trace_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(entries) >= limit:
                break

    return entries
