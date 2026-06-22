"""File operation tools: read_file, write_file, edit_file."""
from __future__ import annotations

from app.llm.tools._common import file_cache_get, file_cache_put, get_cwd, sandbox_path

TOOLS = []


def _invalidate_index_cache(file_path: str) -> None:
    """Best-effort: mark a changed file's vector-index mtime entry as stale.

    Called after write_file/edit_file so the next project re-index re-parses
    the file. Failures are swallowed — indexing is an optimization, not a
    correctness requirement for file tools.
    """
    try:
        from pathlib import Path
        from app.indexer.vector_store import invalidate_file_mtime
        cwd = get_cwd()
        # Resolve the project root by looking for a git marker.
        project_root = cwd
        for parent in [cwd, *cwd.parents]:
            if (parent / ".git").is_dir():
                project_root = parent
                break
        p = Path(file_path)
        if not p.is_absolute():
            p = cwd / p
        try:
            rel = str(p.resolve().relative_to(project_root.resolve())).replace("\\", "/")
        except ValueError:
            return  # file outside project root — nothing to invalidate
        invalidate_file_mtime(str(project_root), rel)
    except Exception:
        pass


async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    from pathlib import Path
    p = sandbox_path(path)
    if not p.is_file():
        if p.is_dir():
            return f"Error: '{path}' is a directory, not a file. Use list_files to see its contents."
        parent = p.parent
        if parent.is_dir():
            siblings = [f.name for f in parent.iterdir() if f.is_file()]
            similar = [s for s in siblings if p.stem in s or s in p.name][:5]
            hint = f" Similar files in {parent.name}/: {', '.join(similar)}" if similar else ""
            return f"Error: File not found: {path}.{hint}"
        return f"Error: File not found: {path}"
    try:
        size = p.stat().st_size
        if size > 2_000_000:
            return f"Error: File too large ({size:,} bytes). Use offset/limit or grep to read parts."
        if offset > 0:
            # Offset reads are not cached (partial reads)
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
        # Full-file read: check cache first
        cached = file_cache_get(p)
        if cached is not None:
            text = cached
        else:
            text = p.read_text(encoding="utf-8")
            file_cache_put(p, text)
        lines = text.splitlines()
        total = len(lines)
        if limit < total:
            header = f"[lines 1-{limit} of {total}]\n"
            return header + "\n".join(lines[:limit])
        return text
    except Exception as e:
        return f"Error reading file: {e}"


TOOLS.append({
    "name": "read_file",
    "description": "Read file contents. Use offset/limit for large files.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "offset": {"type": "integer", "description": "Starting line number (0-based)", "default": 0},
            "limit": {"type": "integer", "description": "Max lines to read", "default": 2000},
        },
        "required": ["path"],
    },
    "handler": read_file,
    "risk_level": "low",
    "allowed_agents": ["explore", "general", "plan", "review", "code"],
    "audit": True,
})


async def write_file(path: str = "", content: str = "") -> str:
    if not path:
        return (
            "Error: 'path' parameter is required. "
            "Call write_file with: {\"path\": \"filename.html\", \"content\": \"your content here\"}. "
            "Make sure to pass BOTH path and content as named parameters."
        )
    if not content:
        return (
            f"Error: 'content' parameter is empty. "
            f"You specified path='{path}' but provided no content to write. "
            f"For large files, use append_file to write in chunks instead."
        )
    p = sandbox_path(path, write=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _invalidate_index_cache(path)
    return f"Successfully wrote {len(content)} bytes to {path}"


TOOLS.append({
    "name": "write_file",
    "description": "Write content to a file. MUST provide both 'path' and 'content' parameters.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write (e.g. 'output.html')"},
            "content": {"type": "string", "description": "The complete file content to write"},
        },
        "required": ["path", "content"],
    },
    "handler": write_file,
    "risk_level": "high",
    "allowed_agents": ["general", "code"],
    "requires_approval": True,
    "audit": True,
})


