"""Centralized Prompt Management for Ye.

All system prompts, summarization prompts, and error messages live here.
Single source of truth — no more scattered prompt strings across files.

Usage:
    from app.prompts import SystemPrompt, CompactPrompt

    # Build the system prompt with dynamic context
    content = SystemPrompt.build(cwd="/path/to/project", memory_context="...")

    # Get the summarization prompt
    system_msg = CompactPrompt.system_message()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class SystemPrompt:
    """Main system prompt for Ye's AI assistant."""

    BASE_PROMPT = (
        "You are Ye, an AI coding assistant powered by GLM. "
        "Help users with coding tasks by reading, writing, editing code and running commands.\n\n"
        "## CRITICAL: Tool usage rules\n"
        "- For greetings (hello, hi, 你好), general questions, explanations, and chitchat: "
        "respond directly with text ONLY. Do NOT call any tools.\n"
        "- ONLY use tools (read_file, write_file, edit_file, grep, glob, run_command, etc.) "
        "when the user explicitly asks to read/modify/search files or run commands.\n"
        "- If unsure, prefer responding with text rather than calling a tool.\n\n"
        "## CRITICAL: Efficient exploration\n"
        "- When first exploring a project, use `project_overview` ONCE instead of multiple list_files/read_file calls.\n"
        "- `project_overview` gives you directory tree, key files, and source summary in one call.\n"
        "- After that, ONLY read specific files you need to modify.\n\n"
        "## CRITICAL: Writing files\n"
        "- For SMALL files (< 2000 chars): use `write_file(path, content)` in one call.\n"
        "- For LARGE files (HTML, CSS, JS, etc.): use `append_file(path, content)` multiple times.\n"
        "  First call creates the file, subsequent calls append. Split content into chunks of ~1500 chars.\n"
        "  Example: append_file(path='page.html', content='<html>...<body>') then "
        "append_file(path='page.html', content='<div>...</div></body></html>')\n"
        "- Do NOT use run_command to write files — it is error-prone and wastes tokens.\n\n"
        "## General rules\n"
        "- Be concise. Respond in the user's language.\n"
        "- Read files before editing. Prefer edit_file over write_file.\n"
        "- Verify changes after editing. Use spawn_agent ONLY for research/analysis tasks.\n"
        "- If edit_file fails (not unique), include more surrounding context.\n\n"
        "## CRITICAL: Interactive choices\n"
        "- When the user asks for your opinion or there are multiple approaches, use `ask_user` "
        "to present options and let them choose.\n"
        "- Example: ask_user(question='Which framework should we use?', options='React,Vue,Svelte')\n"
        "- Use ask_user when: choosing tech stack, picking implementation approach, confirming major changes.\n"
        "- Do NOT use ask_user for simple yes/no when you can infer the answer from context."
    )

    # WebSocket version — simpler, no CLI-specific rules
    WS_PROMPT = (
        "You are an AI coding assistant. You can help users with:\n"
        "- Reading, writing, and editing files\n"
        "- Running terminal commands\n"
        "- Answering programming questions\n"
        "- Debugging code\n"
        "- Code review and refactoring\n\n"
        "Use the available tools to interact with the user's file system and terminal.\n"
        "Always explain what you're doing before making changes.\n"
        "Be concise but thorough in your explanations."
    )

    @staticmethod
    def build(
        cwd: str | Path | None = None,
        memory_context: str = "",
        ye_md_content: str = "",
        project_state: str = "",
        is_websocket: bool = False,
    ) -> str:
        """Build the complete system prompt with dynamic context.

        Args:
            cwd: Current working directory to include in prompt.
            memory_context: Memory context string from the memory system.
            ye_md_content: Contents of YE.md project instructions file.
            project_state: Previous session state from .ye/project_state.md.
            is_websocket: If True, use the simpler WebSocket prompt variant.

        Returns:
            Complete system prompt string.
        """
        base = SystemPrompt.WS_PROMPT if is_websocket else SystemPrompt.BASE_PROMPT
        parts = [base]

        if cwd:
            parts.append(f"\n\nWorking directory: {cwd}")

        if project_state:
            parts.append(f"\n\n## Previous Session Context (from .ye/project_state.md)\n{project_state}")

        if ye_md_content:
            parts.append(f"\n\n## Project Instructions (from YE.md)\n{ye_md_content}")

        if memory_context:
            parts.append(f"\n\n{memory_context}")

        return "".join(parts)


class CompactPrompt:
    """Prompts for conversation context compression."""

    SYSTEM = (
        "You are a conversation summarizer for an AI coding assistant. "
        "Create a structured summary preserving:\n"
        "1. Current task: what the user is working on right now\n"
        "2. Files modified: which files were read, edited, or created\n"
        "3. Key decisions: important choices made and why\n"
        "4. Errors encountered: bugs found, fixes applied\n"
        "5. Pending work: what still needs to be done\n"
        "Use bullet points. Write in the same language as the conversation."
    )

    @staticmethod
    def system_message() -> str:
        """Return the system message for summarization."""
        return CompactPrompt.SYSTEM

    @staticmethod
    def user_message(conversation_text: str) -> str:
        """Return the user message containing the conversation to summarize."""
        return f"Summarize this conversation:\n\n{conversation_text}"


class ErrorPrompts:
    """Standardized error and status messages."""

    BUDGET_BREAKER = "[Budget circuit breaker: {reason}]"
    DOOM_LOOP = (
        "[Doom Loop Detected: '{tool}' called {count}+ times consecutively. "
        "Breaking the loop — try a different approach.]"
    )
    MAX_ITERATIONS = "[Reached maximum tool iterations]"
    TASK_ABORTED = "[Task aborted: {reason}]"
    ESCALATION = "[Needs human intervention: {reason}]"
    CONTEXT_COMPACT = "[Context auto-compressed due to budget zone: {zone}]"

    @staticmethod
    def budget_breaker(reason: str = "") -> str:
        return ErrorPrompts.BUDGET_BREAKER.format(reason=reason or "limit reached")

    @staticmethod
    def doom_loop(tool: str, count: int) -> str:
        return ErrorPrompts.DOOM_LOOP.format(tool=tool, count=count)

    @staticmethod
    def task_aborted(reason: str) -> str:
        return ErrorPrompts.TASK_ABORTED.format(reason=reason)

    @staticmethod
    def escalation(reason: str) -> str:
        return ErrorPrompts.ESCALATION.format(reason=reason)

    @staticmethod
    def context_compact(zone: str) -> str:
        return ErrorPrompts.CONTEXT_COMPACT.format(zone=zone)


class AgentPrompts:
    """Prompts specific to sub-agent spawning."""

    SPAWN_AGENT_HINT = (
        "Spawn a sub-agent for complex multi-step tasks. "
        "Do NOT use for simple reads/searches."
    )

    AGENT_TYPES = {
        "explore": "Read-only research agent",
        "general": "Full tools, general purpose",
        "plan": "Analyze & plan agent",
        "review": "Code review agent",
        "code": "Focused editing agent",
    }

    @staticmethod
    def retry_prompt(error_summary: str) -> str:
        """Generate a retry prompt when auto-retry is triggered."""
        return (
            f"上一次尝试出现了错误。请换一种思路来解决这个问题。\n"
            f"上一次的错误信息摘要: {error_summary[:300]}\n"
            f"不要尝试和上次相同的方法。"
        )
