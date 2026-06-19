import json
import re
from pathlib import Path

from app.llm.tool_executor import ToolExecutor
from app.llm.zhipu_provider import ZhipuProvider
from app.sandbox.runner import run_command


def _get_cwd() -> Path:
    """Get current working directory (always fresh, not cached)."""
    return Path.cwd().resolve()


def _sandbox_path(path: str) -> Path:
    """Resolve path and enforce it stays within the project directory."""
    cwd = _get_cwd()
    p = (cwd / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        p.relative_to(cwd)
    except ValueError:
        raise PermissionError(f"Path escapes project directory: {path}")
    return p

# --- Web dependencies (lazy import, connection reuse) --'

_shared_http_client = None


def _get_http_client():
    """Lazy-init shared raw_http client with connection reuse."""
    global _shared_http_client
    if _shared_http_client is None:
        from app.llm.raw_http import AsyncClient
        _shared_http_client = AsyncClient(timeout=15.0, connect_timeout=5.0)
    return _shared_http_client


async def cleanup_http_client():
    """Close the shared HTTP client. Call on shutdown."""
    global _shared_http_client
    if _shared_http_client is not None:
        await _shared_http_client.aclose()
        _shared_http_client = None


def _import_ddgs():
    try:
        from duckduckgo_search import DDGS
        return DDGS()
    except ImportError:
        return None

_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", ".venv2",
    "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
    ".eggs", ".hg", ".svn", "target", ".gradle", ".idea",
    ".vscode", ".ruff_cache",
})


def _should_skip(path: Path) -> bool:
    parts = path.parts
    skip = _SKIP_DIRS
    for part in parts:
        if part in skip or part.endswith(".egg-info"):
            return True
    return False


async def _read_file_handler(path: str, offset: int = 0, limit: int = 2000) -> str:
    p = _sandbox_path(path)
    if not p.is_file():
        return f"Error: File not found: {path}"
    try:
        size = p.stat().st_size
        if size > 2_000_000:
            return f"Error: File too large ({size:,} bytes). Use offset/limit or grep to read parts."
        # For offset reads, only load needed lines via binary seek
        if offset > 0:
            lines = []
            total = 0
            with open(p, "rb") as f:
                for i, raw in enumerate(f):
                    total = i + 1
                    if i >= offset + limit:
                        continue
                    if i >= offset:
                        lines.append(raw.decode("utf-8", errors="replace").rstrip("\n\r"))
            if not lines:
                return f"Offset {offset} exceeds file length ({total} lines)."
            header = f"[lines {offset + 1}-{min(offset + limit, total)} of {total}]\n"
            return header + "\n".join(lines)
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        total = len(lines)
        if limit < total:
            header = f"[lines 1-{limit} of {total}]\n"
            return header + "\n".join(lines[:limit])
        return text
    except Exception as e:
        return f"Error reading file: {e}"


async def _write_file_handler(path: str, content: str) -> str:
    p = _sandbox_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Successfully wrote {len(content)} bytes to {path}"


async def _edit_file_handler(
    file_path: str, old_string: str, new_string: str, replace_all: bool = False,
) -> str:
    p = _sandbox_path(file_path)
    if not p.is_file():
        return f"Error: File not found: {file_path}"
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    count = content.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {file_path}"
    if count > 1 and not replace_all:
        return (
            f"Error: old_string found {count} times in {file_path}. "
            "Set replace_all=true to replace all occurrences."
        )

    if replace_all:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, 1)
    p.write_text(new_content, encoding="utf-8")
    lines_changed = new_string.count("\n") + 1
    return f"Replaced {count} occurrence(s) in {file_path} (~{lines_changed} lines)"


async def _grep_handler(
    pattern: str, path: str = ".", file_pattern: str = "*", max_results: int = 100,
) -> str:
    root = Path(path).resolve()
    if not root.exists():
        return f"Error: Path not found: {path}"
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    matches: list[str] = []
    # Try rg first (much faster), fall back to Python
    try:
        import asyncio
        cmd = ["rg", "--no-heading", "-n", "--max-count", str(max_results)]
        if file_pattern != "*":
            cmd.extend(["--glob", file_pattern])
        cmd.extend([pattern, str(root)])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0 and stdout:
            lines = stdout.decode("utf-8", errors="replace").strip().splitlines()[:max_results]
            return f"Found {len(lines)} match(es):\n" + "\n".join(lines)
    except (FileNotFoundError, asyncio.TimeoutError):
        pass

    # Fallback: Python-based search
    files_to_search = (
        root.rglob(file_pattern) if file_pattern != "*" else root.rglob("*")
    )
    for fp in files_to_search:
        if not fp.is_file():
            continue
        if _should_skip(fp):
            continue
        if fp.stat().st_size > 1_000_000:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel = fp.relative_to(root)
        for i, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                matches.append(f"{rel}:{i}: {line.rstrip()}")
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break

    if not matches:
        return "No matches found."
    header = f"Found {len(matches)} match(es):\n"
    return header + "\n".join(matches)


