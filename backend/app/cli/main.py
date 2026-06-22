from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Fast stdout for streaming text — bypass Rich markup parsing
_stdout_write = sys.stdout.write

# Suppress "Event loop is closed" RuntimeError from asyncio SSL cleanup on exit
_original_excepthook = sys.excepthook
def _quiet_excepthook(exc_type, exc_val, exc_tb):
    if exc_type is RuntimeError and "Event loop is closed" in str(exc_val):
        return
    _original_excepthook(exc_type, exc_val, exc_tb)
sys.excepthook = _quiet_excepthook
_stdout_flush = sys.stdout.flush

# Lazy heavy imports — loaded inside _run_inner(), not at module import time
# from rich.console import Console  <-- ~400ms
# from app.config import settings    <-- ~1500ms (pydantic_settings)

# Suppress default SECRET_KEY warning in CLI mode (not relevant for local use)
warnings.filterwarnings("ignore", message="Using default SECRET_KEY")

_console = None

def _get_console():
    global _console
    if _console is None:
        from rich.console import Console
        _console = Console()
    return _console

# Shorthand used throughout — resolved at call time, not import time
console = property(lambda self: _get_console())  # doesn't work as module-level

# Actually, just use a module-level proxy
class _ConsoleProxy:
    """Lazy proxy that forwards all attribute access to the real Console."""
    def __getattr__(self, name):
        return getattr(_get_console(), name)

console = _ConsoleProxy()

# Lazy imports — heavy modules loaded only when first accessed
_mem = None
_tasks_mod = None
_worktree_mod = None
_provider = None
_executor = None
_mcp_session = None  # MCP ClientSession (connected lazily when servers are configured)
_ChatMessage = None
_ToolCall = None

def _get_mem():
    global _mem
    if _mem is None:
        import app.memory as m
        _mem = m
    return _mem

def _get_tasks():
    global _tasks_mod
    if _tasks_mod is None:
        import app.tasks as t
        _tasks_mod = t
    return _tasks_mod

def _get_worktree():
    global _worktree_mod
    if _worktree_mod is None:
        import app.worktree as w
        _worktree_mod = w
    return _worktree_mod


def _get_provider():
    global _provider
    if _provider is None:
        from app.llm.zhipu_provider import ZhipuProvider
        _provider = ZhipuProvider()
    return _provider


def _get_executor(provider=None):
    global _executor
    if _executor is None:
        from app.llm.tools import build_tool_executor
        from app.tool_registry import get_registry
        _executor = build_tool_executor(provider or _get_provider())
        # Wire up Tool Registry
        registry = get_registry()
        _executor.set_tool_registry(registry)
    return _executor


def _get_budget():
    """Create a fresh TokenBudget per conversation turn."""
    from app.budget import TokenBudget, BudgetConfig
    return TokenBudget(BudgetConfig(
        max_total_tokens=300_000,
        max_tool_calls=50,
        max_duration_seconds=1800,
        enabled=True,
    ))


def _get_trace(session_id: str = ""):
    """Create a fresh ExecutionTrace per conversation turn."""
    from app.execution_trace import ExecutionTrace
    return ExecutionTrace(session_id=session_id)


def _get_chat_message():
    global _ChatMessage
    if _ChatMessage is None:
        from app.llm.base_provider import ChatMessage
        _ChatMessage = ChatMessage
    return _ChatMessage


def _get_tool_call():
    global _ToolCall
    if _ToolCall is None:
        from app.llm.base_provider import ToolCall
        _ToolCall = ToolCall
    return _ToolCall

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class UsageRecord:
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class SessionState:
    messages: list[ChatMessage] = field(default_factory=list)
    model: str = ""
    cwd: Path = field(default_factory=Path.cwd)
    usage_records: list[UsageRecord] = field(default_factory=list)
    session_start: float = field(default_factory=time.time)
    task_manager: object = field(default_factory=lambda: _get_tasks().TaskManager())
    loop_task: asyncio.Task | None = None
    worktree_name: str = ""
    _cached_system_prompt: ChatMessage | None = None
    _cached_system_cwd: str = ""
    # Per-file mtime caches for _system_prompt (avoid re-reading YE.md /
    # project_state.md every turn when content hasn't changed). Each holds
    # (mtime, content). None = not yet read / file absent.
    _cached_ye_md: tuple | None = None
    _cached_project_state: tuple | None = None
    # Live task list (Claude Code-style TodoWrite). Drives long-task direction
    # via system-prompt injection; updated by the todo_write tool.
    todo_list: object = None  # lazily set to a TodoList instance
    # Interaction mode: "normal" (ask for edits), "plan" (read-only), "auto_accept" (auto-approve all)
    mode: str = "normal"  # "normal" | "plan" | "auto_accept"
    # Anchored summary from the last compaction round (None until first compact).
    # Injected into subsequent compaction prompts so the model updates the
    # existing summary incrementally rather than rebuilding from scratch.
    last_summary: str | None = None
    # Snapshot history: list of (hash, timestamp, message_index, label).
    # Each entry is a restore point captured automatically after tool steps
    # (and manually via /snapshot). The most recent is at the end.
    snapshots: list = field(default_factory=list)


_MODES = ("normal", "plan", "auto_accept")
_MODE_LABELS = {
    "normal":      (" NORMAL ", "bg:#1e293b fg:#7dd3fc"),
    "plan":        (" PLAN ",   "bg:#422006 fg:#fbbf24"),
    "auto_accept": (" AUTO ",   "bg:#052e16 fg:#4ade80"),
}
_MODE_DESCRIPTIONS = {
    "normal": "Normal — edits require confirmation",
    "plan": "Plan — read-only, no edits allowed",
    "auto_accept": "Auto-accept — all edits auto-approved",
}


def _cycle_mode(state: SessionState) -> None:
    """Cycle through modes: normal → plan → auto_accept → normal."""
    idx = _MODES.index(state.mode)
    state.mode = _MODES[(idx + 1) % len(_MODES)]
    state._cached_system_prompt = None


# ---------------------------------------------------------------------------
# Pricing (Yuan per 1K tokens, approximate Zhipu public pricing)
# ---------------------------------------------------------------------------

_EST_COST_PER_1K = {
    "glm-5.2": {"prompt": 0.02, "completion": 0.02},
    "glm-5.1": {"prompt": 0.015, "completion": 0.015},
    "glm-5": {"prompt": 0.01, "completion": 0.01},
    "glm-5-turbo": {"prompt": 0.005, "completion": 0.005},
    "glm-4.7": {"prompt": 0.005, "completion": 0.005},
    "glm-4.7-flashx": {"prompt": 0.0001, "completion": 0.0001},
    "glm-4.6": {"prompt": 0.01, "completion": 0.01},
    "glm-4-plus": {"prompt": 0.05, "completion": 0.05},
    "glm-4-flash": {"prompt": 0.0001, "completion": 0.0001},
    "glm-4-long": {"prompt": 0.001, "completion": 0.001},
    "glm-4": {"prompt": 0.015, "completion": 0.015},
}
_DEFAULT_PRICING = {"prompt": 0.01, "completion": 0.01}


def _format_tokens(n: int) -> str:
    """Format token count for display: 145869 → '145.9K', 128000 → '128.0K'."""
    if n >= 950_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)


def _get_context_usage(state: SessionState) -> tuple[int, int]:
    """Return (used_prompt_tokens, max_context_tokens) based on latest API call."""
    if not state.usage_records:
        return 0, 128000
    last_prompt = state.usage_records[-1].prompt_tokens
    try:
        from app.llm.zhipu_provider import MODELS
        info = MODELS.get(state.model)
        max_ctx = info.max_tokens if info else 128000
    except Exception:
        max_ctx = 128000
    return last_prompt, max_ctx


class _TurnTimer:
    """Live timing for conversation turns — animated 'Thinking...' with elapsed time.

    Provides the Claude Code–style real-time feedback:
      - Animated dots + elapsed seconds during Thinking
      - Per-tool timing (tool_elapsed)
      - Output token counter for the summary line
    """

    def __init__(self):
        self.start_time = 0.0
        self.first_token_time = None
        self.tokens_output = 0
        self._task = None
        self._tool_start = 0.0

    def start_thinking(self):
        """Start the animated 'Thinking...' timer."""
        self.start_time = time.time()
        self.first_token_time = None
        self.tokens_output = 0
        self._task = asyncio.create_task(self._tick())

    def stop_thinking(self):
        """Stop the animation and clear the line."""
        if self._task:
            self._task.cancel()
            self._task = None
        try:
            _stdout_write("\r" + " " * 70 + "\r")
            _stdout_flush()
        except Exception:
            pass
        if self.first_token_time is None:
            self.first_token_time = time.time()

    def mark_tool_start(self):
        self._tool_start = time.time()

    def tool_elapsed(self) -> str:
        e = time.time() - self._tool_start
        return f"{e:.1f}s" if e < 60 else f"{int(e) // 60}m {int(e) % 60:02d}s"

    def add_tokens(self, text):
        self.tokens_output += len(text)

    @property
    def elapsed_str(self) -> str:
        e = time.time() - self.start_time
        m, s = divmod(int(e), 60)
        return f"{m}m {s:02d}s" if m else f"{s}s"

    @property
    def ttfb_str(self) -> str:
        return f"{self.first_token_time - self.start_time:.1f}s" if self.first_token_time else "N/A"

    @property
    def output_str(self) -> str:
        approx = self.tokens_output // 4
        return f"↓{_format_tokens(approx)}" if approx > 0 else ""

    async def _tick(self):
        # ASCII-safe spinner (works in any terminal encoding, incl. GBK on
        # Windows). A rotating bar gives the same "working" feel as braille
        # frames without mojibake risk.
        frames = "|/-\\"
        try:
            i = 0
            while True:
                e = time.time() - self.start_time
                m, s = divmod(int(e), 60)
                dur = f"{m}m{s:02d}s" if m else f"{s}s"
                frame = frames[i % len(frames)]
                # brand-green spinner, dim "Thinking", muted timer
                line = f"  \x1b[38;2;74;222;128m{frame}\x1b[0m  \x1b[2mThinking\x1b[0m \x1b[38;2;107;114;128m{dur}\x1b[0m"
                _stdout_write(f"\r{line}{' ' * max(0, 50 - len(line))}")
                _stdout_flush()
                i += 1
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# YE.md template
# ---------------------------------------------------------------------------

_YE_MD_TEMPLATE = """\
# Project Instructions for Ye

This file contains project-specific instructions that Ye will follow \
when working in this directory.

## Project Overview
<!-- Describe your project here -->

## Tech Stack
<!-- e.g., Python 3.12, FastAPI, React, PostgreSQL -->

## Code Style
<!-- e.g., Use type hints, follow PEP 8, prefer async/await -->

## Testing
<!-- e.g., Run tests with: pytest tests/ -v -->

## Build & Deploy
<!-- e.g., Build with: npm run build, Deploy with: docker-compose up -->

## Important Files
<!-- List key files and their purposes -->

## Conventions
<!-- e.g., API routes in app/api/, models in app/storage/models.py -->

## Notes
<!-- Any additional context Ye should know about -->
"""

# ---------------------------------------------------------------------------
# Banner / help
# ---------------------------------------------------------------------------


