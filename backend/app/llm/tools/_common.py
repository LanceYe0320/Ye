"""Shared utilities for tool handlers."""
from __future__ import annotations

import contextvars
import re
from pathlib import Path

# Per-task working directory. When set (e.g. by spawn_agent), tools resolve
# their CWD from here instead of the process-global os.getcwd() — which lets
# concurrent agents operate in different directories without os.chdir racing.
_task_cwd: contextvars.ContextVar[Path | None] = contextvars.ContextVar("_task_cwd", default=None)


def set_task_cwd(path: Path | str | None) -> contextvars.Token:
    """Set the per-task working directory (for isolated agent execution).

    Returns a token to pass to reset_task_cwd(). When path is None, clears it
    (fall back to process CWD).
    """
    return _task_cwd.set(Path(path).resolve() if path is not None else None)


def reset_task_cwd(token: contextvars.Token) -> None:
    _task_cwd.reset(token)


def get_cwd() -> Path:
    """Return the effective working directory for the current task.

    Prefers a per-task override (set by spawn_agent) so concurrent agents don't
    race on os.chdir(); falls back to the process CWD otherwise.
    """
    override = _task_cwd.get()
    if override is not None:
        return override
    return Path.cwd().resolve()


def _find_repo_root(p: Path) -> Path:
    """Find the git repo root by walking up from p."""
    for parent in [p] + list(p.parents):
        if (parent / ".git").is_dir():
            return parent
    return p


def sandbox_path(path: str, write: bool = False) -> Path:
    """Resolve a path within the sandbox.

    Read operations: allowed within the git repo root.
    Write operations: restricted to CWD only.
    """
    cwd = get_cwd()
    p = (cwd / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()

    if write:
        # Writes restricted to CWD
        root = cwd
    else:
        # Reads allowed within git repo root
        root = _find_repo_root(cwd)

    try:
        p.relative_to(root)
    except ValueError:
        raise PermissionError(f"Path escapes project directory: {path}")
    return p


SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", ".venv2",
    "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
    ".eggs", ".hg", ".svn", "target", ".gradle", ".idea",
    ".vscode", ".ruff_cache",
})


def should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIRS or part.endswith(".egg-info"):
            return True
    return False


def strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Lazy HTTP client
_shared_http_client = None


def get_http_client():
    global _shared_http_client
    if _shared_http_client is None:
        from app.llm.raw_http import AsyncClient
        _shared_http_client = AsyncClient(timeout=15.0, connect_timeout=5.0)
    return _shared_http_client


async def cleanup_http_client():
    global _shared_http_client
    if _shared_http_client is not None:
        await _shared_http_client.aclose()
        _shared_http_client = None


def import_ddgs():
    try:
        from duckduckgo_search import DDGS
        return DDGS()
    except ImportError:
        return None


# ---- File Content Cache ----
# Avoids re-reading unchanged files across tool calls in the same session.
# Key: resolved file path, Value: (mtime_ns, content)
_file_cache: dict[Path, tuple[int, str]] = {}
_FILE_CACHE_MAX = 100


def file_cache_get(path: Path) -> str | None:
    """Return cached file content if file hasn't changed, else None."""
    if not path.is_file():
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    cached = _file_cache.get(path)
    if cached is None:
        return None
    cached_mtime, cached_content = cached
    if stat.st_mtime_ns == cached_mtime:
        return cached_content
    return None


def file_cache_put(path: Path, content: str) -> None:
    """Cache file content with current mtime."""
    if not path.is_file():
        return
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return
    if len(_file_cache) >= _FILE_CACHE_MAX:
        # Evict oldest entry (first key)
        _file_cache.pop(next(iter(_file_cache)))
    _file_cache[path] = (mtime, content)