async def _glob_handler(pattern: str, path: str = ".") -> str:
    root = Path(path).resolve()
    if not root.exists():
        return f"Error: Path not found: {path}"
    try:
        all_files = root.rglob(pattern)
    except Exception as e:
        return f"Error: Invalid glob pattern: {e}"

    results = []
    skip = _SKIP_DIRS
    for f in all_files:
        if _should_skip(f):
            continue
        results.append(str(f.relative_to(root)))
        if len(results) >= 200:
            break
    if not results:
        return "No files matched the pattern."
    return "\n".join(sorted(results))


async def _run_command_handler(command: str, timeout: int = 60) -> str:
    result = await run_command(command, timeout=timeout)
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    if result.exit_code != 0:
        output += f"\n[exit code: {result.exit_code}]"
    return output or "(no output)"


async def _list_files_handler(path: str = ".") -> str:
    p = Path(path).resolve()
    if not p.is_dir():
        return f"Error: Not a directory: {path}"
    entries = []
    for item in sorted(p.iterdir()):
        kind = "DIR " if item.is_dir() else "FILE"
        size = item.stat().st_size if item.is_file() else 0
        entries.append(f"{kind} {item.name} ({size} bytes)")
        if len(entries) >= 500:
            entries.append(f"... and more (showing first 500)")
            break
    return "\n".join(entries) or "(empty directory)"


async def _web_search_handler(query: str, max_results: int = 5) -> str:
    ddgs = _import_ddgs()
    if ddgs is None:
        return "Error: duckduckgo-search not installed. Run: pip install duckduckgo-search"
    try:
        results = ddgs.text(query, max_results=max_results)
    except Exception as e:
        return f"Error searching: {e}"
    if not results:
        return "No search results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', 'No title')}")
        lines.append(f"   {r.get('href', '')}")
        lines.append(f"   {r.get('body', '')}")
        lines.append("")
    return "\n".join(lines)


