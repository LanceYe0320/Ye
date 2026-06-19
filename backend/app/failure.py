"""Failure handling strategies for Ye's agent loop.

Article reference: "Harness 第一层 — 失败处理必须由 Harness 统一管理"
  - 参数错误：打回重填
  - 工具超时：换备用工具
  - 预算不足：降级模型
  - 高风险动作失败：终止并记录审计
  - 多次失败：转人工

Every failure is classified, logged, and handled by a specific strategy.
Agents don't decide retry/abort — the Harness does.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class FailureType(str, Enum):
    INVALID_ARGS = "invalid_args"        # Bad parameters
    TOOL_TIMEOUT = "tool_timeout"        # Tool took too long
    PERMISSION_DENIED = "permission"     # Not authorized
    RATE_LIMITED = "rate_limited"        # Too many calls
    RUNTIME_ERROR = "runtime_error"      # General error
    BUDGET_EXHAUSTED = "budget_exhausted"  # Token budget gone
    DOOM_LOOP = "doom_loop"              # Repeated calls
    PROVIDER_ERROR = "provider_error"    # LLM API error
    AGENT_FAILED = "agent_failed"        # Sub-agent crashed


class FailureAction(str, Enum):
    RETRY = "retry"                # Try again (maybe with fix)
    RETRY_FIX_ARGS = "retry_fix"   # Retry with corrected params
    FALLBACK = "fallback"          # Use alternative tool/approach
    DEGRADE = "degrade"            # Switch to cheaper model
    SKIP = "skip"                  # Skip this step
    ABORT = "abort"                # Stop entire task
    ESCALATE = "escalate"          # Ask for human help


@dataclass
class FailureRecord:
    failure_type: FailureType
    tool_name: str
    error_message: str
    action_taken: FailureAction
    retry_count: int
    timestamp: float
    resolved: bool = False


# --- Strategy table ---

_RETRY_MAX = {
    FailureType.INVALID_ARGS: 3,
    FailureType.TOOL_TIMEOUT: 2,
    FailureType.RATE_LIMITED: 3,
    FailureType.RUNTIME_ERROR: 2,
    FailureType.PROVIDER_ERROR: 2,
}

_ACTION_FOR_TYPE = {
    FailureType.INVALID_ARGS: FailureAction.RETRY_FIX_ARGS,
    FailureType.TOOL_TIMEOUT: FailureAction.RETRY,
    FailureType.PERMISSION_DENIED: FailureAction.ABORT,
    FailureType.RATE_LIMITED: FailureAction.RETRY,
    FailureType.RUNTIME_ERROR: FailureAction.RETRY,
    FailureType.BUDGET_EXHAUSTED: FailureAction.ABORT,
    FailureType.DOOM_LOOP: FailureAction.ABORT,
    FailureType.PROVIDER_ERROR: FailureAction.RETRY,
    FailureType.AGENT_FAILED: FailureAction.RETRY,
}

# What to do when retries are exhausted
_ESCALATION = {
    FailureType.INVALID_ARGS: FailureAction.SKIP,
    FailureType.TOOL_TIMEOUT: FailureAction.FALLBACK,
    FailureType.RATE_LIMITED: FailureAction.SKIP,
    FailureType.RUNTIME_ERROR: FailureAction.ABORT,
    FailureType.PROVIDER_ERROR: FailureAction.ESCALATE,
    FailureType.AGENT_FAILED: FailureAction.ABORT,
}


class FailureHandler:
    """Centralized failure handler — the Harness decides, not the Agent.

    Usage:
        handler = FailureHandler()

        # When a tool fails:
        action = handler.handle("run_command", "timeout after 60s", FailureType.TOOL_TIMEOUT)
        if action == FailureAction.RETRY:
            # Retry the call
            ...
        elif action == FailureAction.ABORT:
            # Stop and report
            ...
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._history: list[FailureRecord] = []
        self._retry_counts: dict[str, int] = {}

    def get_retry_count(self, tool_name: str) -> int:
        """Get how many times a tool has been retried."""
        return self._retry_counts.get(tool_name, 0)

    def classify(self, tool_name: str, error_message: str) -> FailureType:
        """Classify a failure based on the error message."""
        msg = error_message.lower()

        if "timeout" in msg or "timed out" in msg:
            return FailureType.TOOL_TIMEOUT
        if "permission" in msg or "denied" in msg or "blocked" in msg:
            return FailureType.PERMISSION_DENIED
        if "rate limit" in msg or "429" in msg or "too many" in msg:
            return FailureType.RATE_LIMITED
        if "invalid" in msg or "not found" in msg or "no such" in msg:
            return FailureType.INVALID_ARGS
        if "budget" in msg or "circuit breaker" in msg or "exhausted" in msg:
            return FailureType.BUDGET_EXHAUSTED
        if "doom loop" in msg or "repeated" in msg:
            return FailureType.DOOM_LOOP
        if "401" in msg or "403" in msg or "api" in msg:
            return FailureType.PROVIDER_ERROR

        return FailureType.RUNTIME_ERROR

    def handle(self, tool_name: str, error_message: str, failure_type: FailureType | None = None) -> FailureAction:
        """Determine the action for a failure.

        The Harness decides based on:
          1. Failure type
          2. Retry count so far
          3. Whether retries are exhausted

        Returns the action to take.
        """
        if failure_type is None:
            failure_type = self.classify(tool_name, error_message)

        # Track retries per tool
        key = f"{tool_name}:{failure_type.value}"
        retries = self._retry_counts.get(key, 0)
        max_for_type = _RETRY_MAX.get(failure_type, self.max_retries)

        # Non-retryable failures: immediate action
        if failure_type in (FailureType.PERMISSION_DENIED, FailureType.BUDGET_EXHAUSTED, FailureType.DOOM_LOOP):
            action = _ACTION_FOR_TYPE[failure_type]
            self._record(failure_type, tool_name, error_message, action, retries)
            return action

        # Retryable: check if we've exhausted retries
        if retries < max_for_type:
            action = _ACTION_FOR_TYPE.get(failure_type, FailureAction.RETRY)
            self._retry_counts[key] = retries + 1
            self._record(failure_type, tool_name, error_message, action, retries + 1)
            return action
        else:
            # Escalate
            action = _ESCALATION.get(failure_type, FailureAction.ABORT)
            self._record(failure_type, tool_name, error_message, action, retries, resolved=True)
            return action

    def _record(
        self,
        failure_type: FailureType,
        tool_name: str,
        error_message: str,
        action: FailureAction,
        retry_count: int,
        resolved: bool = False,
    ):
        self._history.append(FailureRecord(
            failure_type=failure_type,
            tool_name=tool_name,
            error_message=error_message,
            action_taken=action,
            retry_count=retry_count,
            timestamp=time.time(),
            resolved=resolved,
        ))

    def get_history(self, limit: int = 10) -> list[FailureRecord]:
        return self._history[-limit:]

    def get_summary(self) -> str:
        if not self._history:
            return "No failures recorded."

        by_type: dict[str, int] = {}
        by_action: dict[str, int] = {}
        for r in self._history:
            by_type[r.failure_type.value] = by_type.get(r.failure_type.value, 0) + 1
            by_action[r.action_taken.value] = by_action.get(r.action_taken.value, 0) + 1

        lines = [f"  Total failures: {len(self._history)}"]
        lines.append(f"  By type: {dict(by_type)}")
        lines.append(f"  By action: {dict(by_action)}")
        lines.append(f"  Active retries: {sum(1 for r in self._history if not r.resolved)}")
        return "\n".join(lines)

    def reset(self):
        """Reset retry counts (e.g., at the start of a new conversation turn)."""
        self._retry_counts.clear()