def _build_banner(version: str, model: str, cwd: str):
    """Plan G startup banner — minimal, borderless, 2-3 lines.

    Inspired by Claude Code / Warp / Raycast: a tiny gem glyph + gradient
    brand name on line 1, a dense status row on line 2, an optional hint
    row on line 3. No box, no big logo. Gem glyph auto-degrades to ASCII
    on legacy GBK consoles.
    """
    from rich.text import Text
    from rich.console import Group
    from app.cli.theme import PRIMARY, PRIMARY_DEEP, ACCENT, ACCENT_SOFT, MUTED, MUTED_LIGHT, gem_glyph

    display_cwd = cwd if len(cwd) <= 44 else "..." + cwd[-43:]

    # Resolve the model's context window for display
    try:
        from app.llm.zhipu_provider import MODELS
        ctx = MODELS.get(model)
        max_ctx = _format_tokens(ctx.max_tokens) if ctx else ""
    except Exception:
        max_ctx = ""

    gem = gem_glyph()

    line1 = Text()
    line1.append("  ", style="")
    line1.append(gem, style=f"bold {PRIMARY}")
    line1.append(" ", style="")
    # Gradient brand: Y (bright green) → e (deep green)
    line1.append("Y", style=f"bold {PRIMARY}")
    line1.append("e", style=f"bold {PRIMARY_DEEP}")
    line1.append("   ", style="")
    line1.append("AI Coding Agent", style=MUTED_LIGHT)

    line2 = Text()
    line2.append("  ", style="")
    line2.append(f"v{version}", style=MUTED)
    line2.append("   ", style="")
    line2.append(f"{model}", style=f"bold {ACCENT}")
    if max_ctx:
        line2.append(f"  ({max_ctx})", style=MUTED)
    line2.append("   ", style="")
    line2.append("Ready.", style=PRIMARY)
    line2.append("   ", style="")
    line2.append(display_cwd, style=f"dim {MUTED_LIGHT}")

    return Group(line1, Text(""), line2)


# Slash commands definition (shared between help and completer)
SLASH_COMMANDS = [
    ("/help",          "Show available commands"),
    ("/model",         "Show or switch model"),
    ("/clear",         "Clear conversation history"),
    ("/cd <path>",     "Change working directory"),
    ("/pwd",           "Show current working directory"),
    ("/edit <file>",   "Open file in editor"),
    ("/compact",       "Compress conversation context"),
    ("/cost",          "Show token usage and cost"),
    ("/diff",          "Show git diff of changes"),
    ("/init",          "Create YE.md project instructions"),
    ("/status",        "Show session status"),
    ("/memory",        "Show persistent memories"),
    ("/remember",      "Save text to memory"),
    ("/forget",        "Delete a memory"),
    ("/sessions",      "List recent sessions"),
    ("/resume",        "Resume a previous session"),
    ("/budget",        "Show current token budget status"),
    ("/trace",         "Show recent execution trace"),
    ("/registry",      "Show tool registry summary"),
    ("/eval",          "Show evaluation metrics summary"),
    ("/failures",      "Show recent failure handling log"),
    ("/learn",         "Add a rule to YE.md from mistakes learned"),
    ("/plan",          "Generate an execution plan before acting"),
    ("/prune",         "Prune low-value memories"),
    ("/tasks",         "List all tasks"),
    ("/todos",         "Show the live todo list (TodoWrite)"),
    ("/task",          "Create a new task"),
    ("/done <id>",     "Mark task as completed"),
    ("/taskinfo <id>", "Show detailed task info"),
    ("/review",        "AI code review of staged changes"),
    ("/skills",        "List available skills"),
    ("/mcp",           "Show MCP server connections and tools"),
    ("/loop",          "Run task on interval"),
    ("/doctor",        "Run health checks"),
    ("/soul",          "View or edit persona (SOUL.md)"),
    ("/cron",          "Manage cron jobs: list|create|toggle|delete"),
    ("/coremem",       "Manage core memory: show|add|remove|clear"),
    ("/ss",            "Search past sessions (full-text)"),
    ("/worktree",      "Manage git worktrees"),
    ("/permissions",   "View or set tool permissions (auto/ask/deny)"),
    ("/snapshot",      "Capture a file-state snapshot for /revert"),
    ("/revert",        "Revert files to the last snapshot (or /revert <hash>)"),
    ("/snapshots",     "List recent snapshot hashes with change counts"),
    ("/exit",          "Exit the assistant"),
]

HELP_TEXT = "[bold]Available Commands:[/]\n\n" + "\n".join(
    f"  [cyan]{cmd:18s}[/] {desc}" for cmd, desc in SLASH_COMMANDS
)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def _save_project_state(state: SessionState, last_response: str) -> None:
    """Auto-save project context to .ye/project_state.md after each turn.

    This survives context compression — the model can read it to recover
    what it was doing, what files it modified, and what decisions were made.
    """
    ye_dir = state.cwd / ".ye"
    try:
        ye_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    # Build state summary from messages
    from datetime import datetime
    lines = [
        f"# YE Project State",
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Model: {state.model}",
        f"Messages: {len(state.messages)}",
        f"API calls: {len(state.usage_records)}",
        "",
    ]

    # Extract user messages as task history (last 10)
    user_msgs = [(i, m) for i, m in enumerate(state.messages) if m.role == "user"]
    if user_msgs:
        lines.append("## Recent User Messages")
        for idx, msg in user_msgs[-10:]:
            text = (msg.content or "")[:200]
            lines.append(f"- {text}")
        lines.append("")

    # Extract files that were read/modified
    files_touched = set()
    for msg in state.messages:
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = tc.arguments if isinstance(tc.arguments, dict) else {}
                fp = args.get("path") or args.get("file_path") or args.get("filename")
                if fp and isinstance(fp, str):
                    files_touched.add(fp)
    if files_touched:
        lines.append("## Files Touched")
        for f in sorted(files_touched)[-20:]:
            lines.append(f"- {f}")
        lines.append("")

    # Last assistant response summary
    if last_response:
        lines.append("## Last Response")
        lines.append(last_response[:1500])
        lines.append("")

    state_file = ye_dir / "project_state.md"
    try:
        state_file.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass


def _read_cached_file(path: Path, cache_attr: str, state) -> str:
    """Read a file with mtime caching on the SessionState.

    Returns the cached content if the file's mtime hasn't changed since the
    last read, otherwise re-reads from disk and caches it. Used by
    _system_prompt to avoid re-reading YE.md / project_state.md every turn
    when their content hasn't changed.
    """
    if not path.is_file():
        # clear stale cache if the file vanished
        if hasattr(state, cache_attr):
            setattr(state, cache_attr, None)
        return ""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return ""
    cached = getattr(state, cache_attr, None)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        content = ""
    setattr(state, cache_attr, (mtime, content))
    return content


def _system_prompt(cwd: Path | None = None, state: SessionState | None = None) -> ChatMessage:
    cwd = cwd or Path.cwd()
    cwd_str = str(cwd)

    from app.prompts import SystemPrompt

    # Load YE.md if present (mtime-cached per turn)
    ye_md = cwd / "YE.md"
    ye_md_content = _read_cached_file(ye_md, "_cached_ye_md", state) if state is not None else (
        ye_md.read_text(encoding="utf-8") if ye_md.is_file() else ""
    )

    # Load memory context
    mem_ctx = _get_mem().get_context(max_chars=4000)

    # Load project state from .ye/project_state.md (mtime-cached; survives
    # context compression). This file is updated at the end of each turn by
    # _save_project_state, so its mtime changes and the cache refreshes.
    ye_state_file = cwd / ".ye" / "project_state.md"
    if state is not None:
        project_state = _read_cached_file(ye_state_file, "_cached_project_state", state)[:4000]
    else:
        project_state = (
            ye_state_file.read_text(encoding="utf-8")[:4000] if ye_state_file.is_file() else ""
        )

    content = SystemPrompt.build(
        cwd=cwd,
        memory_context=mem_ctx,
        ye_md_content=ye_md_content,
        project_state=project_state,
    )

    # Inject the live todo list (Claude Code TodoWrite) so the agent keeps
    # direction on multi-step tasks. Rendered fresh each turn from state.todo_list.
    if state is not None and state.todo_list is not None and not state.todo_list.is_empty:
        content += "\n\n" + state.todo_list.render_for_prompt()

    # Inject available Skills (user + project) so the agent can suggest/invoke them.
    from app.skills import discover_skills, render_skills_for_prompt
    skills_ctx = render_skills_for_prompt(discover_skills(cwd))
    if skills_ctx:
        content += skills_ctx

    # Add mode-specific instructions
    if state is not None and state.mode == "plan":
        content += (
            "\n\n## PLAN MODE (Read-Only)\n"
            "You are in PLAN MODE. You can ONLY read files, search, and explore. "
            "Do NOT attempt to write, edit, or modify any files. "
            "Do NOT run any commands that change the filesystem. "
            "Only analyze and propose changes — the user will switch to normal mode to execute."
        )
    prompt = _get_chat_message()(role="system", content=content)
    if state is not None:
        state._cached_system_prompt = prompt
        state._cached_system_cwd = cwd_str
    return prompt


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def _cmd_cost(state: SessionState) -> None:
    from rich.table import Table
    if not state.usage_records:
        console.print("[dim]No token usage data yet.[/]")
        return

    table = Table(title="Token Usage", show_lines=False)
    table.add_column("Model", style="cyan")
    table.add_column("Prompt Tokens", justify="right")
    table.add_column("Completion Tokens", justify="right")
    table.add_column("Total Tokens", justify="right")
    table.add_column("Est. Cost (Yuan)", justify="right", style="yellow")

    totals = {"prompt": 0, "completion": 0, "total": 0, "cost": 0.0}
    by_model: dict[str, dict] = {}

    for rec in state.usage_records:
        if rec.model not in by_model:
            by_model[rec.model] = {"prompt": 0, "completion": 0, "total": 0}
        by_model[rec.model]["prompt"] += rec.prompt_tokens
        by_model[rec.model]["completion"] += rec.completion_tokens
        by_model[rec.model]["total"] += rec.total_tokens

    for model_name, stats in by_model.items():
        pricing = _EST_COST_PER_1K.get(model_name, _DEFAULT_PRICING)
        cost = (
            stats["prompt"] / 1000 * pricing["prompt"]
            + stats["completion"] / 1000 * pricing["completion"]
        )
        table.add_row(
            model_name,
            f"{stats['prompt']:,}",
            f"{stats['completion']:,}",
            f"{stats['total']:,}",
            f"¥{cost:.4f}",
        )
        totals["prompt"] += stats["prompt"]
        totals["completion"] += stats["completion"]
        totals["total"] += stats["total"]
        totals["cost"] += cost

    table.add_row(
        "[bold]Total[/]",
        f"[bold]{totals['prompt']:,}[/]",
        f"[bold]{totals['completion']:,}[/]",
        f"[bold]{totals['total']:,}[/]",
        f"[bold]¥{totals['cost']:.4f}[/]",
    )
    console.print(table)
    console.print(f"[dim]API calls: {len(state.usage_records)}[/]")

    # Context window summary
    used_ctx, max_ctx = _get_context_usage(state)
    remaining = max(0, max_ctx - used_ctx)
    console.print(
        f"[dim]Context window: {_format_tokens(used_ctx)}/{_format_tokens(max_ctx)} "
        f"used, {_format_tokens(remaining)} remaining[/]"
    )


async def _cmd_status(state: SessionState) -> None:
    from rich.panel import Panel
    # Session duration
    elapsed = time.time() - state.session_start
    hours, remainder = divmod(int(elapsed), 3600)
    minutes, seconds = divmod(remainder, 60)
    duration = f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"

    # Git branch
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(state.cwd), timeout=5,
        )
        branch = result.stdout.strip() if result.returncode == 0 else "N/A"
    except Exception:
        branch = "N/A"

    # Token totals
    total_tokens = sum(r.total_tokens for r in state.usage_records)

    # Context window usage
    used_ctx, max_ctx = _get_context_usage(state)
    remaining = max(0, max_ctx - used_ctx)
    ctx_pct = used_ctx / max_ctx * 100 if max_ctx > 0 else 0
    if ctx_pct < 60:
        ctx_style = "green"
    elif ctx_pct < 85:
        ctx_style = "yellow"
    else:
        ctx_style = "red"

    lines = [
        f"  [cyan]Model:[/]             {state.model}",
        f"  [cyan]Working Dir:[/]      {state.cwd}",
        f"  [cyan]Git Branch:[/]       {branch}",
        f"  [cyan]Messages:[/]         {len(state.messages)}",
        f"  [cyan]Context Window:[/]   [{ctx_style}]{_format_tokens(used_ctx)}/{_format_tokens(max_ctx)}[/] ({ctx_pct:.0f}% used, {_format_tokens(remaining)} remaining)",
        f"  [cyan]Total Tokens:[/]     {total_tokens:,}",
        f"  [cyan]API Calls:[/]        {len(state.usage_records)}",
        f"  [cyan]Session Duration:[/] {duration}",
    ]
    console.print(Panel("\n".join(lines), title="Session Status", border_style="cyan"))


