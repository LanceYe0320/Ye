"""Sub-agent system for Ye CLI — with Harness integration.

Supports:
  - Single sub-agent with specialized roles
  - Agent groups: parallel execution of multiple agents with result merging
  - Harness control: Budget, Trace, Registry, and Eval per sub-agent

Article reference: "子 Agent 失败后，整条链路都挂了？失败处理必须由 Harness 统一管理"
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from app.config import settings
from app.llm.base_provider import ChatMessage
from app.llm.tools import build_tool_executor
from app.llm.zhipu_provider import ZhipuProvider

# ---------------------------------------------------------------------------
# Agent roles — each has a tailored system prompt AND restricted tools
# ---------------------------------------------------------------------------

_AGENT_ROLES = {
    "explore": (
        "You are a research agent. You can read files, search code, list directories, "
        "and run read-only commands. Collect information and return a comprehensive answer. "
        "Do NOT modify any files."
    ),
    "general": (
        "You are an autonomous coding agent. Complete the given task using available tools. "
        "Be thorough and return a summary of what you did."
    ),
    "plan": (
        "You are a planning agent. Analyze the codebase, understand the requirements, "
        "and produce a detailed implementation plan. Read files, search code, explore the project. "
        "Do NOT modify any files. Output a clear step-by-step plan."
    ),
    "review": (
        "You are a code review agent. Read the relevant code and provide a thorough review. "
        "Focus on: bugs, security issues, code style, performance, error handling. "
        "Do NOT modify any files. Provide actionable feedback."
    ),
    "code": (
        "You are a focused coding agent. Your job is to implement a specific, well-defined change. "
        "Read the relevant files first, then make precise edits. "
        "Verify your changes by reading the file again after editing. "
        "Return a summary of exactly what you changed and why."
    ),
}

# Tools allowed per agent role — enforces "agent routing" from the article
_AGENT_TOOLS: dict[str, list[str]] = {
    "explore": ["read_file", "list_files", "grep", "glob", "search_codebase", "web_search", "web_fetch"],
    "plan": ["read_file", "list_files", "grep", "glob", "search_codebase", "web_search", "web_fetch"],
    "review": ["read_file", "list_files", "grep", "glob", "search_codebase"],
    "code": ["read_file", "write_file", "edit_file", "list_files", "grep", "glob", "run_command"],
    "general": None,  # All tools
}

# Max parallel agents to avoid overwhelming the API
_MAX_CONCURRENCY = 2
_STAGGER_DELAY = 2.0  # Seconds between launching parallel agents to avoid 429


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    role: str
    task: str
    success: bool
    output: str
    tool_calls: int = 0
    tokens_used: int = 0
    duration_seconds: float = 0


# ---------------------------------------------------------------------------
# Single agent — with Harness
# ---------------------------------------------------------------------------

async def spawn_agent(
    task: str,
    provider: ZhipuProvider,
    model: str | None = None,
    cwd: str | None = None,
    agent_type: str = "general",
    max_iterations: int = 5,
    budget=None,
    trace=None,
) -> str:
    """Run an independent agent with Harness controls."""
    import time as _time

    from app.llm.tools._common import set_task_cwd, reset_task_cwd

    start_time = _time.time()
    model = model or settings.ZHIPU_MODEL
    # Set a per-task working directory via contextvars instead of mutating the
    # process-global os.getcwd(). The old os.chdir(cwd) caused concurrent agents
    # (spawn_agent_group) to race on the global CWD, making file tools run in
    # the wrong directory. contextvars isolates each task cleanly.
    cwd_token = set_task_cwd(cwd) if cwd else set_task_cwd(None)

    system_content = _AGENT_ROLES.get(agent_type, _AGENT_ROLES["general"])
    messages = [
        ChatMessage(role="system", content=system_content),
        ChatMessage(role="user", content=task),
    ]

    executor = build_tool_executor(provider)

    # --- Harness: Attach Budget + Trace ---
    if budget is not None:
        executor.set_budget(budget)
    if trace is not None:
        executor.set_trace(trace)

    # --- Harness: Filter tools by agent role ---
    allowed_tools = _AGENT_TOOLS.get(agent_type)
    if allowed_tools is not None:
        executor._definitions = [
            d for d in executor._definitions if d.name in allowed_tools
        ]

    # --- Harness: Trace start ---
    if trace is not None:
        trace.tool_call("__agent_spawn__", {
            "agent_type": agent_type,
            "task": task[:200],
        }, risk="medium")

    result_text = ""
    tool_call_count = 0
    tokens_used = 0

    try:
        async for chunk in executor.run_agentic_loop(
            messages=messages, model=model, max_iterations=max_iterations,
            agent_role=agent_type,
        ):
            if chunk.type == "text_delta":
                result_text += chunk.text
                if len(result_text) > 50000:
                    result_text = result_text[:50000] + "\n... [output truncated]"
            elif chunk.type == "tool_call_end":
                tool_call_count += 1
            elif chunk.type == "usage":
                tokens_used += chunk.usage.get("total_tokens", 0)
            elif chunk.type == "error":
                result_text += f"\n\n[Agent error: {chunk.text}]"
                if trace is not None:
                    trace.error("agent_error", chunk.text)
                break
    except Exception as e:
        result_text = f"Agent failed: {e}"
        if trace is not None:
            trace.error("agent_exception", str(e))

    # --- Harness: Trace end ---
    if trace is not None:
        trace.tool_result("__agent_spawn__", result_text[:300],
                          duration_ms=(_time.time() - start_time) * 1000)

    reset_task_cwd(cwd_token)
    return result_text or "Agent completed with no output."


# ---------------------------------------------------------------------------
# Agent group — parallel execution with Harness
# ---------------------------------------------------------------------------

async def spawn_agent_group(
    tasks: list[dict],
    provider: ZhipuProvider,
    model: str | None = None,
    cwd: str | None = None,
    budget=None,
    trace=None,
) -> list[AgentResult]:
    """Spawn multiple agents in parallel with Harness controls.

    Each task dict: {"task": str, "type": str, "max_iterations": int}
    """
    import time as _time

    model = model or settings.ZHIPU_MODEL
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _run_one(spec: dict, index: int) -> AgentResult:
        task_desc = spec.get("task", spec.get("description", ""))
        agent_type = spec.get("type", "general")
        max_iter = spec.get("max_iterations", 5)
        start = _time.time()

        # Stagger launches to avoid API rate limits
        if index > 0:
            await asyncio.sleep(_STAGGER_DELAY * index)

        async with semaphore:
            try:
                output = await spawn_agent(
                    task=task_desc,
                    provider=provider,
                    model=model,
                    cwd=cwd,
                    agent_type=agent_type,
                    max_iterations=max_iter,
                    budget=budget,
                    trace=trace,
                )
                return AgentResult(
                    role=agent_type,
                    task=task_desc,
                    success=True,
                    output=output,
                    duration_seconds=_time.time() - start,
                )
            except Exception as e:
                return AgentResult(
                    role=agent_type,
                    task=task_desc,
                    success=False,
                    output=f"Agent failed: {e}",
                    duration_seconds=_time.time() - start,
                )

    results = await asyncio.gather(*[_run_one(t, i) for i, t in enumerate(tasks)])
    return list(results)


def format_group_results(results: list[AgentResult]) -> str:
    """Format agent group results into a readable string."""
    parts = []
    succeeded = sum(1 for r in results if r.success)
    parts.append(f"Agent group completed: {succeeded}/{len(results)} succeeded.\n")

    for i, r in enumerate(results, 1):
        status = "OK" if r.success else "FAILED"
        task_preview = r.task[:80] + ("..." if len(r.task) > 80 else "")
        parts.append(f"--- Agent {i} [{r.role}] ({status}): {task_preview} ---")
        parts.append(r.output)
        parts.append("")

    return "\n".join(parts)
