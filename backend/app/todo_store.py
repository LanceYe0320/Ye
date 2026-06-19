"""Live todo-list store — Claude Code-style TodoWrite.

A per-session dynamic task list that drives agent behavior: the model calls
the `todo_write` tool to update it, the list is injected into the system prompt
each turn (so the agent keeps direction on long tasks), and the UI renders it.

Distinct from app/tasks.py (the heavyweight Harness TaskManager with state
machines, deps, timing). This is the lightweight "what am I doing right now"
list that Claude Code uses to maintain task coherence.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class TodoItem:
    content: str
    status: TodoStatus = TodoStatus.PENDING
    priority: str = "medium"  # low | medium | high
    active_form: str = ""  # present-tense description while in progress

    def checkbox(self) -> str:
        if self.status == TodoStatus.COMPLETED:
            return "[x]"
        if self.status == TodoStatus.IN_PROGRESS:
            return "[~]"
        return "[ ]"


# Priority sort weight for display / injection
_PRIORITY_WEIGHT = {"high": 0, "medium": 1, "low": 2}


@dataclass
class TodoList:
    """A session-scoped, ordered todo list."""
    items: list[TodoItem] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))

    def replace(self, items: list[dict]) -> None:
        """Replace the whole list from a list of dicts (the tool payload).

        Each dict: {content, status?, priority?, active_form?}. Replacing the
        whole list (rather than incremental edits) matches Claude Code's model:
        the agent rewrites the entire current plan each time.
        """
        new_items: list[TodoItem] = []
        for d in items:
            content = (d.get("content") or "").strip()
            if not content:
                continue
            status_raw = (d.get("status") or "pending").strip().lower()
            try:
                status = TodoStatus(status_raw)
            except ValueError:
                status = TodoStatus.PENDING
            priority = (d.get("priority") or "medium").strip().lower()
            if priority not in ("low", "medium", "high"):
                priority = "medium"
            new_items.append(TodoItem(
                content=content,
                status=status,
                priority=priority,
                active_form=(d.get("active_form") or "").strip(),
            ))
        self.items = new_items
        self.updated_at = datetime.now().strftime("%H:%M:%S")

    def clear(self) -> None:
        self.items = []
        self.updated_at = datetime.now().strftime("%H:%M:%S")

    @property
    def is_empty(self) -> bool:
        return not self.items

    def progress(self) -> tuple[int, int]:
        """Return (completed_count, total_count)."""
        total = len(self.items)
        done = sum(1 for i in self.items if i.status == TodoStatus.COMPLETED)
        return done, total

    def render_for_prompt(self) -> str:
        """Compact text form for system-prompt injection.

        Orders: in_progress first, then pending by priority, completed last —
        so the agent's current focus is at the top.
        """
        if self.is_empty:
            return ""
        # Sort: in_progress → pending(high→low) → completed
        def key(i: TodoItem):
            if i.status == TodoStatus.IN_PROGRESS:
                return (0, _PRIORITY_WEIGHT.get(i.priority, 1))
            if i.status == TodoStatus.PENDING:
                return (1, _PRIORITY_WEIGHT.get(i.priority, 1))
            return (2, 0)

        ordered = sorted(self.items, key=key)
        lines = ["## Current Task List (TodoWrite)"]
        done, total = self.progress()
        lines.append(f"Progress: {done}/{total} completed")
        for i in ordered:
            mark = {"completed": "x", "in_progress": "~", "pending": " "}[i.status.value]
            label = i.active_form if (i.active_form and i.status == TodoStatus.IN_PROGRESS) else i.content
            lines.append(f"- [{mark}] {label}")
        lines.append(
            "Keep this list current: mark items in_progress when you start them, "
            "completed when done, and add new items as the plan evolves."
        )
        return "\n".join(lines)

    def render_for_display(self) -> str:
        """Rich-renderable-friendly text form for the /todos command panel."""
        if self.is_empty:
            return "(no active todos — use the todo_write tool to plan a task)"
        done, total = self.progress()
        out = [f"Todos ({done}/{total} done, updated {self.updated_at})"]
        for i in self.items:
            out.append(f"  {i.checkbox()} {i.content}")
        return "\n".join(out)