async def _web_fetch_handler(url: str, max_length: int = 5000) -> str:
    client = _get_http_client()
    try:
        resp = await client.get(url)
        if resp.status >= 400:
            return f"Error: HTTP {resp.status} fetching {url}"
    except Exception as e:
        return f"Error fetching URL: {e}"
    content_type = resp.headers.get("content-type", "")
    raw = await resp.read()
    text = raw.decode("utf-8", errors="replace")
    if "html" in content_type:
        text = _strip_html(text)
    if len(text) > max_length:
        text = text[:max_length] + f"\n... (truncated, {len(text)} total chars)"
    return text


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_tool_executor(provider: ZhipuProvider) -> ToolExecutor:
    executor = ToolExecutor(provider)

    # --- File Operations ---

    executor.register(
        name="read_file",
        description="Read file contents. Use offset/limit for large files.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "offset": {"type": "integer", "description": "Starting line number (0-based)", "default": 0},
                "limit": {"type": "integer", "description": "Max lines to read", "default": 2000},
            },
            "required": ["path"],
        },
        handler=_read_file_handler,
        risk_level="low",
        allowed_agents=["explore", "general", "plan", "review", "code"],
        audit=True,
    )

    executor.register(
        name="write_file",
        description="Write content to a file",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path", "content"],
        },
        handler=_write_file_handler,
        risk_level="high",
        allowed_agents=["general", "code"],
        requires_approval=True,
        audit=True,
    )

    executor.register(
        name="edit_file",
        description="Replace exact text in a file. old_string must be unique unless replace_all=true.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to edit"},
                "old_string": {"type": "string", "description": "Exact text to find and replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)", "default": False},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
        handler=_edit_file_handler,
        risk_level="high",
        allowed_agents=["general", "code"],
        requires_approval=True,
        audit=True,
    )

    # --- Search Operations ---

    executor.register(
        name="list_files",
        description="List files in a directory",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path (default: project root)",
                    "default": ".",
                },
            },
        },
        handler=_list_files_handler,
        risk_level="low",
        allowed_agents=["explore", "general", "plan", "review", "code"],
        audit=False,
    )

    executor.register(
        name="search_codebase",
        description="Search the codebase using semantic similarity. Returns relevant code snippets.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query describing what code to find",
                },
                "n_results": {
                    "type": "integer",
                    "description": "Number of results to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=_search_codebase_handler,
        risk_level="low",
        allowed_agents=["explore", "general", "plan", "review", "code"],
        audit=False,
    )

    executor.register(
        name="grep",
        description="Search file contents with regex. Returns matching lines with line numbers.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Directory to search in (default .)", "default": "."},
                "file_pattern": {"type": "string", "description": "File glob filter (default *)", "default": "*"},
                "max_results": {"type": "integer", "description": "Maximum matches (default 100)", "default": 100},
            },
            "required": ["pattern"],
        },
        handler=_grep_handler,
        risk_level="low",
        allowed_agents=["explore", "general", "plan", "review", "code"],
        audit=False,
    )

    executor.register(
        name="glob",
        description="Find files by glob pattern (e.g. **/*.py).",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. **/*.py)"},
                "path": {"type": "string", "description": "Directory to search in (default .)", "default": "."},
            },
            "required": ["pattern"],
        },
        handler=_glob_handler,
        risk_level="low",
        allowed_agents=["explore", "general", "plan", "review", "code"],
        audit=False,
    )

    # --- System Operations ---

    executor.register(
        name="run_command",
        description="Execute a shell command",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 60},
            },
            "required": ["command"],
        },
        handler=_run_command_handler,
        risk_level="critical",
        allowed_agents=["general"],
        requires_approval=True,
        audit=True,
        timeout=60,
    )

    # --- Web Operations ---

    executor.register(
        name="web_search",
        description="Search the web. Returns titles, URLs, and snippets.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (default 5)", "default": 5},
            },
            "required": ["query"],
        },
        handler=_web_search_handler,
        risk_level="medium",
        allowed_agents=["explore", "general", "plan", "review"],
        audit=True,
        rate_limit=10,
    )

    executor.register(
        name="web_fetch",
        description="Fetch URL and return text content. Strips HTML.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_length": {"type": "integer", "description": "Max chars to return (default 5000)", "default": 5000},
            },
            "required": ["url"],
        },
        handler=_web_fetch_handler,
        risk_level="medium",
        allowed_agents=["explore", "general", "plan", "review"],
        audit=True,
        rate_limit=15,
    )

    # --- Agent Operations ---

    async def _spawn_agent_handler(task_description: str, agent_type: str = "general") -> str:
        from app.agents import spawn_agent
        import os
        return await spawn_agent(task_description, provider, agent_type=agent_type, cwd=os.getcwd())

    executor.register(
        name="spawn_agent",
        description="Spawn a sub-agent for complex multi-step tasks. Do NOT use for simple reads/searches.",
        parameters={
            "type": "object",
            "properties": {
                "task_description": {"type": "string", "description": "Task for the sub-agent"},
                "agent_type": {
                    "type": "string",
                    "description": "Agent role: explore (read-only research), general (full tools), plan (analyze & plan), review (code review), code (focused editing)",
                    "default": "general",
                    "enum": ["explore", "general", "plan", "review", "code"],
                },
            },
            "required": ["task_description"],
        },
        handler=_spawn_agent_handler,
        risk_level="high",
        allowed_agents=["general"],
        requires_approval=True,
        audit=True,
        timeout=120,
    )

    async def _spawn_agent_group_handler(tasks: str) -> str:
        from app.agents import spawn_agent_group, format_group_results
        import os
        task_list = json.loads(tasks)
        results = await spawn_agent_group(
            tasks=task_list, provider=provider, cwd=os.getcwd()
        )
        return format_group_results(results)

    executor.register(
        name="spawn_agent_group",
        description="Spawn MULTIPLE agents in PARALLEL. Each agent works independently. Use when a task can be split into independent subtasks (e.g., review 3 files, check multiple modules).",
        parameters={
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "List of subtasks. Each item: {\"task\": \"description\", \"type\": \"explore|general|plan|review|code\"}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "description": "Task description"},
                            "type": {
                                "type": "string",
                                "description": "Agent role (default: general)",
                                "default": "general",
                                "enum": ["explore", "general", "plan", "review", "code"],
                            },
                        },
                        "required": ["task"],
                    },
                },
            },
            "required": ["tasks"],
        },
        handler=_spawn_agent_group_handler,
        risk_level="high",
        allowed_agents=["general"],
        requires_approval=True,
        audit=True,
        timeout=180,
    )

    return executor


async def _search_codebase_handler(query: str, n_results: int = 5) -> str:
    from app.indexer.vector_store import search_code
    results = search_code(query, n_results=n_results)
    if not results:
        return "No results found. The project may need to be indexed first."
    output_lines = ["Found relevant code snippets:\n"]
    for r in results:
        meta = r.get("metadata", {})
        output_lines.append(f"--- {meta.get('file_path', 'unknown')} (L{meta.get('start_line', '?')}-{meta.get('end_line', '?')}) [{meta.get('chunk_type', '')}: {meta.get('name', '')}] ---")
        output_lines.append(r.get("content", ""))
        output_lines.append("")
    return "\n".join(output_lines)
