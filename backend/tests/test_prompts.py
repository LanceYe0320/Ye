"""Tests for system prompt construction."""
from __future__ import annotations

from pathlib import Path

from app.prompts import SystemPrompt, CompactPrompt


class TestSystemPromptBuild:
    def test_base_prompt_present(self):
        out = SystemPrompt.build()
        assert "Ye" in out or "coding" in out.lower()

    def test_cwd_included(self):
        out = SystemPrompt.build(cwd="/some/path")
        assert "/some/path" in out

    def test_ye_md_appended(self):
        out = SystemPrompt.build(ye_md_content="# My Project\nUse Python")
        assert "My Project" in out
        assert "YE.md" in out

    def test_memory_context_appended(self):
        out = SystemPrompt.build(memory_context="## Core Memory\nuser likes python")
        assert "Core Memory" in out

    def test_project_state_appended(self):
        out = SystemPrompt.build(project_state="Last task: fix bug")
        assert "Previous Session Context" in out
        assert "fix bug" in out

    def test_websocket_variant(self):
        out = SystemPrompt.build(is_websocket=True)
        # WS prompt is shorter and distinct
        assert "coding" in out.lower()

    def test_no_context_no_crash(self):
        out = SystemPrompt.build()
        assert isinstance(out, str)
        assert len(out) > 0


class TestCompactPrompt:
    def test_system_message(self):
        msg = CompactPrompt.system_message()
        assert "summar" in msg.lower()
        assert "task" in msg.lower() or "file" in msg.lower()

    def test_user_message_wraps_text(self):
        msg = CompactPrompt.user_message("some conversation text")
        assert "some conversation text" in msg
