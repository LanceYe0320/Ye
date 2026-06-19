from __future__ import annotations

"""Permission system for Ye CLI tools.

Controls which tools can run automatically vs need user approval.
Config in ~/.ye/permissions.json.

Levels:
  - "auto": Always allowed without asking
  - "ask": Prompt user each time (they can approve for session)
  - "deny": Blocked entirely
"""

import json
from pathlib import Path

_PERM_FILE = Path.home() / ".ye" / "permissions.json"

# Default permission levels for built-in tools
_DEFAULTS = {
    "read_file": "auto",
    "list_files": "auto",
    "grep": "auto",
    "glob": "auto",
    "search_codebase": "auto",
    "web_search": "auto",
    "web_fetch": "auto",
    "write_file": "ask",
    "edit_file": "ask",
    "run_command": "ask",
    "spawn_agent": "ask",
}

# Session-level cache: tools approved for this session
_session_approved: set[str] = set()
_perm_cache: dict | None = None


def _load_config() -> dict:
    global _perm_cache
    if _perm_cache is not None:
        return _perm_cache
    if not _PERM_FILE.is_file():
        _perm_cache = {}
        return _perm_cache
    try:
        _perm_cache = json.loads(_PERM_FILE.read_text(encoding="utf-8"))
        return _perm_cache
    except Exception:
        _perm_cache = {}
        return _perm_cache


def invalidate_cache():
    global _perm_cache
    _perm_cache = None


def _save_config(config: dict):
    _PERM_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PERM_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_permission(tool_name: str) -> str:
    """Get the permission level for a tool. Returns 'auto', 'ask', or 'deny'."""
    config = _load_config()
    return config.get(tool_name, _DEFAULTS.get(tool_name, "ask"))


def set_permission(tool_name: str, level: str):
    """Set the permission level for a tool."""
    if level not in ("auto", "ask", "deny"):
        raise ValueError(f"Invalid permission level: {level}. Use auto/ask/deny.")
    config = _load_config()
    config[tool_name] = level
    _save_config(config)
    invalidate_cache()


def check_tool(tool_name: str) -> str:
    """Check if a tool can run. Returns 'allow', 'deny', or 'ask'.

    Session approvals are cached so users don't get asked repeatedly.
    """
    if tool_name in _session_approved:
        return "allow"
    level = get_permission(tool_name)
    if level == "auto":
        return "allow"
    if level == "deny":
        return "deny"
    return "ask"


def approve_for_session(tool_name: str):
    """Mark a tool as approved for the rest of this session."""
    _session_approved.add(tool_name)


def list_permissions() -> str:
    """Show all tool permissions."""
    config = _load_config()
    lines = ["Tool Permissions:"]
    all_tools = set(_DEFAULTS.keys()) | set(config.keys())
    for tool in sorted(all_tools):
        level = config.get(tool, _DEFAULTS.get(tool, "ask"))
        icon = {"auto": "auto", "ask": "ask", "deny": "deny"}.get(level, level)
        lines.append(f"  {icon:6s} {tool}")
    return "\n".join(lines)
