"""Tool plugin system — auto-discovers tool modules and registers them.

Each tool module (file_ops, search_ops, etc.) exports a TOOLS list of dicts.
Agent tools require a provider and are built via make_agent_tools(provider).

Usage:
    from app.llm.tools import build_tool_executor
    executor = build_tool_executor(provider)
"""
from __future__ import annotations

from pathlib import Path

from app.llm.tool_executor import ToolExecutor

# Auto-discover all tool modules
_TOOL_MODULES = [
    "app.llm.tools.file_ops",
    "app.llm.tools.search_ops",
    "app.llm.tools.system_ops",
    "app.llm.tools.web_ops",
    "app.llm.tools.interaction_ops",
    "app.llm.tools.todo_ops",
]


def _load_tools() -> list[dict]:
    """Import all tool modules and collect their TOOLS lists."""
    import importlib
    all_tools: list[dict] = []
    for module_path in _TOOL_MODULES:
        mod = importlib.import_module(module_path)
        if hasattr(mod, "TOOLS"):
            all_tools.extend(mod.TOOLS)
    return all_tools


def discover_tool_files() -> list[str]:
    """Return list of available tool module paths (for diagnostics)."""
    return list(_TOOL_MODULES)


def build_tool_executor(provider) -> ToolExecutor:
    """Build a fully-wired ToolExecutor from all plugin modules."""
    executor = ToolExecutor(provider)

    # Register all static tools in both executor and registry
    from app.tool_registry import get_registry
    registry = get_registry()
    for tool_def in _load_tools():
        executor.register(**tool_def)
        registry.register(**tool_def)

    # Register agent tools (need provider binding)
    from app.llm.tools.agent_ops import make_agent_tools
    for tool_def in make_agent_tools(provider):
        executor.register(**tool_def)
        registry.register(**tool_def)

    return executor


def register_mcp_tools(executor, session) -> int:
    """Register tools discovered from an MCP ClientSession into the executor.

    Each MCP tool becomes callable as `<server>__<tool>` with its server-provided
    schema. The handler forwards the call to the MCP server. Returns the number
    of tools registered. Safe to call when session has no tools (no-op).
    """
    if not getattr(session, "is_connected", False) or not session.tools:
        return 0
    import asyncio
    from app.tool_registry import get_registry
    registry = get_registry()
    count = 0
    for ns_name, mcp_tool in session.tools.items():
        # Capture per-tool to avoid closure-late-binding.
        async def _handler(_tool=mcp_tool, **kwargs):
            return await session.call_tool(f"{_tool.server}__{_tool.name}", kwargs)

        tool_def = {
            "name": ns_name,
            "description": f"[MCP/{mcp_tool.server}] {mcp_tool.description or mcp_tool.name}",
            "parameters": mcp_tool.input_schema or {"type": "object", "properties": {}},
            "handler": _handler,
            "risk_level": "medium",
            "allowed_agents": ["general", "code"],
            "audit": True,
            "timeout": 60,
        }
        executor.register(**tool_def)
        registry.register(**tool_def)
        count += 1
    return count


def cleanup_http_client():
    """Close the shared HTTP client. Call on shutdown."""
    import asyncio
    from app.llm.tools._common import cleanup_http_client as _cleanup
    return _cleanup()