async def _cmd_diff(state: SessionState) -> None:
    any_output = False
    for staged in (False, True):
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=str(state.cwd), timeout=10,
            )
            output = result.stdout.strip()
        except Exception as e:
            console.print(f"[red]Error running git diff:[/] {e}")
            return

        title = "Staged Changes" if staged else "Unstaged Changes"
        if output:
            any_output = True
            display = output[:2000]
            if len(output) > 2000:
                display += "\n... (truncated, use git diff directly for full output)"
            console.print(Panel(display, title=title, border_style="yellow"))
        else:
            console.print(f"[dim]No {title.lower()}.[/]")

    if not any_output:
        console.print("[dim]Working tree clean — no changes detected.[/]")


async def _cmd_snapshot(state: SessionState, label: str = "") -> None:
    """Capture a file-state snapshot for later /revert.

    Snapshots are stored in an isolated git bare repo (~/.ye/data/snapshot/...),
    never touching the user's own git history. Each snapshot records the full
    working-tree state as a tree hash.
    """
    from app import snapshot as snap_mod
    h = snap_mod.snapshot(state.cwd)
    if h is None:
        console.print(
            "[yellow]Snapshot unavailable.[/] "
            "The working directory must be inside a git repo."
        )
        return
    entry = {
        "hash": h,
        "time": time.time(),
        "label": label or f"snapshot-{len(state.snapshots) + 1}",
    }
    state.snapshots.append(entry)
    console.print(
        f"[green]Snapshot captured:[/] {h[:12]} "
        f"([dim]{entry['label']}[/], #{len(state.snapshots)})"
    )


async def _cmd_snapshots(state: SessionState) -> None:
    """List recent snapshots with pending change counts."""
    if not state.snapshots:
        console.print("[dim]No snapshots yet. Use /snapshot to capture one.[/]")
        return
    from app import snapshot as snap_mod
    from rich.table import Table
    table = Table(title="Snapshots", show_lines=False)
    table.add_column("#", style="dim")
    table.add_column("Hash", style="cyan")
    table.add_column("Label", style="white")
    table.add_column("Pending changes", style="yellow")
    for i, entry in enumerate(state.snapshots, 1):
        changed = snap_mod.diff_files(state.cwd, entry["hash"])
        table.add_row(str(i), entry["hash"][:12], entry["label"], str(len(changed)))
    console.print(table)


async def _cmd_revert(state: SessionState, arg: str) -> None:
    """Revert the working tree (or specific files) to a snapshot.

    Usage:
      /revert              — revert all changed files to the LAST snapshot
      /revert <hash>       — revert to a specific snapshot hash
      /revert <#n>         — revert to the nth snapshot from /snapshots
      /revert <hash> f1 f2 — revert only specific files
    """
    from app import snapshot as snap_mod
    if not state.snapshots:
        console.print("[dim]No snapshots to revert to. Use /snapshot first.[/]")
        return
    parts = arg.split() if arg else []
    target_entry = None
    file_args: list[str] = []
    if parts:
        first = parts[0]
        # Select snapshot by hash prefix or #n
        if first.startswith("#"):
            try:
                idx = int(first[1:]) - 1
                if 0 <= idx < len(state.snapshots):
                    target_entry = state.snapshots[idx]
            except ValueError:
                pass
        elif len(first) >= 7:
            for e in state.snapshots:
                if e["hash"].startswith(first):
                    target_entry = e
                    break
        if target_entry is None and not first.startswith("#"):
            # Treat first token as a file if it didn't match a snapshot
            file_args.append(first)
        file_args.extend(parts[1:] if target_entry else parts[1:])
    if target_entry is None:
        target_entry = state.snapshots[-1]

    if file_args:
        n = snap_mod.revert_files(state.cwd, target_entry["hash"], file_args)
        console.print(
            f"[green]Reverted {n} file(s) to snapshot[/] "
            f"{target_entry['hash'][:12]} ([dim]{target_entry['label']}[/])"
        )
    else:
        changed = snap_mod.diff_files(state.cwd, target_entry["hash"])
        if not changed:
            console.print("[dim]No changes since that snapshot — nothing to revert.[/]")
            return
        try:
            answer = input(
                f"  Revert {len(changed)} changed file(s) to snapshot "
                f"{target_entry['hash'][:12]}? This overwrites working-tree state. [y/N] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        confirmed = answer in ("y", "yes")
        if not confirmed:
            console.print("[dim]Revert cancelled.[/]")
            return
        ok = snap_mod.restore(state.cwd, target_entry["hash"])
        if ok:
            console.print(
                f"[green]Restored working tree to snapshot[/] "
                f"{target_entry['hash'][:12]} ([dim]{target_entry['label']}[/])"
            )
        else:
            console.print("[red]Revert failed — see log for details.[/]")


async def _cmd_init(state: SessionState) -> None:
    ye_md = state.cwd / "YE.md"
    if ye_md.exists():
        console.print(
            f"[yellow]YE.md already exists at {ye_md}.[/]\n"
            "[dim]Use /edit YE.md to modify it.[/]"
        )
        return
    ye_md.write_text(_YE_MD_TEMPLATE, encoding="utf-8")
    console.print(
        f"[green]Created YE.md[/] in {state.cwd}\n"
        "[dim]Edit it to customize project instructions for Ye.[/]"
    )


async def _cmd_compact(state: SessionState, provider: ZhipuProvider) -> None:
    """Compact conversation — structured summary + tail turn preservation.

    Strategy (ported from opencode compaction.ts):
    - Split messages into "head" (to summarize) and "tail" (to keep verbatim).
      The tail boundary is computed by *turns* (a new turn starts at each user
      message), not by raw message count — so we never cut an assistant+tool
      pair in half.
    - Summarize the head using the structured Markdown template
      (Goal / Constraints / Progress / Key Decisions / Next Steps / ...).
    - On the 2nd+ compaction, inject the previous summary and ask for an
      *update* — keeps the summary stable and only costs the diff.
    - Old tool output is pruned more aggressively than assistant text, since
      tool results are the biggest context hogs and rarely need full fidelity
      once summarized.
    """
    if len(state.messages) <= 5:
        console.print("[dim]Conversation is short enough, no compaction needed.[/]")
        return

    # --- Compute tail boundary by turns ---
    # A "turn" = a user message + everything until the next user message.
    # Keep the last TAIL_TURNS turns verbatim.
    TAIL_TURNS = 1
    user_indices = [
        i for i, m in enumerate(state.messages)
        if m.role == "user" and i > 0  # skip the system prompt slot
    ]
    if len(user_indices) <= TAIL_TURNS:
        # Not enough turns to split — fall back to keeping the last few messages
        split_point = max(1, len(state.messages) - 4)
    else:
        split_point = user_indices[-TAIL_TURNS]

    # Skip the system prompt (index 0) when summarizing the head.
    head_start = 1
    old_messages = state.messages[head_start:split_point]
    recent_messages = state.messages[split_point:]

    if not old_messages:
        console.print("[dim]Nothing to compact — recent context is already minimal.[/]")
        return

    # --- Serialize head with tiered tool-output pruning ---
    # Tool results are the #1 context hog. We keep a small head+tail of each
    # so the model retains "what was tried" without the full dump.
    TOOL_KEEP_HEAD = 300
    TOOL_KEEP_TAIL = 150
    ASSISTANT_KEEP = 1000

    parts: list[str] = []
    for msg in old_messages:
        role = msg.role.upper()
        text = msg.content or ""
        tool_names = ""
        if msg.tool_calls:
            tool_names = f" [tools: {', '.join(tc.name for tc in msg.tool_calls)}]"
        if role == "TOOL":
            if len(text) > TOOL_KEEP_HEAD + TOOL_KEEP_TAIL:
                text = (
                    text[:TOOL_KEEP_HEAD]
                    + f"\n... [pruned {len(text) - TOOL_KEEP_HEAD - TOOL_KEEP_TAIL} chars] ...\n"
                    + text[-TOOL_KEEP_TAIL:]
                )
        elif role == "ASSISTANT" and len(text) > ASSISTANT_KEEP:
            text = text[:ASSISTANT_KEEP] + "..."
        parts.append(f"[{role}]{tool_names}: {text}")

    conversation_text = "\n".join(parts)
    if len(conversation_text) > 16000:
        conversation_text = conversation_text[-16000:]

    from app.prompts import CompactPrompt

    # --- Build the compaction prompt (incremental if we have a prior summary) ---
    summarize_messages = [
        _get_chat_message()(
            role="system",
            content=CompactPrompt.system_message(),
        ),
        _get_chat_message()(
            role="user",
            content=CompactPrompt.user_message(
                conversation_text,
                previous_summary=state.last_summary,
            ),
        ),
    ]

    mode_label = "Updating summary" if state.last_summary else "Compacting conversation"
    console.print(f"[dim]{mode_label}...[/]\n")
    summary_parts: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0

    try:
        async for chunk in provider.chat(
            messages=summarize_messages,
            max_tokens=1200,
            temperature=0.3,
            model=state.model,
        ):
            if chunk.type == "text_delta":
                # Stream the summary live instead of buffering silently —
                # gives immediate feedback during the compaction round-trip.
                summary_parts.append(chunk.text)
                _stdout_write(chunk.text)
                _stdout_flush()
            elif chunk.type == "usage":
                prompt_tokens += chunk.usage.get("prompt_tokens", 0)
                completion_tokens += chunk.usage.get("completion_tokens", 0)
                total_tokens += chunk.usage.get("total_tokens", 0)
    except Exception as e:
        console.print(f"\n[red]Compaction failed:[/] {e}")
        return

    summary = "".join(summary_parts)
    console.print()  # newline after streamed summary

    # --- Rebuild messages: system + anchored summary + preserved tail ---
    old_count = len(state.messages)
    state.last_summary = summary
    state.messages = [
        _system_prompt(state.cwd, state=state),
        _get_chat_message()(
            role="user",
            content=(
                "[Anchored conversation summary — earlier turns were compacted. "
                "Use this as durable context for the remaining work.]\n\n" + summary
            ),
        ),
        *recent_messages,
    ]
    state.usage_records.append(UsageRecord(
        model=state.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    ))
    new_count = len(state.messages)
    console.print(
        f"[green]Compacted {old_count} -> {new_count} messages[/] "
        f"({len(summary)} chars summary, {len(recent_messages)} tail kept)"
    )


async def _edit_file(filename: str, cwd: Path) -> None:
    """Open a file in the system's default editor."""
    filepath = (cwd / filename).resolve()
    if not filepath.is_file():
        console.print(f"[red]File not found:[/] {filepath}")
        return

    editor = os.environ.get("EDITOR", "") or os.environ.get("VISUAL", "")
    if sys.platform == "win32" and not editor:
        editor = "notepad"

    if not editor:
        editor = "vi"

    console.print(f"[dim]Opening {filepath} with {editor}...[/]")
    try:
        proc = await asyncio.create_subprocess_exec(
            editor, str(filepath),
            cwd=str(cwd),
        )
        await proc.wait()
    except FileNotFoundError:
        console.print(f"[red]Editor '{editor}' not found. Set EDITOR env variable.[/]")
    except Exception as e:
        console.print(f"[red]Error opening editor:[/] {e}")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def _detect_cmd_name() -> str:
    """Infer the command name used to invoke Ye (for help/banner text).

    Returns "ye" or "yjl" when launched via the installed console-script wrapper,
    otherwise "ye" as the canonical fallback.
    """
    # Explicit override (set by the yjl.bat wrapper so --help shows the right name)
    env_cmd = os.environ.get("YE_CMD", "").strip().lower()
    if env_cmd in ("yjl", "ye"):
        return env_cmd
    try:
        base = Path(sys.argv[0]).name.lower() if sys.argv else ""
    except Exception:
        base = ""
    if base.endswith(".exe"):
        base = base[:-4]
    if base in ("yjl", "ye"):
        return base
    # python -m app.cli.main → still show the canonical command
    return "ye"


def _parse_args(argv: list[str] | None = None) -> dict:
    """Parse CLI arguments: yjl|ye [-r] [-p PROMPT] [--model MODEL] [-v] [-h]."""
    import argparse

    cmd = _detect_cmd_name()
    parser = argparse.ArgumentParser(
        prog=cmd,
        description="Ye — AI coding assistant (Claude Code clone)",
        add_help=True,
    )
    parser.add_argument(
        "-r", "--resume",
        action="store_true",
        help="Resume the most recent conversation session",
    )
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        nargs="?",
        const="",
        default=None,
        help="Run a single prompt non-interactively (no REPL)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Specify the model to use (e.g., glm-5.2, glm-5.1, glm-4-plus)",
    )
    parser.add_argument(
        "-v", "--version",
        action="store_true",
        help="Show version and exit",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="Resume a specific session by ID",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=0,
        help="Auto-retry on failure (max attempts, e.g. --retry 3)",
    )

    args = parser.parse_args(argv)
    return {
        "resume": args.resume or bool(args.session),
        "prompt": args.prompt,
        "model": args.model,
        "version": args.version,
        "session_id": args.session,
        "retry": args.retry,
    }


