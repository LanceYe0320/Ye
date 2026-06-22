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
        # Structured summary template must be present.
        assert "summar" in msg.lower() or "goal" in msg.lower()
        # All required sections of the anchored summary template.
        for section in ("## Goal", "## Progress", "## Key Decisions",
                        "## Next Steps", "## Relevant Files", "## Constraints"):
            assert section in msg, f"missing section {section!r}"

    def test_user_message_wraps_text(self):
        msg = CompactPrompt.user_message("some conversation text")
        assert "some conversation text" in msg

    def test_user_message_incremental_injects_previous_summary(self):
        """Second+ compaction asks for an UPDATE, not a rebuild."""
        msg = CompactPrompt.user_message(
            "new turn",
            previous_summary="## Goal\n- old goal",
        )
        assert "<previous-summary>" in msg
        assert "old goal" in msg
        assert "update" in msg.lower()

    def test_user_message_first_time_no_anchor(self):
        """First compaction has no previous summary → asks to create new."""
        msg = CompactPrompt.user_message("first turn")
        assert "<previous-summary>" not in msg
        assert "create a new" in msg.lower()
