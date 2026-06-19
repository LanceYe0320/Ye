"""Interaction tools: ask_user — present choices and get user input."""
from __future__ import annotations

import asyncio

TOOLS = []


async def ask_user(
    question: str,
    options: str = "",
) -> str:
    """Ask the user a question, optionally with multiple-choice options.

    Use this when you need the user to make a decision, pick an approach,
    or provide input that affects how you proceed.

    Args:
        question: The question to ask (e.g. "Which framework should we use?").
        options: Comma-separated choices (e.g. "React,Vue,Svelte").
                 If empty, the user can type a free-form answer.
    """
    print()  # blank line for readability

    if options:
        opts = [o.strip() for o in options.split(",") if o.strip()]
        if not opts:
            opts = ["Yes", "No"]

        # Display question + numbered options
        print(f"  \033[1;36m?\033[0m \033[1m{question}\033[0m")
        for i, opt in enumerate(opts, 1):
            print(f"    \033[2m{i}.\033[0m {opt}")
        print(f"    \033[2m0.\033[0m (其他 — 自由输入)")

        try:
            raw = await asyncio.to_thread(input, "  \033[2m选择 (序号或内容):\033[0m ")
            raw = raw.strip()
            if not raw:
                return "用户未做选择（空输入）。请直接继续你的判断。"
            if raw.isdigit():
                idx = int(raw)
                if 1 <= idx <= len(opts):
                    return f"用户选择了: {opts[idx - 1]}"
                if idx == 0:
                    follow = await asyncio.to_thread(input, "  \033[2m请输入你的回答:\033[0m ")
                    return f"用户输入: {follow.strip() or '(空)'}"
            return f"用户输入: {raw}"
        except (EOFError, KeyboardInterrupt):
            return "用户取消了选择。请直接继续你的判断。"
    else:
        # Free-form question
        print(f"  \033[1;36m?\033[0m \033[1m{question}\033[0m")
        try:
            raw = await asyncio.to_thread(input, "  \033[2m回答:\033[0m ")
            return raw.strip() or "用户未输入内容。"
        except (EOFError, KeyboardInterrupt):
            return "用户取消了输入。请直接继续你的判断。"


TOOLS.append({
    "name": "ask_user",
    "description": (
        "Ask the user a question with optional multiple-choice options. "
        "Use when you need user decisions: choosing an approach, confirming a direction, "
        "picking between alternatives, or getting custom input. "
        "Examples: ask_user(question='Which framework?', options='React,Vue,Svelte'), "
        "ask_user(question='Should I proceed with the refactor?'). "
        "IMPORTANT: Do NOT use for simple yes/no confirmations that can be inferred — "
        "use only when genuine user choice is needed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Question to ask the user (e.g. 'Which approach should we use?')",
            },
            "options": {
                "type": "string",
                "description": "Comma-separated choices (e.g. 'React,Vue,Svelte'). Leave empty for free-form input.",
                "default": "",
            },
        },
        "required": ["question"],
    },
    "handler": ask_user,
    "risk_level": "low",
    "allowed_agents": ["general", "code", "plan"],
})