def main():
    if sys.version_info < (3, 10):
        print(f"Error: Python 3.10+ required, got {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)
    warnings.filterwarnings("ignore", message="Using default SECRET_KEY")
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    cli_args = _parse_args()
    try:
        _run_async(_run(cli_args))
    except KeyboardInterrupt:
        pass


def _run_async(coro):
    """Run a coroutine to completion with thorough teardown.

    Like asyncio.run(), but drains async generators and the default executor
    BEFORE closing the loop, so no StreamWriter/SSL transport is left dangling
    to raise 'Event loop is closed' during interpreter GC.
    """
    import asyncio
    import threading

    # Silence "Exception ignored in: <function StreamWriter.__del__ ...>"
    # that asyncio prints during teardown even after our cleanup. These are
    # benign (the loop is already closed) and only produce ugly noise.
    def _quiet_threading_excepthook(args):
        msg = str(args.exc_value) if args.exc_value else ""
        if args.exc_type is RuntimeError and "Event loop is closed" in msg:
            return
        _prev_threading_hook(args)

    _prev_threading_hook = threading.excepthook
    threading.excepthook = _quiet_threading_excepthook

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        try:
            loop.run_until_complete(loop.shutdown_default_executor())
        except Exception:
            pass
        try:
            asyncio.set_event_loop(None)
            loop.close()
        except Exception:
            pass


async def _run(cli_args: dict):
    try:
        await _run_inner(cli_args)
    finally:
        # Close all HTTP clients before the event loop tears down.
        # The provider keeps its own AsyncClient (separate from the tools'
        # shared client); closing both prevents StreamWriter.__del__ from
        # raising 'Event loop is closed' tracebacks during interpreter teardown.
        try:
            if _provider is not None and hasattr(_provider, "aclose"):
                await _provider.aclose()
        except Exception:
            pass
        from app.llm.tools import cleanup_http_client
        try:
            await cleanup_http_client()
        except Exception:
            pass
        # Shut down MCP server connections (subprocesses / HTTP clients).
        global _mcp_session
        if _mcp_session is not None:
            try:
                await _mcp_session.shutdown()
            except Exception:
                pass
            _mcp_session = None


async def _run_inner(cli_args: dict):
    from rich.panel import Panel
    from rich import box
    from app.config import settings
    from app.cli.theme import PRIMARY, PRIMARY_DEEP, DANGER, ACCENT, MUTED, MUTED_LIGHT

    # --version: print and exit early
    if cli_args.get("version"):
        print(f"Ye v{settings.VERSION}")
        return

    # --- Compact startup banner (only in interactive mode) ---
    if cli_args.get("prompt") is None:
        console.print(_build_banner(
            version=settings.VERSION,
            model=cli_args.get("model") or settings.ZHIPU_MODEL,
            cwd=str(Path.cwd()),
        ))
        console.print()

    if not settings.ZHIPU_API_KEY:
        # Graceful, well-formatted configuration prompt (no ugly red box).
        console.print(Panel(
            f"[bold {DANGER}]API key not configured[/bold {DANGER}]\n\n"
            f"[{MUTED_LIGHT}]Add your Zhipu key to [bold].env[/bold] (in the backend/ folder):[/]\n"
            f"  [{ACCENT}]ZHIPU_API_KEY[/] [{MUTED}]=your-key-here[/]\n\n"
            f"[{MUTED}]Get one from [bold]https://open.bigmodel.cn/[/bold][/]",
            border_style=f"dim {DANGER}",
            padding=(1, 2),
            box=box.ROUNDED,
        ))
        sys.exit(1)

    # Config is loaded, but defer LLM modules until first message
    ChatMessage = _get_chat_message()

    state = SessionState(
        model=cli_args.get("model") or settings.ZHIPU_MODEL,
        cwd=Path.cwd(),
    )

    # --resume / --session: load previous session
    resumed_session_id = None
    if cli_args.get("resume"):
        import app.sessions as sessions
        session_id = cli_args.get("session_id")

        # If specific session ID given, load it directly
        if session_id:
            data = sessions.load_session(session_id)
        else:
            # Interactive session picker (like Claude Code)
            recent = sessions.list_sessions(limit=10)
            if not recent:
                console.print("[dim]No previous sessions found. Starting fresh.[/]")
                data = None
            else:
                from rich.table import Table
                table = Table(title="Select a session to resume", show_lines=False)
                table.add_column("#", style="bold", width=3)
                table.add_column("Session ID", style="cyan")
                table.add_column("Model")
                table.add_column("Msgs", justify="right")
                table.add_column("Preview", style="dim", max_width=60)
                table.add_column("Saved", style="dim")
                for i, s in enumerate(recent, 1):
                    preview = s.get("preview", "")[:60]
                    saved = s.get("saved_at", "")[:16]
                    table.add_row(str(i), s["id"], s.get("model", "?"), str(s.get("message_count", 0)), preview, saved)
                console.print(table)
                console.print("[dim]Enter number to resume, or press Enter to start fresh.[/]")
                try:
                    choice = input("Resume session #> ").strip()
                except (EOFError, KeyboardInterrupt):
                    console.print("[dim]Starting fresh session.[/]")
                    choice = ""

                data = None
                if choice:
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(recent):
                            selected_id = recent[idx]["id"]
                            data = sessions.load_session(selected_id)
                        else:
                            console.print(f"[dim]Invalid selection. Starting fresh.[/]")
                    except ValueError:
                        # User might have typed a session ID directly
                        data = sessions.load_session(choice)

        if data is not None:
            restored_msgs = sessions.deserialize_messages(data.get("messages", []))
            restored_usage = sessions.deserialize_usage_records(data.get("usage_records", []))
            state.messages = restored_msgs
            state.usage_records = restored_usage
            state.model = cli_args.get("model") or data.get("model", state.model)
            saved_cwd = data.get("cwd", "")
            if saved_cwd and Path(saved_cwd).is_dir():
                os.chdir(saved_cwd)
                state.cwd = Path(saved_cwd)
            state.session_start = time.time()
            resumed_session_id = data.get("id")
            console.print(
                f"[green]Resumed session[/] {resumed_session_id} "
                f"({len(state.messages)} messages, model: {state.model})"
            )
            # Invalidate cached system prompt
            state._cached_system_prompt = None
            # Refresh system prompt (update cwd, memory context)
            state.messages[0] = _system_prompt(state.cwd, state=state)

    if not cli_args.get("resume") or resumed_session_id is None:
        state.messages = [_system_prompt(state=state)]

    # Preload LLM modules in background while user is at the prompt
    preload_done = asyncio.Event()
    _preloaded_provider = None
    _preloaded_executor = None

    async def _preload():
        nonlocal _preloaded_provider, _preloaded_executor
        try:
            _preloaded_provider = _get_provider()
            _preloaded_executor = _get_executor(_preloaded_provider)
            # Pre-warm TCP+TLS connection to Zhipu API
            try:
                await _preloaded_provider._get_http().warmup(
                    settings.ZHIPU_BASE_URL.rstrip("/")
                )
            except Exception:
                pass
        except Exception:
            pass
        preload_done.set()

    asyncio.create_task(_preload())

    provider = None
    executor = None

    # --- MCP: connect external tool servers (if configured) ---
    # Done in the background so it doesn't block startup; tools are registered
    # into the executor once available. Failures are logged, never fatal.
    global _mcp_session
    try:
        from app.mcp_client import ClientSession, load_server_configs
        mcp_configs = load_server_configs()
        if mcp_configs:
            _mcp_session = ClientSession()

            async def _connect_mcp():
                try:
                    # Wait for preload so we register into the SAME executor the
                    # REPL will use (avoids any timing ambiguity).
                    await preload_done.wait()
                    await _mcp_session.connect(mcp_configs)
                    if _mcp_session.is_connected:
                        mcp_provider = _preloaded_provider or _get_provider()
                        mcp_executor = _preloaded_executor or _get_executor(mcp_provider)
                        from app.llm.tools import register_mcp_tools
                        n = register_mcp_tools(mcp_executor, _mcp_session)
                        if n:
                            console.print(f"[dim]\\_ MCP: {len(_mcp_session._connections)} server(s), {n} tool(s) registered[/]")
                except Exception as e:
                    logger.debug("MCP connect failed: %s", e)

            asyncio.create_task(_connect_mcp())
    except Exception:
        pass

    # --prompt: non-interactive mode
    prompt_text_arg = cli_args.get("prompt")
    if prompt_text_arg is not None:
        if not prompt_text_arg:
            console.print(f"[dim]Usage: {_detect_cmd_name()} -p \"your prompt here\"[/]")
            return
        provider = _get_provider()
        executor = _get_executor(provider)

        # Bind the todo list so the todo_write tool works in -p mode too
        # (otherwise it returns "not available in this context").
        if state.todo_list is None:
            from app.todo_store import TodoList
            state.todo_list = TodoList()
        from app.llm.tools.todo_ops import set_active_todos
        set_active_todos(state.todo_list)

        state.messages.append(ChatMessage(role="user", content=prompt_text_arg))

        p_timer = _TurnTimer()
        p_timer.start_thinking()
        assistant_parts: list[str] = []
        p_tools = 0
        p_tidx = 0

        try:
            async for chunk in executor.run_agentic_loop(
                messages=state.messages, model=state.model
            ):
                if chunk.type == "text_delta":
                    if p_timer.first_token_time is None:
                        p_timer.stop_thinking()
                    _stdout_write(chunk.text)
                    _stdout_flush()
                    assistant_parts.append(chunk.text)
                    p_timer.add_tokens(chunk.text)
                elif chunk.type == "tool_call_end":
                    p_tools += 1
                elif chunk.type == "tool_execution_start":
                    if p_timer.first_token_time is None:
                        p_timer.stop_thinking()
                    p_tidx += 1
                    p_timer.mark_tool_start()
                    tool_name = chunk.text.replace("Executing: ", "")
                    progress = f" ({p_tidx}/{p_tools})" if p_tools > 1 else ""
                    from app.cli.theme import tool_start_line
                    console.print()
                    _stdout_write(tool_start_line(tool_name, progress))
                    _stdout_flush()
                elif chunk.type == "tool_execution_result":
                    console.print(f"[dim green]v[/] [dim]{p_timer.tool_elapsed()}[/]")
                elif chunk.type == "tool_execution_error":
                    console.print(f"[dim red]x[/]")
                elif chunk.type == "usage":
                    state.usage_records.append(UsageRecord(
                        model=state.model,
                        prompt_tokens=chunk.usage.get("prompt_tokens", 0),
                        completion_tokens=chunk.usage.get("completion_tokens", 0),
                        total_tokens=chunk.usage.get("total_tokens", 0),
                    ))
                elif chunk.type == "messages_update":
                    state.messages = chunk.usage.get("messages", state.messages)
                elif chunk.type == "error":
                    console.print(f"\n[bold red]Error:[/] {chunk.text}")
        except Exception as e:
            console.print(f"\n[bold red]Error:[/] {e}")

        console.print()  # trailing newline

        # --- Auto-retry: if --retry N was set and there was an error, retry ---
        max_retries = cli_args.get("retry", 0)
        last_error = None
        if max_retries > 0:
            for attempt in range(1, max_retries + 1):
                # Check if previous attempt had issues
                output_text = "".join(assistant_parts).lower()
                has_error = any(kw in output_text for kw in ["error", "failed", "exception", "traceback", "失败"])
                if not has_error:
                    break

                last_error = output_text
                console.print(f"\n[yellow]Auto-retry {attempt}/{max_retries} — previous attempt had errors. Trying different approach...[/]\n")
                retry_prompt = (
                    f"上一次尝试出现了错误。请换一种思路来解决这个问题。\n"
                    f"上一次的错误信息摘要: {last_error[:300]}\n"
                    f"不要尝试和上次相同的方法。"
                )
                state.messages.append(ChatMessage(role="user", content=retry_prompt))
                assistant_parts = []

                try:
                    async for chunk in executor.run_agentic_loop(
                        messages=state.messages, model=state.model
                    ):
                        if chunk.type == "text_delta":
                            _stdout_write(chunk.text)
                            _stdout_flush()
                            assistant_parts.append(chunk.text)
                        elif chunk.type == "tool_execution_start":
                            from app.cli.theme import tool_start_line
                            tool_name = chunk.text.replace('Executing: ', '')
                            console.print()
                            _stdout_write(tool_start_line(tool_name))
                            _stdout_flush()
                        elif chunk.type == "tool_execution_result":
                            console.print(f"[dim green]v[/]")
                        elif chunk.type == "tool_execution_error":
                            console.print(f"[dim red]x[/]")
                        elif chunk.type == "messages_update":
                            state.messages = chunk.usage.get("messages", state.messages)
                        elif chunk.type == "error":
                            console.print(f"\n[bold red]Error:[/] {chunk.text}")
                except Exception as e:
                    console.print(f"\n[bold red]Error:[/] {e}")

                console.print()

            else:
                if last_error:
                    console.print(f"\n[bold red]All {max_retries} retry attempts exhausted.[/]")

        # Auto-save session
        import app.sessions as sessions
        sessions.save_session(
            messages=sessions.serialize_messages(state.messages),
            model=state.model,
            cwd=str(state.cwd),
            usage_records=sessions.serialize_usage_records(state.usage_records),
        )
        return

    # Interactive REPL mode
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.completion import Completer, Completion

        class SlashCompleter(Completer):
            """Auto-complete slash commands, like Claude Code."""
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor
                if not text.startswith("/"):
                    return
                word = text.lstrip()
                for cmd, desc in SLASH_COMMANDS:
                    cmd_name = cmd.split()[0]  # "/help", "/model", etc.
                    if cmd_name.startswith(word) and cmd_name != word:
                        yield Completion(
                            cmd_name,
                            start_position=-len(word),
                            display_meta=desc,
                        )

        history_file = Path.home() / ".ye_history"

        from prompt_toolkit.key_binding import KeyBindings
        _kb = KeyBindings()
        @_kb.add('escape')
        def _esc_exit(event):
            event.app.exit(exception=EOFError(), style='class:aborting')
        @_kb.add('s-tab')  # Shift+Tab: cycle mode (normal → plan → auto_accept)
        def _shift_tab_cycle(event):
            _cycle_mode(state)
            event.app.invalidate()  # Refresh toolbar

        session: PromptSession = PromptSession(
            history=FileHistory(str(history_file)),
            completer=SlashCompleter(),
            complete_while_typing=True,
            key_bindings=_kb,
        )

        # Bottom toolbar showing context window usage + current mode (like Claude Code)
        def _bottom_toolbar():
            used_ctx, max_ctx = _get_context_usage(state)
            remaining = max(0, max_ctx - used_ctx)
            ctx_pct = used_ctx / max_ctx * 100 if max_ctx > 0 else 0
            if ctx_pct < 60:
                color = "#4ade80"      # PRIMARY green
            elif ctx_pct < 85:
                color = "#fbbf24"      # WARN amber
            else:
                color = "#f87171"      # DANGER red
            # Session duration
            session_elapsed = time.time() - state.session_start
            h, r = divmod(int(session_elapsed), 3600)
            m, s = divmod(r, 60)
            time_str = f"{h}h{m}m" if h else f"{m}m{s}s"
            # Mode indicator
            mode_label, mode_style = _MODE_LABELS[state.mode]
            return FormattedText([
                (mode_style, f" {mode_label} "),
                ("bg:#0f0f1e fg:#6b7280", f"  {time_str}  "),
                ("bg:#0f0f1e fg:#6b7280", "  |  ctx "),
                (f"bg:#0f0f1e fg:{color}", f"{_format_tokens(used_ctx)}/{_format_tokens(max_ctx)}"),
                ("bg:#0f0f1e fg:#6b7280", f"  ({_format_tokens(remaining)} free)  "),
                ("bg:#0f0f1e fg:#4b5563", " Shift+Tab = mode"),
            ])

    except Exception:
        session = None

    while True:
        # Prompt: a leaf-tinted chevron. Brand green primary, muted when empty.
        prompt_text = FormattedText([("#22c55e", "> ")]) if session else None

        try:
            if session:
                user_input = await asyncio.to_thread(
                    session.prompt, prompt_text,
                    bottom_toolbar=_bottom_toolbar,
                )
            else:
                user_input = input("> ")
        except (EOFError, KeyboardInterrupt):
            console.print(f"\n[{PRIMARY_DEEP}]See you next time.[/]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        is_skill = user_input.startswith("/")
        if user_input.startswith("/"):
            try:
                result = await _handle_command(user_input, state, provider, executor)
            except Exception as e:
                console.print(f"[red]Command error:[/] {e}")
                result = "ok"
            if result == "exit":
                break
            # A skill command injected a user message — fall through to run the
            # agentic loop on it (instead of skipping as a normal command would).
            if result != "skill":
                continue

        # Refresh system prompt if mode changed (plan mode adds read-only instructions)
        if state.messages and state.messages[0].role == "system":
            state.messages[0] = _system_prompt(state.cwd, state=state)

        # A skill command already appended its body as a user message; otherwise
        # append the raw user input now.
        if not is_skill:
            state.messages.append(ChatMessage(role="user", content=user_input))

        # Lazy init: use preloaded modules or load on demand
        if provider is None:
            if not preload_done.is_set():
                _stdout_write("\r\x1b[2mLoading AI modules...\x1b[0m")
                _stdout_flush()
            await preload_done.wait()
            if _preloaded_provider is not None:
                provider = _preloaded_provider
                executor = _preloaded_executor
            if executor is None:
                provider = provider or _get_provider()
                executor = _get_executor(provider)

        # Auto-compact: if context is too large, compress before sending
        if len(state.messages) > 40:
            total_chars = sum(len(m.content or "") for m in state.messages)
            if total_chars > 80000:
                console.print("[dim]Context large, auto-compacting...[/]")
                await _cmd_compact(state, provider)

        # --- Harness: create fresh Budget + Trace for this turn ---
        turn_budget = _get_budget()
        turn_budget.start()
        turn_trace = _get_trace(session_id=resumed_session_id or "")
        turn_trace.start(user_input)

        executor.set_budget(turn_budget)
        executor.set_trace(turn_trace)

        # --- Harness: Failure Handler ---
        from app.failure import FailureHandler
        turn_failures = FailureHandler()
        executor.set_failure_handler(turn_failures)

        # --- TodoWrite: bind the session todo list to the tool for this turn ---
        if state.todo_list is None:
            from app.todo_store import TodoList
            state.todo_list = TodoList()
        from app.llm.tools.todo_ops import set_active_todos
        set_active_todos(state.todo_list)

        # --- Harness: Budget compact callback ---
        # Only compact on RED zone. YELLOW just warns — compacting on yellow
        # creates a feedback loop because budget tracks cumulative tokens,
        # not context size, so compression doesn't help the budget counter.
        async def _budget_compact_callback(zone: str, msgs: list):
            if zone == "red":
                console.print("[dim yellow]Budget zone RED, auto-compressing context...[/]")
                await _cmd_compact(state, provider)
                return state.messages
            # YELLOW: warn only, don't compress
            return msgs

        executor.set_compact_callback(_budget_compact_callback)

        # --- Harness: Permission system (auto/ask/deny) + mode-aware approval ---
        async def _approval_callback(tool_name: str, args: dict) -> bool:
            from app.permissions import check_tool, approve_for_session

            # Plan mode: block ALL write/edit/run tools
            if state.mode == "plan":
                write_tools = {"write_file", "edit_file", "append_file", "run_command", "spawn_agent"}
                if tool_name in write_tools:
                    console.print(f"[yellow]⚠ Plan mode: [bold]{tool_name}[/] blocked (read-only)[/]")
                    return False

            # Auto-accept mode: approve everything (unless explicitly denied)
            if state.mode == "auto_accept":
                perm = check_tool(tool_name)
                if perm == "deny":
                    console.print(f"[red]x {tool_name} 已被禁止（deny）[/]")
                    return False
                return True  # Auto-approve

            # Normal mode: existing approval flow
            perm = check_tool(tool_name)
            if perm == "allow":
                return True
            if perm == "deny":
                console.print(f"[red]x {tool_name} 已被禁止（deny）[/]")
                return False

            # "ask" mode — prompt user
            summary = ""
            if tool_name == "run_command":
                cmd = args.get("command", "?")
                summary = f"  命令: {cmd[:120]}\n"
            elif tool_name in ("write_file", "edit_file"):
                path = args.get("path") or args.get("file_path", "?")
                summary = f"  文件: {path}\n"
            console.print(f"\n[yellow]⚠ 需要确认: [bold]{tool_name}[/][/]")
            if summary:
                console.print(f"[dim]{summary}[/]")
            try:
                answer = input("  允许执行? [y/Y(e=always)/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return False

            if answer in ("y", "yes", "是"):
                return True
            if answer in ("e", "always", "auto"):
                from app.permissions import set_permission
                set_permission(tool_name, "auto")
                console.print(f"[green]v {tool_name} 已设为自动允许（本次及以后）[/]")
                return True
            return False

        executor.set_approval_callback(_approval_callback)

        # --- Start live timer (Claude Code-style animated feedback) ---
        timer = _TurnTimer()
        timer.start_thinking()
        assistant_parts: list[str] = []
        pending_tool_count = 0
        tool_exec_idx = 0
        in_tool_phase = False
        grouped_tools = False  # True when concurrent tools are grouped
        group_ok = 0
        group_fail = 0

        try:
            async for chunk in executor.run_agentic_loop(
                messages=state.messages, model=state.model
            ):
                if chunk.type == "text_delta":
                    if timer.first_token_time is None:
                        timer.stop_thinking()
                    # Flush grouped tool summary before streaming text
                    if grouped_tools and (group_ok + group_fail) > 0:
                        tool_dur = timer.tool_elapsed()
                        parts = [f"v{group_ok}"]
                        if group_fail:
                            parts.append(f"x{group_fail}")
                        console.print(f"[dim]{'/'.join(parts)} {tool_dur}[/]")
                        grouped_tools = False
                        group_ok = 0
                        group_fail = 0
                    if in_tool_phase:
                        pending_tool_count = 0
                        tool_exec_idx = 0
                        in_tool_phase = False
                    _stdout_write(chunk.text)
                    _stdout_flush()
                    assistant_parts.append(chunk.text)
                    timer.add_tokens(chunk.text)

                elif chunk.type == "tool_call_end":
                    pending_tool_count += 1

                elif chunk.type == "tool_execution_start":
                    in_tool_phase = True
                    if timer.first_token_time is None:
                        timer.stop_thinking()
                    # Flush previous grouped summary
                    if grouped_tools and (group_ok + group_fail) > 0:
                        tool_dur = timer.tool_elapsed()
                        parts = [f"v{group_ok}"]
                        if group_fail:
                            parts.append(f"x{group_fail}")
                        console.print(f"[dim]{'/'.join(parts)} {tool_dur}[/]")
                        group_ok = 0
                        group_fail = 0
                    timer.mark_tool_start()
                    tool_name = chunk.text.replace("Executing: ", "")
                    from app.cli.theme import tool_start_line
                    # Detect grouped tools by empty tool_call_id
                    is_grouped = not getattr(chunk, "tool_call_id", None)
                    if is_grouped:
                        grouped_tools = True
                        group_ok = 0
                        group_fail = 0
                    else:
                        grouped_tools = False
                    _stdout_write(tool_start_line(tool_name))
                    _stdout_flush()

                elif chunk.type == "tool_execution_result":
                    if grouped_tools:
                        group_ok += 1
                    else:
                        tool_dur = timer.tool_elapsed()
                        result_text = chunk.text[:500]
                        if len(chunk.text) > 500:
                            result_text += "..."
                        if "\n" not in result_text and len(result_text) < 80:
                            console.print(f"[dim green]v[/] [dim]{tool_dur} {result_text}[/]")
                        else:
                            console.print(f"[dim green]v {tool_dur}[/]")

                elif chunk.type == "tool_execution_error":
                    if grouped_tools:
                        group_fail += 1
                    else:
                        tool_dur = timer.tool_elapsed()
                        from app.cli.theme import tool_fail_line, ANSI_DIM, ANSI_RED, ANSI_RESET
                        _stdout_write(tool_fail_line(tool_dur))
                        _stdout_flush()
                        console.print(f"\n  {ANSI_RED}{chunk.text[:300]}{ANSI_RESET}")

                elif chunk.type == "escalation":
                    if grouped_tools and (group_ok + group_fail) > 0:
                        tool_dur = timer.tool_elapsed()
                        parts = [f"v{group_ok}"]
                        if group_fail:
                            parts.append(f"x{group_fail}")
                        console.print(f"[dim]{'/'.join(parts)} {tool_dur}[/]")
                        grouped_tools = False
                    console.print(f"\n[bold yellow]Escalation:[/] {chunk.text}")
                    console.print("[dim]This task requires human intervention. Please review and take action.[/]")

                elif chunk.type == "budget_compact":
                    if grouped_tools and (group_ok + group_fail) > 0:
                        tool_dur = timer.tool_elapsed()
                        parts = [f"v{group_ok}"]
                        if group_fail:
                            parts.append(f"x{group_fail}")
                        console.print(f"[dim]{'/'.join(parts)} {tool_dur}[/]")
                        grouped_tools = False
                    console.print(f"[dim yellow]{chunk.text}[/]")

                elif chunk.type == "usage":
                    state.usage_records.append(UsageRecord(
                        model=state.model,
                        prompt_tokens=chunk.usage.get("prompt_tokens", 0),
                        completion_tokens=chunk.usage.get("completion_tokens", 0),
                        total_tokens=chunk.usage.get("total_tokens", 0),
                    ))

                elif chunk.type == "messages_update":
                    state.messages = chunk.usage.get("messages", state.messages)

                elif chunk.type == "error":
                    err_text = chunk.text
                    if "401" in err_text or "Authorization" in err_text:
                        console.print(
                            "\n[bold red]Authentication failed.[/]\n"
                            "[dim]Your API key is invalid or expired. Check your .env file:\n"
                            "  ZHIPU_API_KEY=your-key-here\n\n"
                            "Get a key from: https://open.bigmodel.cn/[/]"
                        )
                    elif "429" in err_text or "rate" in err_text.lower():
                        console.print(f"\n[bold yellow]Rate limited[/] — waiting a moment and try again.")
                    else:
                        console.print(f"\n[bold red]Error:[/] {err_text}")
                    # Don't break — messages_update chunk follows error and must be consumed

            # --- Turn summary (Claude Code-style timing line) ---
            budget_zone = turn_budget.check_zone()
            used_ctx, max_ctx = _get_context_usage(state)
            ctx_pct = used_ctx / max_ctx * 100 if max_ctx > 0 else 0

            # Build a clean summary line: (2m 30s · ↓1.2K · ctx 8.5K/128K)
            summary_parts = [timer.elapsed_str]
            if timer.first_token_time:
                ttfb = timer.first_token_time - timer.start_time
                summary_parts.append(f"TTFB {ttfb:.1f}s")
            if timer.tokens_output > 100:
                approx = timer.tokens_output // 4
                summary_parts.append(f"↓{_format_tokens(approx)} tokens")
            summary_parts.append(f"ctx {_format_tokens(used_ctx)}/{_format_tokens(max_ctx)} ({ctx_pct:.0f}%)")
            if budget_zone.value != "green":
                summary_parts.append(f"budget:[{budget_zone.value}]")

            console.print(f"\n[dim]({' · '.join(summary_parts)})[/]")

            # --- Harness: finish trace ---
            turn_trace.finish(output="".join(assistant_parts), success=True)

            # --- Auto-save project state to .ye/project_state.md ---
            _save_project_state(state, "".join(assistant_parts))

            # --- Auto-snapshot: if this turn mutated files, capture a restore point ---
            # Only snapshot when tools actually ran (pending_tool_count tracks
            # tool calls in this turn). Keeps empty turns from spamming git.
            if pending_tool_count > 0 and state.mode != "plan":
                try:
                    from app import snapshot as snap_mod
                    h = snap_mod.snapshot(state.cwd)
                    if h is not None:
                        # Dedup: don't record an identical tree twice in a row.
                        if not state.snapshots or state.snapshots[-1]["hash"] != h:
                            state.snapshots.append({
                                "hash": h,
                                "time": time.time(),
                                "label": f"auto (turn, {pending_tool_count} tool)",
                            })
                except Exception:
                    pass  # snapshot is a safety net, never block the turn

            # --- TodoWrite: render live progress if the list is active ---
            if state.todo_list is not None and not state.todo_list.is_empty:
                done, total = state.todo_list.progress()
                console.print(f"[dim]\\_ todos: {done}/{total} done[/]")

            # --- Post-loop hooks (Stop hook equivalent) ---
            try:
                from app.hooks import run_hook
                hook_output = run_hook("post_loop", {"cwd": str(state.cwd)})
                if hook_output:
                    console.print(f"[dim]\\_ post-loop hook: {hook_output[:200]}[/]")
            except Exception as e:
                pass  # post-loop hook failure is non-critical

        except Exception as e:
            timer.stop_thinking()
            console.print(f"\n[bold red]Error:[/] {e}\n")
            turn_trace.finish(output=str(e), success=False)
            if assistant_parts:
                state.messages.append(ChatMessage(
                    role="assistant", content="".join(assistant_parts)
                ))

    # Auto-save session on exit
    import app.sessions as sessions
    sessions.save_session(
        messages=sessions.serialize_messages(state.messages),
        model=state.model,
        cwd=str(state.cwd),
        usage_records=sessions.serialize_usage_records(state.usage_records),
    )


async def _handle_command(
    cmd: str, state: SessionState, provider: ZhipuProvider, executor
) -> str:
    from rich.panel import Panel
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/exit", "/quit", "/q"):
        console.print("[dim]Bye![/]")
        return "exit"

    if command == "/help":
        console.print(HELP_TEXT)

    elif command == "/model":
        if arg:
            state.model = arg.strip()
            console.print(f"[cyan]Model switched to:[/] {state.model}")
        else:
            console.print(f"[cyan]Current model:[/] {state.model}")
            console.print("[dim]Available: glm-5.2, glm-5.1, glm-5, glm-5-turbo, glm-4.7, glm-4.7-flashx, glm-4.6, glm-4-plus, glm-4-flash, glm-4-long, glm-4[/]")

    elif command == "/clear":
        state.messages.clear()
        state.messages.append(_system_prompt(state.cwd, state=state))
        console.print("[dim]Conversation cleared.[/]")

    elif command == "/pwd":
        console.print(str(state.cwd))

    elif command == "/cd":
        if not arg:
            console.print("[dim]Usage: /cd <path>[/]")
        else:
            new_cwd = (state.cwd / arg).resolve()
            if new_cwd.is_dir():
                os.chdir(new_cwd)
                state.cwd = new_cwd
                state._cached_system_prompt = None  # Invalidate prompt cache
                console.print(f"[dim]Changed to:[/] {state.cwd}")
            else:
                console.print(f"[red]Not a directory:[/] {new_cwd}")

    elif command == "/edit":
        if not arg:
            console.print("[dim]Usage: /edit <file>[/]")
        else:
            await _edit_file(arg.strip(), state.cwd)

    elif command == "/cost":
        await _cmd_cost(state)

    elif command == "/status":
        await _cmd_status(state)

    elif command == "/diff":
        await _cmd_diff(state)

    elif command == "/snapshot":
        await _cmd_snapshot(state, label=arg.strip())

    elif command == "/snapshots":
        await _cmd_snapshots(state)

    elif command == "/revert":
        await _cmd_revert(state, arg.strip())

    elif command == "/init":
        await _cmd_init(state)

    elif command == "/compact":
        await _cmd_compact(state, provider)

    elif command == "/memory":
        result = _get_mem().list_all()
        console.print(Panel(result or "No memories saved yet.", title="Memory", border_style="cyan"))

    elif command == "/remember":
        if not arg:
            console.print("[dim]Usage: /remember <category>: <text>[/]")
            console.print("[dim]Categories: user, feedback, project, reference[/]")
            console.print("[dim]Example: /remember user: I prefer Python with type hints[/]")
        else:
            cat = "user"
            text = arg
            if ":" in arg and arg.split(":")[0].strip().lower() in ("user", "feedback", "project", "reference"):
                cat, text = arg.split(":", 1)
                cat = cat.strip().lower()
                text = text.strip()
            name = text[:40].replace(" ", "_")
            result = _get_mem().save(cat, name, text)
            console.print(f"[green]{result}[/]")

    elif command == "/forget":
        if not arg:
            console.print("[dim]Usage: /forget <name>[/]")
        else:
            result = _get_mem().delete(arg.strip())
            console.print(f"[dim]{result}[/]")

    elif command == "/sessions":
        import app.sessions as sessions
        from rich.table import Table
        recent = sessions.list_sessions(limit=10)
        if not recent:
            console.print("[dim]No saved sessions found.[/]")
        else:
            table = Table(title="Recent Sessions", show_lines=False)
            table.add_column("ID", style="cyan")
            table.add_column("Model")
            table.add_column("Messages", justify="right")
            table.add_column("Saved At", style="dim")
            for s in recent:
                table.add_row(s["id"], s["model"], str(s["message_count"]), s["saved_at"][:19])
            console.print(table)
            console.print(f"[dim]Use /resume <id> to restore a session, or {_detect_cmd_name()} -r from CLI.[/]")

    elif command == "/resume":
        import app.sessions as sessions
        session_id = arg.strip() if arg else None
        data = sessions.load_session(session_id)
        if data is None:
            console.print("[dim]No session found.[/]")
        else:
            restored_msgs = sessions.deserialize_messages(data.get("messages", []))
            restored_usage = sessions.deserialize_usage_records(data.get("usage_records", []))
            state.messages = restored_msgs
            state.usage_records = restored_usage
            state.model = data.get("model", state.model)
            saved_cwd = data.get("cwd", "")
            if saved_cwd and Path(saved_cwd).is_dir():
                os.chdir(saved_cwd)
                state.cwd = Path(saved_cwd)
            state._cached_system_prompt = None
            state.messages[0] = _system_prompt(state.cwd, state=state)
            console.print(
                f"[green]Resumed session[/] {data['id']} "
                f"({len(state.messages)} messages, model: {state.model})"
            )

    elif command == "/budget":
        used_ctx, max_ctx = _get_context_usage(state)
        remaining = max(0, max_ctx - used_ctx)
        ctx_pct = used_ctx / max_ctx * 100 if max_ctx > 0 else 0
        total_tokens = sum(r.total_tokens for r in state.usage_records)

        lines = [
            f"  [cyan]Context Window:[/]  {_format_tokens(used_ctx)} / {_format_tokens(max_ctx)} ({ctx_pct:.0f}% used)",
            f"  [cyan]Remaining:[/]      {_format_tokens(remaining)}",
            f"  [cyan]Total Tokens:[/]   {total_tokens:,} (cumulative)",
            f"  [cyan]API Calls:[/]      {len(state.usage_records)}",
            "",
            "  [dim]Budget zones (per-turn, 300K total tokens):[/]",
            "  [green]GREEN[/] → normal  |  [yellow]YELLOW[/] (60%) → compress  |  [red]RED[/] (85%) → aggressive  |  [bold red]BREAKER[/] (95%) → stop",
        ]
        console.print(Panel("\n".join(lines), title="Token Budget & Context", border_style="cyan"))

    elif command == "/trace":
        from app.execution_trace import read_traces
        entries = read_traces(limit=20)
        if not entries:
            console.print("[dim]No execution traces found yet.[/]")
        else:
            from rich.table import Table
            table = Table(title="Recent Execution Trace", show_lines=False)
            table.add_column("Time", style="dim", width=19)
            table.add_column("Event", style="cyan", width=14)
            table.add_column("Detail", width=50)
            for e in entries[-20:]:
                detail = ""
                if e.get("tool"):
                    detail = f"{e['tool']} ({e.get('risk', '')})"
                elif e.get("zone"):
                    detail = f"zone={e['zone']} tokens={e.get('tokens_used', 0):,}"
                elif e.get("from_model"):
                    detail = f"{e['from_model']} → {e['to_model']}"
                elif e.get("message"):
                    detail = e["message"][:50]
                elif e.get("user_input"):
                    detail = e["user_input"][:50]
                table.add_row(
                    e.get("timestamp", "")[:19],
                    e.get("event", ""),
                    detail,
                )
            console.print(table)

    elif command == "/registry":
        from app.tool_registry import get_registry
        registry = get_registry()
        console.print(registry.summary())

    elif command == "/tasks":
        console.print(state.task_manager.format_tasks())

    elif command == "/todos":
        from rich.panel import Panel
        if state.todo_list is None or state.todo_list.is_empty:
            console.print("[dim]No active todos. The agent creates them via the todo_write tool.[/]")
        else:
            console.print(Panel(
                state.todo_list.render_for_display(),
                title="TodoWrite", border_style="cyan",
            ))

    elif command == "/task":
        if not arg:
            console.print("[dim]Usage: /task <description>[/]")
        else:
            t = state.task_manager.create(subject=arg.strip())
            console.print(f"[green]Task #{t.id} created:[/] {t.subject}")

    elif command == "/done":
        if not arg:
            console.print("[dim]Usage: /done <task_id>[/]")
        else:
            try:
                tid = int(arg.strip())
            except ValueError:
                console.print("[red]Task ID must be a number[/]")
                return "ok"
            t = state.task_manager.update_status(tid, _get_tasks().TaskStatus.COMPLETED)
            if t:
                console.print(f"[green]Task #{tid} completed:[/] {t.subject}")
            else:
                console.print(f"[red]Task #{tid} not found[/]")

    elif command == "/taskinfo":
        if not arg:
            console.print("[dim]Usage: /taskinfo <task_id>[/]")
        else:
            try:
                tid = int(arg.strip())
            except ValueError:
                console.print("[red]Task ID must be a number[/]")
                return "ok"
            info = state.task_manager.format_task_detail(tid)
            console.print(Panel(info, title=f"Task #{tid}", border_style="cyan"))

    elif command == "/plan":
        if not arg:
            console.print("[dim]Usage: /plan <goal description>[/]")
            console.print("[dim]Ye will generate a step-by-step plan, then ask you to approve before executing.[/]")
        else:
            await _cmd_plan(state, arg.strip(), provider)

    elif command == "/prune":
        import app.memory as mem
        report = mem.prune_memories(dry_run=(arg.strip() == "dry"))
        console.print(Panel(report, title="Memory Pruning", border_style="yellow"))
        if arg.strip() != "dry":
            console.print("[dim]Use /prune dry to preview without changes.[/]")

    elif command == "/eval":
        from app.eval import get_eval_summary
        summary = get_eval_summary()
        console.print(Panel(summary, title="Evaluation Metrics", border_style="green"))

    elif command == "/failures":
        console.print("[dim]Failure log is tracked per conversation turn.[/]")
        console.print("[dim]Use /trace to see detailed execution events including failures.[/]")

    elif command == "/learn":
        if not arg:
            console.print("[dim]Usage: /learn <rule>[/]")
            console.print("[dim]Example: /learn 不要在 packages/ui 里装本该装在 apps/web 的包[/]")
            return "done"
        ye_md = Path.cwd() / "YE.md"
        if not ye_md.is_file():
            console.print("[dim]No YE.md found in current directory. Creating one.[/]")
            ye_md.write_text("# Project Rules\n\n## From mistakes learned\n\n", encoding="utf-8")
        content = ye_md.read_text(encoding="utf-8")
        if "From mistakes learned" not in content and "从错误中学到的" not in content:
            content += "\n\n## 从错误中学到的\n\n"
        marker = "从错误中学到的" if "从错误中学到的" in content else "From mistakes learned"
        idx = content.index(marker) + len(marker)
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        new_rule = f"\n- {arg} ({date_str})"
        content = content[:idx] + new_rule + content[idx:]
        ye_md.write_text(content, encoding="utf-8")
        console.print(f"[green]Rule saved to YE.md:[/] {arg}")
        return "done"

    elif command == "/review":
        await _cmd_review(state, provider)

    elif command == "/loop":
        if not arg:
            console.print("[dim]Usage: /loop <interval> <task>[/]")
            console.print("[dim]Example: /loop 5m check the test results[/]")
            console.print("[dim]Use /loop stop to cancel[/]")
        elif arg.strip() == "stop":
            if state.loop_task:
                state.loop_task.cancel()
            state.loop_task = None
            console.print("[dim]Loop stopped.[/]")
        else:
            await _cmd_loop(state, arg, provider)

    elif command == "/doctor":
        await _cmd_doctor(state, provider)

    elif command == "/permissions":
        await _cmd_permissions(state, provider, arg)

    elif command == "/soul":
        from app.soul import load_soul, save_soul
        if not arg:
            console.print(Panel(load_soul(), title="SOUL.md", border_style="magenta"))
        elif arg.startswith("save "):
            result = save_soul(arg[5:])
            console.print(f"[green]{result}[/]")
        else:
            console.print("[dim]Usage: /soul [save <text>][/]")

    elif command == "/cron":
        from app.cron import create_job, list_jobs, delete_job, toggle_job, format_jobs_table
        parts = (arg or "").split(None, 1)
        sub = parts[0] if parts else ""
        if sub == "create" and len(parts) > 1:
            # /cron create <schedule> | <prompt>
            rest = parts[1]
            sched_parts = rest.split("|", 1)
            if len(sched_parts) == 2:
                job = create_job(schedule=sched_parts[0].strip(), prompt=sched_parts[1].strip())
            else:
                job = create_job(schedule="daily", prompt=rest)
            console.print(f"[green]Created:[/] {job['id']} — {job['schedule']} — {job['prompt'][:60]}")
        elif sub == "delete" and len(parts) > 1:
            if delete_job(parts[1].strip()):
                console.print(f"[dim]Deleted job {parts[1].strip()}[/]")
            else:
                console.print(f"[red]Job not found[/]")
        elif sub == "toggle" and len(parts) > 1:
            job = toggle_job(parts[1].strip())
            if job:
                status = "enabled" if job["enabled"] else "disabled"
                console.print(f"[green]{job['id']} {status}[/]")
            else:
                console.print("[red]Job not found[/]")
        else:
            console.print(Panel(format_jobs_table(), title="Cron Jobs", border_style="cyan"))

    elif command == "/coremem":
        mem = _get_mem()
        if not arg or arg == "show":
            core = mem.core_memory_load()
            user = mem.user_profile_load()
            console.print(Panel(core or "(empty)", title="Core Memory", border_style="yellow"))
            console.print(Panel(user or "(empty)", title="User Profile", border_style="green"))
        elif arg.startswith("add "):
            result = mem.core_memory_append(arg[4:])
            console.print(f"[green]{result}[/]")
        elif arg.startswith("remove "):
            result = mem.core_memory_remove(arg[7:])
            console.print(f"[dim]{result}[/]")
        elif arg == "clear":
            mem.core_memory_save("")
            console.print("[dim]Core memory cleared.[/]")
        else:
            console.print("[dim]Usage: /coremem [show|add <text>|remove <keyword>|clear][/]")

    elif command == "/ss":
        if not arg:
            console.print("[dim]Usage: /ss <search query>[/]")
        else:
            from app.session_search import format_search_results, search_sessions
            results = search_sessions(arg)
            console.print(Panel(format_search_results(results), title=f"Session Search: {arg}", border_style="cyan"))

    elif command == "/worktree":
        if not arg:
            result = _get_worktree().list_worktrees(state.cwd)
            console.print(Panel(result, title="Worktrees", border_style="cyan"))
        elif arg.strip() == "done":
            name = state.worktree_name
            if not name:
                console.print("[dim]Not in a worktree.[/]")
            else:
                result = _get_worktree().remove_worktree(name, state.cwd)
                console.print(f"[dim]{result}[/]")
                state.worktree_name = ""
        else:
            name = arg.strip().replace(" ", "-")
            wt_path, branch = _get_worktree().create_worktree(name, state.cwd)
            if not wt_path:
                console.print(f"[red]{branch}[/]")
            else:
                state.worktree_name = name
                os.chdir(wt_path)
                state.cwd = wt_path
                console.print(f"[green]Created worktree:[/] {name} ({branch})")
                console.print(f"[dim]Working dir changed to {wt_path}[/]")

    elif command == "/skills":
        from rich.panel import Panel
        from app.skills import discover_skills
        skills = discover_skills(state.cwd)
        if not skills:
            console.print("[dim]No skills installed. Add one at .ye/skills/<name>/SKILL.md or ~/.ye/skills/<name>/SKILL.md[/]")
        else:
            lines = []
            for sk in sorted(skills.values(), key=lambda s: s.name):
                tag = "[project]" if sk.source == "project" else "[user]"
                trig = f" — triggers: {sk.trigger_summary}" if sk.triggers else ""
                lines.append(f"  /{sk.name} {tag} — {sk.description}{trig}")
            console.print(Panel("\n".join(lines), title="Skills", border_style="magenta"))
            console.print("[dim]Type /<name> to invoke a skill.[/]")

    elif command == "/mcp":
        from rich.panel import Panel
        if _mcp_session is None or not _mcp_session.is_connected:
            console.print("[dim]No MCP servers connected. Configure them in ~/.ye/mcp_servers.json[/]")
        else:
            lines = [f"  Servers: {len(_mcp_session._connections)}   Tools: {len(_mcp_session.tools)}", ""]
            for ns_name, t in sorted(_mcp_session.tools.items()):
                lines.append(f"  {ns_name} — {t.description[:60]}")
            console.print(Panel("\n".join(lines), title="MCP", border_style="cyan"))

    elif command.startswith("/") and not command.startswith("//"):
        # Dynamic skill command: /<skill-name> [args] → inject skill body.
        from app.skills import discover_skills, load_skill_body
        skill_name = command[1:].split()[0] if " " in command else command[1:]
        skills = discover_skills(state.cwd)
        body = load_skill_body(skills, skill_name)
        if body is not None:
            console.print(f"[magenta]\\_ skill: {skill_name}[/]")
            # Inject the skill body as a user message so the agent follows it.
            extra = f" {arg}" if arg else ""
            state.messages.append(ChatMessage(
                role="user",
                content=f"[Skill: {skill_name}]\n{body}{extra}",
            ))
            return "skill"  # signal the REPL to run the loop on this
        console.print(f"[dim]Unknown command:[/] {command}. Type /help for available commands.")

    else:
        console.print(f"[dim]Unknown command:[/] {command}. Type /help for available commands.")

    return "ok"


async def _cmd_plan(state: SessionState, goal: str, provider: ZhipuProvider) -> None:
    """Generate a declarative execution plan, let user approve, then execute."""
    from rich.panel import Panel
    from app.orchestrator import Orchestrator

    if provider is None:
        provider = _get_provider()

    orchestrator = Orchestrator(provider, model=state.model)

    # Step 1: Generate plan
    console.print("[dim]Generating execution plan...[/]")
    plan = await orchestrator.generate_plan(goal)

    if not plan.steps:
        console.print("[dim]Could not generate a plan. Try describing your goal more specifically.[/]")
        return

    # Step 2: Validate
    issues = orchestrator.validate_plan(plan)
    if issues:
        console.print("[yellow]Plan validation issues:[/]")
        for issue in issues:
            console.print(f"  [yellow]![/] {issue}")

    # Step 3: Show plan for approval
    console.print(Panel(plan.summary(), title="Execution Plan", border_style="cyan"))
    console.print("")
    console.print("[dim]Options: y = execute, e = edit step agent, n = cancel[/]")

    try:
        approval = input("  Approve plan? [y/e/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Plan cancelled.[/]")
        return

    if approval == "n" or not approval:
        console.print("[dim]Plan cancelled.[/]")
        return

    if approval == "e":
        console.print("[dim]Editing not yet implemented. Executing as-is.[/]")

    # Step 4: Execute plan with progress display
    console.print("[dim]Executing plan...[/]")

    def on_step_start(step):
        console.print(f"  [cyan]→[/] Step {step.step}: [{step.agent}] {step.intent}")

    def on_step_end(step):
        if step.status.value == "completed":
            console.print(f"  [green]v[/] Step {step.step}: done ({step.duration_ms:.0f}ms)")
        else:
            console.print(f"  [red]x[/] Step {step.step}: {step.error}")

    plan = await orchestrator.execute_plan(
        plan,
        cwd=str(state.cwd),
        on_step_start=on_step_start,
        on_step_end=on_step_end,
    )

    # Step 5: Show final result
    console.print("")
    if plan.status == "completed":
        console.print(Panel(
            "\n\n".join(
                f"[bold]Step {s.step} ({s.agent}):[/] {s.output[:300]}"
                for s in plan.steps if s.output
            ),
            title="Plan Result",
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"Plan {plan.status}. Check failed step for details.",
            title="Plan Status",
            border_style="red",
        ))


async def _cmd_review(state: SessionState, provider: ZhipuProvider) -> None:
    from rich.panel import Panel
    try:
        result = subprocess.run(
            ["git", "diff", "--staged"],
            capture_output=True, text=True, cwd=str(state.cwd), timeout=10,
        )
        diff = result.stdout.strip()
    except Exception as e:
        console.print(f"[red]Error getting diff:[/] {e}")
        return

    if not diff:
        console.print("[dim]No staged changes to review. Stage files with git add first.[/]")
        return

    console.print("[dim]Running code review...[/]")
    from app.agents import spawn_agent

    review_prompt = (
        f"Review the following staged git diff and provide feedback.\n"
        f"Focus on: bugs, security issues, code style, performance, and suggestions.\n\n"
        f"```\n{diff[:8000]}\n```"
    )
    review = await spawn_agent(review_prompt, provider, model=state.model, agent_type="explore", cwd=str(state.cwd))
    console.print(Panel(review, title="Code Review", border_style="yellow"))


def _parse_interval(s: str) -> int:
    """Parse interval string like '5m', '30s', '1h' to seconds."""
    s = s.strip().lower()
    try:
        if s.endswith("h"):
            val = int(s[:-1]) * 3600
        elif s.endswith("m"):
            val = int(s[:-1]) * 60
        elif s.endswith("s"):
            val = int(s[:-1])
        else:
            val = int(s) * 60
    except ValueError:
        return -1
    return val if val > 0 else -1


async def _cmd_loop(state: SessionState, arg: str, provider: ZhipuProvider) -> None:
    from rich.panel import Panel
    parts = arg.strip().split(maxsplit=1)
    if len(parts) < 2:
        console.print("[dim]Usage: /loop <interval> <task>[/]")
        return

    interval = _parse_interval(parts[0])
    if interval <= 0:
        console.print(f"[red]Invalid interval:[/] {parts[0]}. Use 5m, 30s, 1h, etc.")
        return
    task_text = parts[1]

    if state.loop_task:
        state.loop_task.cancel()

    async def _run_loop():
        while True:
            console.print(f"\n[dim]--- Loop: running '{task_text}' ---[/]")
            try:
                from app.agents import spawn_agent
                result = await spawn_agent(task_text, provider, model=state.model, cwd=str(state.cwd))
                console.print(Panel(result[:1000], title="Loop Result", border_style="cyan"))
            except Exception as e:
                console.print(f"[red]Loop error:[/] {e}")
            console.print(f"[dim]--- Next run in {interval}s ---[/]")
            await asyncio.sleep(interval)

    state.loop_task = asyncio.create_task(_run_loop())
    console.print(f"[green]Loop started:[/] '{task_text}' every {parts[0]}")


async def _cmd_permissions(state: SessionState, provider: ZhipuProvider, arg: str = "") -> None:
    from rich.panel import Panel
    from rich.table import Table
    from app.permissions import list_permissions, set_permission, get_permission, _DEFAULTS, invalidate_cache

    parts = arg.strip().split(maxsplit=1)

    # No args: show current permissions
    if len(parts) <= 1:
        table = Table(title="Tool Permissions", show_header=True, header_style="bold cyan")
        table.add_column("Tool", style="white")
        table.add_column("Level", width=10)
        table.add_column("Description", style="dim")

        icons = {"auto": "[green]v auto[/]", "ask": "[yellow]? ask[/]", "deny": "[red]x deny[/]"}
        descs = {
            "auto": "自动允许，无需确认",
            "ask": "每次执行前询问",
            "deny": "禁止使用",
        }
        all_tools = sorted(set(_DEFAULTS.keys()))
        for tool in all_tools:
            level = get_permission(tool)
            table.add_row(tool, icons.get(level, level), descs.get(level, ""))
        console.print(table)
        console.print("\n[dim]用法: /permissions <tool> <auto|ask|deny>")
        console.print("[dim]例: /permissions write_file auto  — 写文件不再询问")
        console.print("[dim]例: /permissions run_command deny  — 禁止执行命令[/]")
        return

    # Set permission
    tool_name = parts[0] if len(parts) > 0 else ""
    level = parts[1] if len(parts) > 1 else ""

    if not tool_name or not level:
        console.print("[red]用法: /permissions <tool> <auto|ask|deny>[/]")
        return

    if level not in ("auto", "ask", "deny"):
        console.print(f"[red]无效级别: {level}，请用 auto / ask / deny[/]")
        return

    if tool_name not in _DEFAULTS and tool_name not in {"read_file", "write_file", "edit_file", "run_command", "grep", "glob", "list_files", "search_codebase", "web_search", "web_fetch", "spawn_agent"}:
        console.print(f"[yellow]⚠ 未知工具: {tool_name}")
        console.print(f"[dim]已知工具: {', '.join(sorted(_DEFAULTS.keys()))}[/]")

    set_permission(tool_name, level)
    invalidate_cache()

    icons = {"auto": "[green]v auto[/]", "ask": "[yellow]? ask[/]", "deny": "[red]x deny[/]"}
    console.print(f"{icons[level]} {tool_name} 已设为 [bold]{level}[/]")
    console.print(f"[dim]配置文件: ~/.ye/permissions.json[/]")


async def _cmd_doctor(state: SessionState, provider: ZhipuProvider) -> None:
    from rich.panel import Panel
    from app.config import settings as settings

    checks: list[str] = []
    warnings: list[str] = []

    # --- Basic ---
    import platform
    checks.append(f"[cyan]Python:[/]         {platform.python_version()}")
    checks.append(f"[cyan]Model:[/]          {state.model}")

    key_set = bool(settings.ZHIPU_API_KEY)
    key_status = "[green]set[/]" if key_set else "[red]not set[/]"
    checks.append(f"[cyan]API Key:[/]        {key_status}")

    p = provider or _get_provider()
    valid = await p.validate_api_key()
    api_status = "[green]connected[/]" if valid else "[red]connection failed[/]"
    checks.append(f"[cyan]API:[/]            {api_status}")

    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=5,
        )
        checks.append(f"[cyan]Git:[/]            {result.stdout.strip()}")
    except Exception:
        checks.append("[cyan]Git:[/]            [red]not found[/]")

    checks.append(f"[cyan]Working Dir:[/]    {state.cwd}")

    # --- Harness: Memory ---
    mem_ctx = _get_mem().get_context(max_chars=100)
    mem_status = "has memories" if mem_ctx else "empty"
    checks.append(f"[cyan]Memory:[/]         {mem_status}")

    # --- Harness: Tool Registry ---
    from app.tool_registry import get_registry
    registry = get_registry()
    tool_count = len(registry._tools)
    checks.append(f"[cyan]Tool Registry:[/]  {tool_count} tools registered")

    # Check if any tools are missing risk levels
    no_risk = [name for name, spec in registry._tools.items() if spec.risk_level.value == "medium" and not spec.audit]
    if no_risk:
        warnings.append(f"Tools without audit: {', '.join(no_risk)}")

    # --- Harness: Sessions ---
    import app.sessions as sessions
    saved_sessions = sessions.list_sessions(limit=1)
    session_status = f"{len(sessions.list_sessions(limit=100))} saved" if saved_sessions else "no saved sessions"
    checks.append(f"[cyan]Sessions:[/]       {session_status}")

    # --- Harness: Traces ---
    from pathlib import Path as _P
    trace_dir = _P.home() / ".ye" / "traces"
    trace_count = len(list(trace_dir.glob("*.jsonl"))) if trace_dir.is_dir() else 0
    checks.append(f"[cyan]Traces:[/]         {trace_count} day(s) logged")

    # --- Harness: Budget ---
    from app.budget import BudgetConfig
    budget_cfg = BudgetConfig()
    checks.append(
        f"[cyan]Budget:[/]          {budget_cfg.max_total_tokens:,} tokens, "
        f"{budget_cfg.max_tool_calls} tool calls, {budget_cfg.max_duration_seconds}s timeout"
    )

    # --- Harness: Eval ---
    from app.eval import get_eval_summary
    metrics_file = _P.home() / ".ye" / "metrics.json"
    eval_status = "has metrics" if metrics_file.is_file() else "no metrics yet"
    checks.append(f"[cyan]Eval:[/]           {eval_status}")

    # --- Disk ---
    try:
        usage = shutil.disk_usage(str(state.cwd))
        free_gb = usage.free / (1024**3)
        checks.append(f"[cyan]Disk Free:[/]      {free_gb:.1f} GB")
        if free_gb < 1:
            warnings.append("Low disk space!")
    except Exception:
        pass

    # --- Summary ---
    border = "green"
    if warnings:
        border = "yellow"
        checks.append("")
        checks.append("[yellow]Warnings:[/]")
        for w in warnings:
            checks.append(f"  [yellow]![/] {w}")

    console.print(Panel("\n".join(checks), title="Health Check", border_style=border))


if __name__ == "__main__":
    main()
