"""Tests for the live TodoWrite task list."""
from __future__ import annotations

from app.todo_store import TodoList, TodoItem, TodoStatus


class TestTodoListReplace:
    def test_full_replace(self):
        tl = TodoList()
        tl.replace([
            {"content": "a", "status": "completed"},
            {"content": "b", "status": "in_progress"},
            {"content": "c", "status": "pending"},
        ])
        assert len(tl.items) == 3
        assert tl.items[0].status == TodoStatus.COMPLETED

    def test_invalid_status_falls_back_to_pending(self):
        tl = TodoList()
        tl.replace([{"content": "x", "status": "bogus"}])
        assert tl.items[0].status == TodoStatus.PENDING

    def test_invalid_priority_falls_back_to_medium(self):
        tl = TodoList()
        tl.replace([{"content": "x", "status": "pending", "priority": "urgent"}])
        assert tl.items[0].priority == "medium"

    def test_empty_content_skipped(self):
        tl = TodoList()
        tl.replace([{"content": "  ", "status": "pending"}, {"content": "ok"}])
        assert len(tl.items) == 1

    def test_progress(self):
        tl = TodoList()
        tl.replace([
            {"content": "a", "status": "completed"},
            {"content": "b", "status": "pending"},
        ])
        assert tl.progress() == (1, 2)


class TestRender:
    def test_prompt_render_orders_in_progress_first(self):
        tl = TodoList()
        tl.replace([
            {"content": "done", "status": "completed"},
            {"content": "next", "status": "pending"},
            {"content": "now", "status": "in_progress"},
        ])
        out = tl.render_for_prompt()
        assert "now" in out
        # in_progress should appear before completed
        assert out.index("now") < out.index("done")

    def test_prompt_render_uses_active_form(self):
        tl = TodoList()
        tl.replace([
            {"content": "Edit code", "status": "in_progress", "active_form": "Editing code"},
        ])
        out = tl.render_for_prompt()
        assert "Editing code" in out

    def test_empty_render(self):
        tl = TodoList()
        assert tl.render_for_prompt() == ""
        assert "no active" in tl.render_for_display()

    def test_display_checkboxes(self):
        tl = TodoList()
        tl.replace([
            {"content": "a", "status": "completed"},
            {"content": "b", "status": "in_progress"},
            {"content": "c", "status": "pending"},
        ])
        out = tl.render_for_display()
        assert "[x]" in out  # completed
        assert "[~]" in out  # in progress
        assert "[ ]" in out  # pending
