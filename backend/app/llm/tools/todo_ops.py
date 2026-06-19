"""Todo tool: todo_write — update the live task list (Claude Code TodoWrite)."""
from __future__ import annotations

from app.todo_store import TodoList

TOOLS = []

# The active todo list is bound by the CLI/Web layer via set_active_todos()
# before the agentic loop runs, so the tool can mutate it without a global.
_active: TodoList | None = None


def set_active_todos(todos: TodoList | None) -> None:
    """Bind the session's todo list so the tool can mutate it. Call before
    each agentic loop run; pass None to unbind after."""
    global _active
    _active = todos


def get_active_todos() -> TodoList | None:
    return _active


async def todo_write(todos: list[dict]) -> str:
    """Update the live task list. REPLACES the entire list each call.

    Each item: {"content": str, "status": "pending|in_progress|completed",
                "priority": "low|medium|high", "active_form"?: str}
    """
    if _active is None:
        return "TodoWrite is not available in this context."
    if not isinstance(todos, list):
        return "Error: 'todos' must be a list of items."
    _active.replace(todos)
    done, total = _active.progress()
    # Echo the new list back to the model so it sees confirmation.
    return f"Todos updated ({done}/{total} completed):\n" + _active.render_for_display()


TOOLS.append({
    "name": "todo_write",
    "description": (
        "Update the live task list for the current work. ALWAYS replace the FULL "
        "list (not a diff). Use this to plan multi-step tasks: create todos BEFORE "
        "starting, mark in_progress when you begin an item, completed when done. "
        "A short, current list keeps complex work on track."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "The complete new task list. Each item: content (str), "
                               "status (pending|in_progress|completed), priority (low|medium|high), "
                               "active_form (str, present-tense label shown while in_progress).",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "What needs doing"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                        "active_form": {"type": "string", "description": "Present-tense label while working on it"},
                    },
                    "required": ["content", "status"],
                },
            },
        },
        "required": ["todos"],
    },
    "handler": todo_write,
    "risk_level": "low",
    "allowed_agents": ["general", "code", "plan"],
    "audit": True,
    "timeout": 5,
})
