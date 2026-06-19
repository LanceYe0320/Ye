"""Persistent file-based memory system for Ye CLI — with forgetting mechanism.


Article reference: "Harness 第三层 — 状态与记忆，记住该记的，忘掉该忘的"
  - "记忆不是仓库，是花园。需要定期修剪。"
  - Retention scoring based on: access frequency, recency, importance, validation status

Memories are stored as markdown files in ~/.ye/memory/.
MEMORY.md serves as an index file loaded into context.

Retention scores:
  HIGH   → Keep original text
  MEDIUM → Compress to summary
  LOW    → Delete
"""

from __future__ import annotations
import logging

import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)
_MEMORY_DIR = Path.home() / ".ye" / "memory"
_INDEX_FILE = _MEMORY_DIR / "MEMORY.md"
_META_FILE = _MEMORY_DIR / "_meta.json"
_CATEGORIES = ["user", "feedback", "project", "reference"]

# Tier 1: Bounded core memory (always in context)
_CORE_MEMORY_FILE = _MEMORY_DIR / "core.md"
_CORE_USER_FILE = _MEMORY_DIR / "user.md"
_CORE_MEMORY_MAX = 2200  # chars
_CORE_USER_MAX = 1375

# Retention thresholds
_RETENTION_HIGH = 0.6
_RETENTION_LOW = 0.25

# Scoring weights (5 factors, sum = 1.0)
_W_RECENCY = 0.25
_W_FREQUENCY = 0.25
_W_SIZE = 0.15
_W_AGE = 0.15
_W_RELEVANCE = 0.20

# Category importance multipliers
_CATEGORY_WEIGHTS: dict[str, float] = {
    "project": 1.3,
    "feedback": 1.2,
    "user": 1.1,
    "reference": 0.8,
    "compressed": 0.5,
}

# Max memory age in days before automatic pruning
_MAX_AGE_DAYS = 90

# Stop words for keyword extraction
_STOP_WORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "have", "this", "that", "with",
    "from", "they", "been", "said", "each", "which", "their", "will", "other",
    "about", "many", "then", "them", "these", "some", "would", "make", "like",
    "into", "time", "very", "when", "what", "your", "there", "use", "than",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
    "看", "好", "自己", "这",
})


def _ensure_dir():
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)


# Cached directory listing of the memory dir, invalidated by mtime. Avoids
# repeated rglob system calls across get_context / search / prune in a turn.
_memory_dir_cache: tuple[float, list[Path]] = (0.0, [])


def _list_memory_files() -> list[Path]:
    """Return *.md files in the memory dir, cached by directory mtime.

    Multiple memory operations in a single turn (get_context, search, prune)
    each used to rglob the whole directory. This caches the listing until the
    directory's mtime changes.
    """
    global _memory_dir_cache
    try:
        dir_mtime = _MEMORY_DIR.stat().st_mtime
    except OSError:
        return []
    cached_mtime, cached_files = _memory_dir_cache
    if dir_mtime == cached_mtime and cached_files:
        return cached_files
    files = list(_MEMORY_DIR.rglob("*.md"))
    _memory_dir_cache = (dir_mtime, files)
    return files


