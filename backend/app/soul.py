"""SOUL.md persona system for Ye CLI.

Inspired by Hermes Agent's SOUL.md — a markdown file that shapes the agent's
personality, communication style, and behavioral preferences.

Lookup order:
  1. Project-level: ./.ye/soul.md  (project-specific persona)
  2. User-level:    ~/.ye/soul.md  (global default)
"""
from __future__ import annotations

from pathlib import Path

_PROJECT_SOUL = Path(".ye/soul.md")
_USER_SOUL = Path.home() / ".ye" / "soul.md"
_DEFAULT_SOUL = """\
# Ye Persona

You are Ye, an AI coding assistant. You are direct, concise, and helpful.
You write clean code without unnecessary comments.
You communicate in the same language the user uses.
"""


def load_soul() -> str:
    """Load persona text from SOUL.md. Project-level takes priority."""
    if _PROJECT_SOUL.is_file():
        return _PROJECT_SOUL.read_text(encoding="utf-8")
    if _USER_SOUL.is_file():
        return _USER_SOUL.read_text(encoding="utf-8")
    return _DEFAULT_SOUL


def save_soul(text: str, project_level: bool = False) -> str:
    """Save persona to SOUL.md file."""
    target = _PROJECT_SOUL if project_level else _USER_SOUL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    loc = "project" if project_level else "global"
    return f"SOUL.md saved ({loc}, {len(text)} chars)"


def soul_context() -> str:
    """Return persona text formatted for system prompt injection."""
    text = load_soul().strip()
    if not text:
        return ""
    return f"## Persona\n\n{text}"
