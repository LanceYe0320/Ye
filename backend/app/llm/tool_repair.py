"""Tool-call repair — salvage malformed tool calls from Chinese LLMs (GLM/DeepSeek/Qwen).

Ported and adapted from opencode's ``experimental_repairToolCall`` (TypeScript) to
Python. The goal: when the model returns a tool call whose arguments fail to
execute, instead of giving up, try a series of deterministic fixes:

  1. ``snake_case`` parameter names → ``camelCase`` / correct names
     (e.g. ``file_path`` → ``file_path``; ``old_string`` stays; but wrong
     aliases like ``filepath`` → ``file_path`` are also corrected).
  2. Tool-name case / alias mismatch (``Edit`` → ``edit_file``,
     ``replace_in_file`` → ``edit_file``).
  3. ``edit_file`` parameter slot mix-ups (filePath / oldString swapped).
  4. ``glob`` absolute-path pattern normalization.

The public entry point is :func:`repair_tool_call`. It returns either a
repaired :class:`ToolCall` (best-effort) or ``None`` when no fix applies.

This is a **pure, dependency-free** module so it can be unit-tested in
isolation and called from the agentic loop with zero side effects.

Why a dedicated module?
  - Keeps the repair heuristics in one place, easy to extend per model quirk.
  - The agentic loop just needs one ``repair_tool_call(tc, known_tools)``
    call — no scattered ``if`` branches across the loop.
"""
from __future__ import annotations

import logging
import re
from dataclasses import replace as dc_replace
from typing import Any, Iterable

from app.llm.base_provider import ToolCall

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-tool canonical parameter names.
#
# Models trained on the Claude Code / opencode schema often use camelCase
# (filePath, oldString) while our tools use snake_case (file_path,
# old_string). Worse, different tools use different names for the same
# concept: edit_file uses ``file_path`` but write_file/read_file use
# ``path``. So we keep an explicit per-tool canonical set and resolve
# synonyms within that set.
# ---------------------------------------------------------------------------
_CANONICAL_PARAMS: dict[str, set[str]] = {
    "edit_file": {"file_path", "old_string", "new_string", "replace_all"},
    "write_file": {"path", "content"},
    "read_file": {"path", "offset", "limit"},
    "append_file": {"path", "content"},
    "glob": {"pattern", "path"},
    "grep": {"pattern", "path", "glob"},
    "run_command": {"command"},
    "list_files": {"path"},
    "search_codebase": {"query"},
}

# Synonym groups — any of these input forms may resolve to any of the listed
# canonical forms; the first one present in the tool's canonical set wins.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "filepath": ("file_path", "path", "filename"),
    "file_path": ("file_path", "path", "filename"),
    "filename": ("file_path", "path", "filename"),
    "path": ("path", "file_path"),
    "old": ("old_string",),
    "oldstring": ("old_string",),
    "old_string": ("old_string",),
    "new": ("new_string",),
    "newstring": ("new_string",),
    "new_string": ("new_string",),
    "replaceall": ("replace_all",),
    "replace_all": ("replace_all",),
    "content": ("content", "text", "contents"),
    "contents": ("content", "text"),
    "text": ("content", "text"),
    "command": ("command",),
    "cmd": ("command",),
    "pattern": ("pattern",),
    "glob": ("glob", "pattern"),
    "query": ("query",),
    "q": ("query",),
}

# Tool-name aliases → canonical name in our registry.
_TOOL_ALIASES: dict[str, str] = {
    # edit variants
    "edit": "edit_file",
    "replace": "edit_file",
    "replace_in_file": "edit_file",
    "str_replace": "edit_file",
    "str_replace_editor": "edit_file",
    "multiedit": "edit_file",
    "multi_edit": "edit_file",
    # write variants
    "write": "write_file",
    "create_file": "write_file",
    "new_file": "write_file",
    # read variants
    "read": "read_file",
    "view_file": "read_file",
    "cat": "read_file",
    # append
    "append": "append_file",
    # list
    "ls": "list_files",
    "list": "list_files",
    "list_directory": "list_files",
    # glob / grep
    "find": "glob",
    "search_files": "grep",
    "rg": "grep",
    # command
    "bash": "run_command",
    "shell": "run_command",
    "execute": "run_command",
}


