from __future__ import annotations
import logging


logger = logging.getLogger(__name__)
"""Hooks system for Ye CLI.


Hooks are shell commands that run before/after certain events.
Configured in ~/.ye/hooks.json.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

_HOOKS_FILE = Path.home() / ".ye" / "hooks.json"

VALID_EVENTS = {"pre_tool", "post_tool", "pre_response", "post_response", "post_loop"}


def _load_hooks() -> dict[str, list[dict]]:
    if not _HOOKS_FILE.is_file():
        return {}
    try:
        data = json.loads(_HOOKS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_hooks(event: str) -> list[dict]:
    """Get all enabled hooks for an event."""
    if event not in VALID_EVENTS:
        return []
    hooks = _load_hooks()
    return [h for h in hooks.get(event, []) if h.get("enabled", True)]


def run_hook(event: str, context: dict[str, Any] | None = None) -> str:
    """Run all hooks for an event. Returns combined output or error."""
    hooks = get_hooks(event)
    if not hooks:
        return ""
    results = []
    for hook in hooks:
        cmd = hook.get("command", "")
        if not cmd:
            continue
        try:
            env = None
            if context:
                env = dict(os.environ)
                for k, v in context.items():
                    env[f"YE_{k.upper()}"] = str(v)
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=30, env=env,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                output += f"\n[hook error: exit {result.returncode}]"
            if output:
                results.append(output)
        except subprocess.TimeoutExpired:
            results.append(f"[hook timeout: {cmd}]")
        except Exception as e:
            results.append(f"[hook error: {e}]")
    return "\n".join(results)


def list_hooks() -> str:
    """List all configured hooks."""
    hooks = _load_hooks()
    if not hooks:
        return "No hooks configured. Create ~/.ye/hooks.json to add hooks."
    lines = ["Configured hooks:"]
    for event, hook_list in hooks.items():
        for h in hook_list:
            status = "enabled" if h.get("enabled", True) else "disabled"
            lines.append(f"  [{status}] {event}: {h.get('command', '')}")
    return "\n".join(lines)
