"""System tools: run_command."""
from __future__ import annotations

from app.sandbox.runner import run_command

TOOLS = []


async def run_cmd(command: str, timeout: int = 60) -> str:
    result = await run_command(command, timeout=timeout)
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    if result.exit_code != 0:
        output += f"\n[exit code: {result.exit_code}]"
    return output or "(no output)"


TOOLS.append({
    "name": "run_command",
    "description": "Execute a shell command",
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 60},
        },
        "required": ["command"],
    },
    "handler": run_cmd,
    "risk_level": "critical",
    "allowed_agents": ["general"],
    "requires_approval": True,
    "audit": True,
    "timeout": 60,
})
