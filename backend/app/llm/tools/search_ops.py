"""Search tools: grep, glob, list_files, search_codebase."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from app.llm.tools._common import should_skip, SKIP_DIRS


TOOLS = []


async def grep(pattern: str, path: str = ".", file_pattern: str = "*", max_results: int = 100) -> str:
    root = Path(path).resolve()
    if not root.exists():
        return f"Error: Path not found: {path}"
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    # Try rg first (much faster)
    try:
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
    matches: list[str] = []
    files_to_search = root.rglob(file_pattern) if file_pattern != "*" else root.rglob("*")
    for fp in files_to_search:
        if not fp.is_file() or should_skip(fp) or fp.stat().st_size > 1_000_000:
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
    return f"Found {len(matches)} match(es):\n" + "\n".join(matches)


TOOLS.append({
    "name": "grep",
    "description": "Search file contents with regex. Returns matching lines with line numbers.",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "Directory to search in (default .)", "default": "."},
            "file_pattern": {"type": "string", "description": "File glob filter (default *)", "default": "*"},
            "max_results": {"type": "integer", "description": "Maximum matches (default 100)", "default": 100},
        },
        "required": ["pattern"],
    },
    "handler": grep,
    "risk_level": "low",
    "allowed_agents": ["explore", "general", "plan", "review", "code"],
})


async def glob(pattern: str, path: str = ".") -> str:
    root = Path(path).resolve()
    if not root.exists():
        return f"Error: Path not found: {path}"
    try:
        all_files = root.rglob(pattern)
    except Exception as e:
        return f"Error: Invalid glob pattern: {e}"
    results = []
    for f in all_files:
        if should_skip(f):
            continue
        results.append(str(f.relative_to(root)))
        if len(results) >= 200:
            break
    if not results:
        return "No files matched the pattern."
    return "\n".join(sorted(results))


TOOLS.append({
    "name": "glob",
    "description": "Find files by glob pattern (e.g. **/*.py).",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern (e.g. **/*.py)"},
            "path": {"type": "string", "description": "Directory to search in (default .)", "default": "."},
        },
        "required": ["pattern"],
    },
    "handler": glob,
    "risk_level": "low",
    "allowed_agents": ["explore", "general", "plan", "review", "code"],
})


async def list_files(path: str = ".") -> str:
    p = Path(path).resolve()
    if not p.exists():
        return f"Error: Path not found: {path}"
    # If a file was given instead of a directory, show the file's info and list its parent
    if p.is_file():
        parent = p.parent
        size = p.stat().st_size
        entries = [f"FILE {p.name} ({size} bytes)  ← you passed a file, showing parent directory:"]
        for item in sorted(parent.iterdir()):
            kind = "DIR " if item.is_dir() else "FILE"
            s = item.stat().st_size if item.is_file() else 0
            marker = " ←" if item.name == p.name else ""
            entries.append(f"  {kind} {item.name} ({s} bytes){marker}")
            if len(entries) >= 500:
                entries.append("  ... and more (showing first 500)")
                break
        return "\n".join(entries)
    entries = []
    for item in sorted(p.iterdir()):
        kind = "DIR " if item.is_dir() else "FILE"
        size = item.stat().st_size if item.is_file() else 0
        entries.append(f"{kind} {item.name} ({size} bytes)")
        if len(entries) >= 500:
            entries.append("... and more (showing first 500)")
            break
    return "\n".join(entries) or "(empty directory)"


TOOLS.append({
    "name": "list_files",
    "description": "List files in a directory",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path (default: project root)", "default": "."},
        },
    },
    "handler": list_files,
    "risk_level": "low",
    "allowed_agents": ["explore", "general", "plan", "review", "code"],
})


async def search_codebase(query: str, n_results: int = 5) -> str:
    try:
        from app.indexer.vector_store import search_code
    except ImportError:
        return (
            "Semantic search is not available (chromadb not installed). "
            "Use `grep` or `glob` instead for code search. "
            "To enable: pip install chromadb"
        )
    results = search_code(query, n_results=n_results)
    if not results:
        return "No results found. The project may need to be indexed first."
    output_lines = ["Found relevant code snippets:\n"]
    for r in results:
        meta = r.get("metadata", {})
        output_lines.append(
            f"--- {meta.get('file_path', 'unknown')} "
            f"(L{meta.get('start_line', '?')}-{meta.get('end_line', '?')}) "
            f"[{meta.get('chunk_type', '')}: {meta.get('name', '')}] ---"
        )
        output_lines.append(r.get("content", ""))
        output_lines.append("")
    return "\n".join(output_lines)


TOOLS.append({
    "name": "search_codebase",
    "description": "Search the codebase using semantic similarity. Returns relevant code snippets.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural language search query"},
            "n_results": {"type": "integer", "description": "Number of results (default 5)", "default": 5},
        },
        "required": ["query"],
    },
    "handler": search_codebase,
    "risk_level": "low",
    "allowed_agents": ["explore", "general", "plan", "review", "code"],
})


# Key file patterns to auto-detect project type and summarize
_KEY_FILES = [
    "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "Makefile",
    "Dockerfile", "docker-compose.yml", ".env", ".env.example",
    "README.md", "CLAUDE.md", "YE.md",
]
_SUMMARY_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".html", ".css", ".scss", ".yaml", ".yml", ".toml", ".json",
    ".md", ".sql", ".sh", ".bash", ".zsh",
}


async def project_overview(path: str = ".") -> str:
    """One-shot project overview: directory tree + key file summaries.