def _load_meta() -> dict[str, Any]:
    """Load memory metadata (access counts, last access time, etc.)."""
    if _META_FILE.is_file():
        try:
            return json.loads(_META_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("suppressed", exc_info=True)
            pass
    return {"entries": {}}


def _save_meta(meta: dict):
    _ensure_dir()
    _META_FILE.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _record_access(name: str, referenced_by: str | None = None, meta: dict | None = None):
    """Record that a memory was accessed (for retention scoring).

    Pass an existing `meta` dict (from _load_meta) to update it in memory
    WITHOUT touching disk — the caller is then responsible for one final
    _save_meta(meta). This avoids N reads + N writes when recording access
    for many memories at once (e.g. in get_context).
    """
    save_needed = meta is None
    if meta is None:
        meta = _load_meta()
    entries = meta.setdefault("entries", {})
    key = name.replace(" ", "_")
    entry = entries.setdefault(key, {})
    entry["access_count"] = entry.get("access_count", 0) + 1
    entry["last_access"] = time.time()
    if referenced_by:
        refs = entry.setdefault("referenced_by", [])
        if referenced_by not in refs:
            refs.append(referenced_by)
    if save_needed:
        _save_meta(meta)


def _extract_keywords(text: str) -> set[str]:
    """Extract keywords from text for relevance scoring."""
    lower = text.lower()
    words = set(re.findall(r'[a-z一-鿿]{3,}', lower))
    return words - _STOP_WORDS


# --- Core API ---


def save(category: str, name: str, content: str) -> str:
    """Save a memory entry. Category is a subdirectory, name becomes the filename."""
    if category not in _CATEGORIES:
        return f"Invalid category '{category}'. Use: {', '.join(_CATEGORIES)}"
    _ensure_dir()
    cat_dir = _MEMORY_DIR / category
    cat_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filepath = cat_dir / f"{safe_name}.md"

    header = f"---\nname: {name}\ncategory: {category}\ndate: {datetime.now().isoformat()}\n---\n\n"
    filepath.write_text(header + content, encoding="utf-8")

    # Initialize metadata with pre-computed keywords
    keywords = _extract_keywords(content)
    meta = _load_meta()
    key = safe_name
    meta.setdefault("entries", {})[key] = {
        "created_at": time.time(),
        "access_count": 0,
        "last_access": time.time(),
        "size": len(content),
        "category": category,
        "_keywords": sorted(keywords),
    }
    _save_meta(meta)

    _rebuild_index()
    return f"Saved memory '{name}' in category '{category}'"


def load(category: str | None = None) -> str:
    """Load memories. If category is None, load all."""
    _ensure_dir()
    if category:
        cat_dir = _MEMORY_DIR / category
        if not cat_dir.is_dir():
            return f"No memories in category '{category}'."
        files = sorted(cat_dir.glob("*.md"))
    else:
        files = sorted(_MEMORY_DIR.rglob("*.md"))

    if not files:
        return "No memories found."

    parts: list[str] = []
    for f in files:
        if f.name == "MEMORY.md":
            continue
        parts.append(f"### {f.relative_to(_MEMORY_DIR)}\n")
        parts.append(f.read_text(encoding="utf-8"))
        parts.append("")
    return "\n".join(parts) if parts else "No memories found."


def search(query: str) -> str:
    """Search across all memories for a keyword."""
    _ensure_dir()
    query_lower = query.lower()
    results: list[str] = []
    for f in _MEMORY_DIR.rglob("*.md"):
        if f.name in ("MEMORY.md", "_meta.json"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if query_lower in text.lower():
            rel = f.relative_to(_MEMORY_DIR)
            results.append(f"--- {rel} ---\n{text[:500]}")
            # Record access
            _record_access(f.stem)
    if not results:
        return f"No memories matching '{query}'."
    return "\n\n".join(results)


def delete(name: str) -> str:
    """Delete a memory by name (matches filename stem)."""
    _ensure_dir()
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    for f in _MEMORY_DIR.rglob("*.md"):
        if f.name == "MEMORY.md":
            continue
        if f.stem == safe_name:
            f.unlink()
            # Remove from metadata
            meta = _load_meta()
            meta.get("entries", {}).pop(safe_name, None)
            _save_meta(meta)
            _rebuild_index()
            return f"Deleted memory '{f.relative_to(_MEMORY_DIR)}'."
    for f in _MEMORY_DIR.rglob("*.md"):
        if f.name == "MEMORY.md":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if f"name: {name}" in text:
            f.unlink()
            meta = _load_meta()
            meta.get("entries", {}).pop(f.stem, None)
            _save_meta(meta)
            _rebuild_index()
            return f"Deleted memory '{f.relative_to(_MEMORY_DIR)}'."
    return f"No memory found with name '{name}'."


def list_all() -> str:
    """Show the memory index."""
    _ensure_dir()
    if not _INDEX_FILE.is_file():
        return "No memories saved yet."
    return _INDEX_FILE.read_text(encoding="utf-8")


def get_context(max_chars: int = 4000, context_keywords: set[str] | None = None) -> str:
    """Load memories as context for the system prompt — three-layer approach.

    Tier 1 (always loaded): core.md + user.md (bounded, always in context)
    Tier 2 (scored): category memories sorted by retention + relevance
    Tier 3 (session): handled by session_search module
    """
    _ensure_dir()
    parts: list[str] = []
    total = 0

    # --- Tier 1: Core memory (always loaded, bounded) ---
    if _CORE_MEMORY_FILE.is_file():
        core = _CORE_MEMORY_FILE.read_text(encoding="utf-8").strip()
        if core:
            parts.append("## Core Memory\n" + core)
            total += len(core)

    if _CORE_USER_FILE.is_file():
        user = _CORE_USER_FILE.read_text(encoding="utf-8").strip()
        if user:
            parts.append("## User Profile\n" + user)
            total += len(user)

    # --- Tier 2: Category memories (scored, budget-filling) ---
    tier2_budget = max_chars - total
    if tier2_budget > 0:
        # Load meta ONCE and mutate it in memory, then persist ONCE at the end.
        # Previously _record_access was called per-file, each doing a full
        # load+save of _meta.json → N×(read+write) disk ops per get_context.
        meta = _load_meta()
        memory_files = _list_memory_files()  # cached directory scan
        scored_files: list[tuple[float, Path]] = []
        for f in memory_files:
            if f.name in ("MEMORY.md", "_meta.json", "core.md", "user.md"):
                continue
            key = f.stem
            score = compute_retention_score(key, meta, context_keywords=context_keywords)
            scored_files.append((score, f))
        scored_files.sort(key=lambda x: x[0], reverse=True)

        tier2_parts: list[str] = []
        tier2_total = 0
        accessed: list[str] = []
        for _score, f in scored_files:
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            if tier2_total + len(text) > tier2_budget:
                break
            tier2_parts.append(text)
            tier2_total += len(text)
            accessed.append(f.stem)
        # Batch-record access in memory (no disk I/O), then persist once.
        for name in accessed:
            _record_access(name, meta=meta)
        if accessed:
            _save_meta(meta)
        if tier2_parts:
            parts.append("## Persistent Memory\n\n" + "\n---\n".join(tier2_parts))

    if not parts:
        return ""
    return "\n\n".join(parts)


# --- Forgetting / Retention ---


def compute_retention_score(
    entry_key: str,
    meta: dict,
    category: str | None = None,
    context_keywords: set[str] | None = None,
) -> float:
    """Compute retention score [0.0, 1.0] for a memory entry.

    Higher score = more worth keeping.
    Factors: recency, access frequency, size, age, keyword relevance.
    Post-factors: category multiplier, relationship bonus.
    """
    entries = meta.get("entries", {})
    entry = entries.get(entry_key, {})

    now = time.time()
    created_at = entry.get("created_at", now)
    last_access = entry.get("last_access", created_at)
    access_count = entry.get("access_count", 0)
    size = entry.get("size", 100)

    # Resolve category from metadata if not provided
    if category is None:
        category = entry.get("category", "")

    # Recency: how recently was this accessed? (0-1, 1 = just now)
    days_since_access = (now - last_access) / 86400
    recency = max(0, 1 - days_since_access / _MAX_AGE_DAYS)

    # Frequency: how often accessed (0-1, log scale)
    frequency = min(1.0, math.log1p(access_count) / math.log1p(20))

    # Size: prefer concise memories (0-1, shorter = higher)
    size_score = max(0.1, 1 - size / 5000)

    # Age penalty: very old memories decay
    age_days = (now - created_at) / 86400
    age_score = max(0.1, 1 - age_days / (_MAX_AGE_DAYS * 2))

    # Keyword relevance: boost if memory keywords overlap with context
    relevance = 0.5  # neutral default
    if context_keywords:
        stored = entry.get("_keywords", [])
        if stored:
            mem_kw = set(stored)
            overlap = len(context_keywords & mem_kw) / max(1, len(context_keywords))
            relevance = 0.3 + 0.7 * overlap

    score = (
        _W_RECENCY * recency
        + _W_FREQUENCY * frequency
        + _W_SIZE * size_score
        + _W_AGE * age_score
        + _W_RELEVANCE * relevance
    )

    # Category importance multiplier
    cat_weight = _CATEGORY_WEIGHTS.get(category, 1.0)
    score *= cat_weight

    # Relationship bonus: memories referenced by others are more important
    ref_count = len(entry.get("referenced_by", []))
    score += min(0.15, ref_count * 0.05)

    return round(min(1.0, max(0.0, score)), 3)


def _compress_content(content: str, max_lines: int = 4) -> str:
    """Extract key sentences from memory content using importance heuristics.

    Scores lines by: position, importance keywords, numbers, list markers, length.
    Returns the top-scoring lines in their original order.
    """
    lines = [
        l for l in content.split("\n")
        if l.strip()
        and not l.strip().startswith("---")
        and not l.strip().startswith("name:")
        and not l.strip().startswith("category:")
        and not l.strip().startswith("date:")
    ]

    if len(lines) <= max_lines:
        return "\n".join(lines)

    importance_keywords = {
        "important", "key", "critical", "must", "always", "never",
        "注意", "重要", "关键", "必须", "核心",
    }

    scored: list[tuple[float, int, str]] = []
    for i, line in enumerate(lines):
        s = 0.0
        stripped = line.strip()
        lower = stripped.lower()

        # First content line is always important
        if i == 0:
            s += 3.0
        # Lines with importance keywords
        if any(kw in lower for kw in importance_keywords):
            s += 2.0
        # Lines with numbers (often contain specific values)
        if re.search(r'\d+', stripped):
            s += 1.0
        # Bullet/list items (structured content)
        if stripped.startswith(("- ", "* ", "1.", "2.", "3.")):
            s += 1.0
        # Longer lines tend to have more content
        s += min(1.0, len(stripped) / 100)

        scored.append((s, i, line))

    # Pick top-scoring lines, restore original order
    scored.sort(key=lambda x: x[0], reverse=True)
    selected_indices = sorted([x[1] for x in scored[:max_lines]])
    return "\n".join(lines[idx] for idx in selected_indices)


def prune_memories(dry_run: bool = False) -> str:
    """Prune memories based on retention scores.

    HIGH (>= 0.6)   → Keep as-is
    MEDIUM (0.25-0.6) → Compress to summary
    LOW (< 0.25)    → Delete

    Returns a report of what was done.
    """
    _ensure_dir()
    meta = _load_meta()
    entries = meta.get("entries", {})

    if not entries:
        return "No memories to prune."

    kept = []
    compressed = []
    deleted = []

    for key, entry_data in list(entries.items()):
        # Resolve category from metadata or file path
        cat = entry_data.get("category", "")
        if not cat:
            for f in _MEMORY_DIR.rglob("*.md"):
                if f.stem == key and f.name != "MEMORY.md":
                    parts = f.relative_to(_MEMORY_DIR).parts
                    if len(parts) > 1:
                        cat = parts[0]
                    break

        score = compute_retention_score(key, meta, category=cat)
        entry_data["retention_score"] = score

        # Find the actual file
        filepath = None
        for f in _MEMORY_DIR.rglob("*.md"):
            if f.stem == key and f.name != "MEMORY.md":
                filepath = f
                break

        if filepath is None or not filepath.is_file():
            # Orphaned metadata entry, clean up
            entries.pop(key, None)
            deleted.append(f"{key} (orphaned metadata)")
            continue

        if score >= _RETENTION_HIGH:
            kept.append(f"{key} (score: {score})")
        elif score >= _RETENTION_LOW:
            # Compress using importance-based extraction
            if not dry_run:
                content = filepath.read_text(encoding="utf-8")
                lines_total = len([l for l in content.split("\n") if l.strip()])
                if lines_total > 3:
                    compressed_text = _compress_content(content, max_lines=4)
                    compressed_content = (
                        f"---\nname: {key}\ncategory: compressed\ndate: {datetime.now().isoformat()}\n---\n\n"
                        + compressed_text
                        + f"\n... [compressed from {lines_total} lines, retention: {score}]"
                    )
                    filepath.write_text(compressed_content, encoding="utf-8")
            compressed.append(f"{key} (score: {score})")
        else:
            # Delete
            if not dry_run:
                filepath.unlink()
                entries.pop(key, None)
            deleted.append(f"{key} (score: {score})")

    if not dry_run:
        _save_meta(meta)
        _rebuild_index()

    report = ["Memory Pruning Report:", ""]
    if kept:
        report.append(f"  Kept ({len(kept)}):")
        for k in kept[:5]:
            report.append(f"    + {k}")
        if len(kept) > 5:
            report.append(f"    ... and {len(kept) - 5} more")
    if compressed:
        report.append(f"  Compressed ({len(compressed)}):")
        for c in compressed:
            report.append(f"    ~ {c}")
    if deleted:
        report.append(f"  Deleted ({len(deleted)}):")
        for d in deleted:
            report.append(f"    - {d}")

    return "\n".join(report)


def retention_report() -> str:
    """Show retention scores for all memories without modifying anything."""
    _ensure_dir()
    meta = _load_meta()
    entries = meta.get("entries", {})

    if not entries:
        return "No memories to evaluate."

    lines = ["Memory Retention Scores:", f"  {'Name':30s} {'Score':>6s} {'Access':>6s} {'Age':>8s} Action", ""]
    for key in sorted(entries.keys()):
        score = compute_retention_score(key, meta)
        access = entries[key].get("access_count", 0)
        age_days = (time.time() - entries[key].get("created_at", time.time())) / 86400
        age_str = f"{age_days:.0f}d" if age_days >= 1 else f"{age_days * 24:.0f}h"

        if score >= _RETENTION_HIGH:
            action = "KEEP"
        elif score >= _RETENTION_LOW:
            action = "COMPRESS"
        else:
            action = "DELETE"

        lines.append(f"  {key:30s} {score:>6.3f} {access:>6d} {age_str:>8s} {action}")

    return "\n".join(lines)


def _rebuild_index():
    """Rebuild the MEMORY.md index file."""
    _ensure_dir()
    lines = ["# Ye Memory Index\n"]
    for cat in _CATEGORIES:
        cat_dir = _MEMORY_DIR / cat
        if not cat_dir.is_dir():
            continue
        files = sorted(cat_dir.glob("*.md"))
        if not files:
            continue
        lines.append(f"\n## {cat.title()}\n")
        for f in files:
            rel = f.relative_to(_MEMORY_DIR)
            try:
                text = f.read_text(encoding="utf-8")
                first_line = ""
                for line in text.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("---") and not line.startswith("name:") and not line.startswith("category:") and not line.startswith("date:"):
                        first_line = line[:100]
                        break
                desc = first_line or f.stem
            except Exception:
                desc = f.stem
            lines.append(f"- [{f.stem}]({rel}) — {desc}")
    _INDEX_FILE.write_text("\n".join(lines), encoding="utf-8")


# --- Tier 1: Core Memory Management ---


def core_memory_load() -> str:
    """Load the bounded core memory (always in context)."""
    _ensure_dir()
    if _CORE_MEMORY_FILE.is_file():
        return _CORE_MEMORY_FILE.read_text(encoding="utf-8")
    return ""


def core_memory_save(text: str) -> str:
    """Save core memory, enforcing the character bound."""
    _ensure_dir()
    if len(text) > _CORE_MEMORY_MAX:
        text = text[:_CORE_MEMORY_MAX] + "\n... [truncated to fit bound]"
    _CORE_MEMORY_FILE.write_text(text, encoding="utf-8")
    return f"Core memory saved ({len(text)}/{_CORE_MEMORY_MAX} chars)"


def core_memory_append(line: str) -> str:
    """Append a line to core memory if space allows."""
    _ensure_dir()
    current = core_memory_load()
    new_text = (current.rstrip() + "\n" + line).strip()
    if len(new_text) > _CORE_MEMORY_MAX:
        return f"Core memory full ({len(current)}/{_CORE_MEMORY_MAX} chars). Remove something first."
    _CORE_MEMORY_FILE.write_text(new_text, encoding="utf-8")
    return f"Appended to core memory ({len(new_text)}/{_CORE_MEMORY_MAX} chars)"


def core_memory_remove(keyword: str) -> str:
    """Remove lines containing keyword from core memory."""
    _ensure_dir()
    current = core_memory_load()
    lines = current.split("\n")
    filtered = [l for l in lines if keyword.lower() not in l.lower()]
    removed = len(lines) - len(filtered)
    if removed == 0:
        return f"No lines matching '{keyword}' in core memory."
    _CORE_MEMORY_FILE.write_text("\n".join(filtered), encoding="utf-8")
    return f"Removed {removed} line(s) matching '{keyword}' from core memory."


def user_profile_load() -> str:
    """Load the user profile memory."""
    _ensure_dir()
    if _CORE_USER_FILE.is_file():
        return _CORE_USER_FILE.read_text(encoding="utf-8")
    return ""


def user_profile_save(text: str) -> str:
    """Save user profile, enforcing the character bound."""
    _ensure_dir()
    if len(text) > _CORE_USER_MAX:
        text = text[:_CORE_USER_MAX] + "\n... [truncated to fit bound]"
    _CORE_USER_FILE.write_text(text, encoding="utf-8")
    return f"User profile saved ({len(text)}/{_CORE_USER_MAX} chars)"


# ---------------------------------------------------------------------------
# Async wrappers — use these from async code to avoid blocking the event loop
# ---------------------------------------------------------------------------

import asyncio


async def async_save(category: str, name: str, content: str) -> str:
    """Async version of save() — offloads file I/O to a thread."""
    return await asyncio.to_thread(save, category, name, content)


async def async_load(category: str | None = None) -> str:
    """Async version of load()."""
    return await asyncio.to_thread(load, category)


async def async_search(query: str) -> str:
    """Async version of search()."""
    return await asyncio.to_thread(search, query)


async def async_delete(name: str) -> str:
    """Async version of delete()."""
    return await asyncio.to_thread(delete, name)


async def async_list_all() -> str:
    """Async version of list_all()."""
    return await asyncio.to_thread(list_all)


async def async_get_context(max_chars: int = 4000, context_keywords: set[str] | None = None) -> str:
    """Async version of get_context() — the hot path in system prompt building."""
    return await asyncio.to_thread(get_context, max_chars, context_keywords)


async def async_core_load() -> str:
    """Async version of core_memory_load()."""
    return await asyncio.to_thread(core_memory_load)


async def async_core_save(text: str) -> str:
    """Async version of core_memory_save()."""
    return await asyncio.to_thread(core_memory_save, text)


async def async_user_profile_load() -> str:
    """Async version of user_profile_load()."""
    return await asyncio.to_thread(user_profile_load)


async def async_user_profile_save(text: str) -> str:
    """Async version of user_profile_save()."""
    return await asyncio.to_thread(user_profile_save, text)

