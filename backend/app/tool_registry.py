"""Tool Registry — production-grade tool governance for Ye.

Article reference: "Harness 第二层 — 工具治理，Tool Registry 是安全边界"

Every tool must be registered with metadata:
  - risk_level: low / medium / high / critical
  - allowed_agents: which agent roles can use this tool
  - timeout: max execution time in seconds
  - requires_approval: whether human confirmation is needed
  - audit: whether to log the call for audit trail

Agent 负责局部智能，Harness 负责全局控制。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable

ToolHandler = Callable[..., Awaitable[str]]


class RiskLevel(str, Enum):
    LOW = "low"            # Read-only, no side effects
    MEDIUM = "medium"      # Read with search, web access
    HIGH = "high"          # File writes, edits
    CRITICAL = "critical"  # Command execution, deletion, external calls


@dataclass
class ToolSpec:
    """Full specification for a registered tool."""
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    risk_level: RiskLevel = RiskLevel.MEDIUM
    allowed_agents: list[str] = field(default_factory=lambda: ["*"])
    timeout: int = 30
    requires_approval: bool = False
    audit: bool = True
    rate_limit: int = 0  # 0 = unlimited, N = max calls per minute

    # Runtime state (not serialized)
    _call_times: list[float] = field(default_factory=list, repr=False)

    def check_rate_limit(self) -> bool:
        """Return True if the call is allowed under rate limit."""
        if self.rate_limit <= 0:
            return True
        now = time.time()
        # Prune calls older than 60 seconds
        self._call_times = [t for t in self._call_times if now - t < 60]
        if len(self._call_times) >= self.rate_limit:
            return False
        self._call_times.append(now)
        return True


class ToolRegistry:
    """Central registry for all tools.

    Based on the article's principle: "给 Agent 一个工具，不是给它一个函数，而是给它一把权限钥匙"
    """

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
        risk_level: str = "medium",
        allowed_agents: list[str] | None = None,
        timeout: int = 30,
        requires_approval: bool = False,
        audit: bool = True,
        rate_limit: int = 0,
    ):
        """Register a tool with full governance metadata."""
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            risk_level=RiskLevel(risk_level),
            allowed_agents=allowed_agents or ["*"],
            timeout=timeout,
            requires_approval=requires_approval,
            audit=audit,
            rate_limit=rate_limit,
        )
        self._tools[name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def get_handler(self, name: str) -> ToolHandler | None:
        spec = self._tools.get(name)
        return spec.handler if spec else None

    def check_permission(self, tool_name: str, agent_role: str = "general") -> dict:
        """Check if an agent is allowed to call a tool.

        Returns: {"allowed": bool, "reason": str}
        """
        spec = self._tools.get(tool_name)
        if spec is None:
            return {"allowed": False, "reason": f"Tool '{tool_name}' not registered"}

        # Check agent allowlist
        if "*" not in spec.allowed_agents and agent_role not in spec.allowed_agents:
            return {
                "allowed": False,
                "reason": f"Agent '{agent_role}' not authorized for '{tool_name}'",
            }

        # Check rate limit
        if not spec.check_rate_limit():
            return {
                "allowed": False,
                "reason": f"Rate limit exceeded for '{tool_name}' ({spec.rate_limit}/min)",
            }

        return {"allowed": True, "reason": "ok"}

    def definitions(self) -> list[dict]:
        """Get tool definitions for LLM function calling."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in self._tools.values()
        ]

    def definitions_for_agent(self, agent_role: str) -> list[dict]:
        """Get tool definitions filtered by agent role."""
        result = []
        for spec in self._tools.values():
            if "*" in spec.allowed_agents or agent_role in spec.allowed_agents:
                result.append({
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                })
        return result

    def summary(self) -> str:
        """Print a summary of all registered tools."""
        lines = ["Tool Registry Summary:", f"  {'Tool':20s} {'Risk':10s} {'Agents':20s} {'Audit':6s}"]
        lines.append("  " + "-" * 70)
        for spec in self._tools.values():
            agents = ", ".join(spec.allowed_agents)
            lines.append(
                f"  {spec.name:20s} {spec.risk_level.value:10s} {agents:20s} "
                f"{'yes' if spec.audit else 'no':6s}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Audit Logger — structured execution trace
# ---------------------------------------------------------------------------

_TRACE_DIR = Path.home() / ".ye" / "traces"


def _ensure_trace_dir():
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)


def log_tool_call(
    tool_name: str,
    arguments: dict,
    result: str,
    agent_role: str = "general",
    session_id: str | None = None,
    duration_ms: float = 0,
    risk_level: str = "medium",
    blocked: bool = False,
    blocked_reason: str = "",
):
    """Write a structured audit log entry for a tool call."""
    _ensure_trace_dir()
    now = datetime.now()
    trace_file = _TRACE_DIR / f"{now.strftime('%Y%m%d')}.jsonl"

    entry = {
        "timestamp": now.isoformat(),
        "tool": tool_name,
        "arguments": _truncate_for_log(arguments),
        "result_preview": result[:500] if result else "",
        "agent": agent_role,
        "session": session_id or "",
        "duration_ms": round(duration_ms, 1),
        "risk_level": risk_level,
        "blocked": blocked,
        "blocked_reason": blocked_reason,
    }
    trace_file.open("a", encoding="utf-8").write(
        json.dumps(entry, ensure_ascii=False) + "\n"
    )


def _truncate_for_log(obj: Any, max_len: int = 200) -> Any:
    if isinstance(obj, str):
        return obj[:max_len] + ("..." if len(obj) > max_len else "")
    if isinstance(obj, dict):
        return {k: _truncate_for_log(v, max_len) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get the global tool registry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    risk_level: str = "medium",
    allowed_agents: list[str] | None = None,
    timeout: int = 30,
    requires_approval: bool = False,
    audit: bool = True,
    rate_limit: int = 0,
):
    """Decorator to auto-register a function as a tool at import time.

    Usage:
        @tool("read_file", "Read file contents", {"type": "object", ...})
        async def read_file(path: str) -> str:
            ...
    """
    def decorator(func: ToolHandler) -> ToolHandler:
        get_registry().register(
            name=name,
            description=description,
            parameters=parameters,
            handler=func,
            risk_level=risk_level,
            allowed_agents=allowed_agents,
            timeout=timeout,
            requires_approval=requires_approval,
            audit=audit,
            rate_limit=rate_limit,
        )
        return func
    return decorator