def _camel_to_snake(name: str) -> str:
    """``filePath`` → ``file_path``. Idempotent on already-snake names."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _normalize_param_name(tool: str, key: str) -> str:
    """Map a possibly-wrong parameter key to the canonical one for ``tool``.

    Resolution order:
      1. If ``key`` is already a canonical param for ``tool``, return as-is.
      2. snake_case the key (``filePath`` → ``file_path``) and re-check.
      3. Look up the key in the synonym table and pick the first canonical
         variant that the tool actually accepts.
      4. Give up and return the snake_cased key (caller decides whether to
         keep it).
    """
    canonical = _CANONICAL_PARAMS.get(tool, set())
    if key in canonical:
        return key
    snake = _camel_to_snake(key)
    if snake in canonical:
        return snake
    # Synonym lookup (case-insensitive)
    candidates = _SYNONYMS.get(snake) or _SYNONYMS.get(key.lower())
    if candidates:
        for c in candidates:
            if c in canonical:
                return c
    return snake  # keep snake_cased form even if not canonical (preserves info)


def _looks_like_path(s: str) -> bool:
    """Heuristic: does this string look like a file path?"""
    if not s:
        return False
    return bool(re.search(r"[\\/]|\.[a-zA-Z]{1,5}$", s))


def repair_tool_call(
    tool_call: ToolCall,
    known_tool_names: Iterable[str],
) -> ToolCall | None:
    """Attempt to repair a failing tool call.

    Args:
        tool_call: The original (failing) tool call.
        known_tool_names: The set of tool names the executor actually knows.
            Used to decide whether a name alias is needed.

    Returns:
        A new :class:`ToolCall` with repaired name/arguments, or ``None`` if
        no repair could be applied (caller should fall back to returning the
        error to the model).
    """
    known = set(known_tool_names)
    name = tool_call.name
    args: dict[str, Any] = dict(tool_call.arguments)
    changed = False

    # --- Step 1: repair tool name (case + alias) ---
    repaired_name: str | None = None
    # Exact alias hit
    if name in _TOOL_ALIASES:
        candidate = _TOOL_ALIASES[name]
        if name not in known and candidate in known:
            repaired_name = candidate
    # Case-insensitive match against known tools
    if repaired_name is None and name not in known:
        low = name.lower()
        for k in known:
            if k.lower() == low:
                repaired_name = k
                break
        # Case-insensitive alias
        if repaired_name is None:
            for alias, canonical in _TOOL_ALIASES.items():
                if alias.lower() == low and canonical in known:
                    repaired_name = canonical
                    break
    if repaired_name is not None and repaired_name != name:
        logger.info("tool_repair: name %r -> %r", name, repaired_name)
        name = repaired_name
        changed = True

    # --- Step 2: repair parameter names (camelCase / wrong aliases) ---
    target_tool = name  # use repaired name for alias resolution
    new_args: dict[str, Any] = {}
    had_renamed = False
    for key, value in args.items():
        canon = _normalize_param_name(target_tool, key)
        if canon != key:
            had_renamed = True
        # Last-write-wins on duplicate canonical keys
        new_args[canon] = value
    if had_renamed:
        logger.info("tool_repair: renamed params for %r: %s", name, list(new_args.keys()))
        args = new_args
        changed = True

    # --- Step 3: edit_file-specific slot fixes ---
    # Only fire when parameters are obviously misplaced (missing file_path, or
    # file_path doesn't look like a path while another slot does). We do NOT
    # inject default values for otherwise-correct calls — the handler already
    # has defaults, and injecting them here would mark every call "repaired".
    if target_tool == "edit_file":
        fp = args.get("file_path")
        old = args.get("old_string")
        new = args.get("new_string")
        # Case A: file_path missing, but old_string looks like a path
        if not fp and old and new and _looks_like_path(str(old)) and not _looks_like_path(str(new)):
            logger.info("tool_repair: edit_file slot fix A (filePath from old_string)")
            args = {"file_path": str(old), "old_string": str(new), "new_string": "", "replace_all": False}
            changed = True
        # Case B: file_path present but doesn't look like a path, while
        # new_string/old_string does — params likely swapped.
        elif fp and not _looks_like_path(str(fp)) and old:
            candidate_path = str(new) if (new and _looks_like_path(str(new))) else (str(old) if _looks_like_path(str(old)) else None)
            if candidate_path:
                logger.info("tool_repair: edit_file slot fix B (param swap)")
                args = {"file_path": candidate_path, "old_string": str(fp), "new_string": str(old), "replace_all": False}
                changed = True

    # --- Step 4: glob absolute-path pattern normalization ---
    if target_tool == "glob" and isinstance(args.get("pattern"), str):
        pat = args["pattern"]
        # Absolute Windows path or POSIX absolute that isn't a glob
        if re.search(r":[\\/]", pat) or (pat.startswith("/") and not pat.startswith("/**")):
            # Take the last path segment as a relative glob
            relative = pat.replace("\\", "/").rstrip("/").split("/")[-1] or "**/*"
            logger.info("tool_repair: glob pattern %r -> %r", pat, relative)
            args["pattern"] = relative
            changed = True

    if not changed:
        return None

    return dc_replace(tool_call, name=name, arguments=args)


__all__ = ["repair_tool_call"]