async def edit_file(
    file_path: str, old_string: str, new_string: str, replace_all: bool = False,
) -> str:
    p = sandbox_path(file_path, write=True)
    if not p.is_file():
        return f"Error: File not found: {file_path}"
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    # Fuzzy multi-level replace (handles whitespace/indentation/escape
    # differences that LLMs frequently introduce). Falls back to exact match
    # on level 0. See app.llm.fuzzy_replace for the full chain.
    from app.llm.fuzzy_replace import fuzzy_replace

    had_crlf = "\r\n" in content
    norm_content = content.replace("\r\n", "\n")
    norm_old = old_string.replace("\r\n", "\n")
    norm_new = new_string.replace("\r\n", "\n")

    result = fuzzy_replace(norm_content, norm_old, norm_new, replace_all=replace_all)

    if result.content is None:
        # On failure, surface helpful context for self-correction.
        msg = f"Error editing {file_path}: {result.error}"
        if "not find" in (result.error or "").lower():
            old_lines = norm_old.splitlines()
            content_lines = norm_content.splitlines()
            hints = []
            if old_lines:
                first_line = old_lines[0].strip() if old_lines[0].strip() else (old_lines[1].strip() if len(old_lines) > 1 else "")
                for i, cl in enumerate(content_lines):
                    if first_line and first_line in cl:
                        start = max(0, i - 2)
                        end = min(len(content_lines), i + len(old_lines) + 2)
                        ctx = content_lines[start:end]
                        ctx_str = "\n".join(f"  {start + j + 1}: {line}" for j, line in enumerate(ctx))
                        hints.append(f"Line {start + 1}-{end}:\n{ctx_str}")
                        if len(hints) >= 2:
                            break
            if hints:
                msg += f"\nPossible match near:\n{hints[0]}"
            else:
                msg += "\nUse read_file to see the current content and copy the exact text."
        return msg

    new_content = result.content
    # Restore original line endings
    if had_crlf:
        new_content = new_content.replace("\n", "\r\n")
    p.write_text(new_content, encoding="utf-8")
    _invalidate_index_cache(file_path)
    level_name = ["exact", "line-trimmed", "block-anchor", "whitespace-norm",
                  "indent-flex", "escape-norm", "trimmed-boundary",
                  "context-aware", "multi-occurrence"][result.replacer_index or 0]
    lines_changed = max(norm_new.count("\n"), norm_old.count("\n")) + 1
    suffix = "" if level_name == "exact" else f" [fuzzy: {level_name}]"
    return f"Replaced text in {file_path} (~{lines_changed} lines){suffix}"


TOOLS.append({
    "name": "edit_file",
    "description": "Replace exact text in a file. old_string must be unique unless replace_all=true.",
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file to edit"},
            "old_string": {"type": "string", "description": "Exact text to find and replace"},
            "new_string": {"type": "string", "description": "Replacement text"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)", "default": False},
        },
        "required": ["file_path", "old_string", "new_string"],
    },
    "handler": edit_file,
    "risk_level": "high",
    "allowed_agents": ["general", "code"],
    "requires_approval": True,
    "audit": True,
})


async def append_file(path: str = "", content: str = "") -> str:
    """Append content to a file. Creates the file if it doesn't exist.

    For large files (HTML, CSS, etc.), call this multiple times with small chunks
    instead of using write_file with a huge content parameter.
    """
    if not path:
        return "Error: 'path' parameter is required."
    if not content:
        return "Error: 'content' parameter is empty. Pass the text chunk to append."
    p = sandbox_path(path, write=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    is_new = not p.exists()
    with open(p, "a", encoding="utf-8") as f:
        f.write(content)
    total_size = p.stat().st_size
    action = "Created" if is_new else "Appended to"
    return f"{action} {path}: +{len(content)} bytes (total: {total_size:,} bytes)"


TOOLS.append({
    "name": "append_file",
    "description": (
        "Append content to a file (creates if not exists). "
        "PREFERRED for writing large files like HTML/CSS/JS — "
        "call multiple times with small chunks instead of one huge write_file call. "
        "Example: append_file(path='page.html', content='<div>section 1</div>'), "
        "then append_file(path='page.html', content='<div>section 2</div>')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to append to"},
            "content": {"type": "string", "description": "Text chunk to append"},
        },
        "required": ["path", "content"],
    },
    "handler": append_file,
    "risk_level": "high",
    "allowed_agents": ["general", "code"],
    "requires_approval": True,
    "audit": True,
})