import logging


logger = logging.getLogger(__name__)
    Replaces 10-15 individual list_files + read_file calls during exploration.
    """
    root = Path(path).resolve()
    if not root.is_dir():
        return f"Error: '{path}' is not a directory."

    lines = [f"Project: {root.name}\n"]

    # 1. Directory tree (max 3 levels, skip hidden/build dirs)
    lines.append("## Directory Structure")
    _tree_lines = []
    for item in sorted(root.iterdir()):
        if item.name.startswith(".") and item.name not in {".env", ".env.example"}:
            continue
        if item.name in SKIP_DIRS:
            continue
        if item.is_dir():
            count = 0
            try:
                for _ in item.iterdir():
                    count += 1
            except PermissionError:
                pass
            _tree_lines.append(f"  {item.name}/ ({count} items)")
        else:
            size = item.stat().st_size
            _tree_lines.append(f"  {item.name} ({size:,} bytes)")
    lines.append("\n".join(_tree_lines[:50]))

    # 2. Key file contents (project config)
    lines.append("\n## Key Files")
    for kf in _KEY_FILES:
        fp = root / kf
        if fp.is_file() and not should_skip(fp):
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                if len(content) > 2000:
                    content = content[:2000] + "\n... [truncated]"
                lines.append(f"\n### {kf}\n```\n{content}\n```")
            except Exception:
                logger.debug("suppressed", exc_info=True)
                pass

    # 3. Source file summary (count by type, key entry points)
    lines.append("\n## Source Summary")
    ext_counts: dict[str, int] = {}
    entry_points: list[str] = []
    for fp in root.rglob("*"):
        if should_skip(fp) or not fp.is_file():
            continue
        ext = fp.suffix.lower()
        if ext in _SUMMARY_EXTENSIONS:
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
        name = fp.name.lower()
        if name in {"main.py", "app.py", "__init__.py", "main.go", "main.rs", "index.ts", "index.js"}:
            rel = fp.relative_to(root)
            entry_points.append(str(rel))

    if ext_counts:
        parts = [f"{ext}: {count}" for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1])]
        lines.append(f"Files by type: {', '.join(parts)}")
    if entry_points:
        lines.append(f"Entry points: {', '.join(entry_points[:10])}")

    # 4. First 5 lines of each entry point for quick context
    if entry_points:
        lines.append("\n## Entry Point Previews")
        for ep in entry_points[:5]:
            fp = root / ep
            try:
                head = fp.read_text(encoding="utf-8", errors="replace").splitlines()[:15]
                lines.append(f"\n### {ep}\n" + "\n".join(head))
            except Exception:
                logger.debug("suppressed", exc_info=True)
                pass

    return "\n".join(lines)


TOOLS.append({
    "name": "project_overview",
    "description": (
        "Get a one-shot project overview: directory tree, key config files, "
        "source file summary, and entry point previews. "
        "PREFER this over multiple list_files + read_file calls when first exploring a project."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Project root directory (default .)", "default": "."},
        },
    },
    "handler": project_overview,
    "risk_level": "low",
    "allowed_agents": ["explore", "general", "plan", "review", "code"],
})
