"""Fuzzy multi-level string replacer for the edit tool.

A faithful Python port of opencode's 9-level ``Replacer`` chain
(``packages/opencode/src/tool/edit.ts``). The motivation: LLMs frequently
return an ``old_string`` that differs from the file's actual text in trivial
ways — trailing whitespace, indentation, escape sequences, line-ending
normalization. A pure exact-match tool rejects these and the model wastes an
agentic-loop iteration re-reading the file. By trying progressively looser
matchers we let most edits succeed on the first try.

Public API:

  :class:`ReplaceResult`  — outcome of :func:`fuzzy_replace`.
  :func:`fuzzy_replace`   — the single entry point used by ``edit_file``.

Design notes (kept identical to the TS original so behaviour is predictable):

  * Replacers are tried in a fixed order, simplest/strictest first.
  * The first replacer that yields a *unique* match wins.
  * ``replace_all`` replaces every occurrence; otherwise ambiguity (multiple
    matches) is an error.
  * All replacers operate on the raw file content — they return the actual
    substring present in the file so the splice is byte-exact.

This module has **no project dependencies** so it can be tested in isolation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# Similarity thresholds (mirror edit.ts constants)
_SINGLE_CANDIDATE_SIMILARITY_THRESHOLD = 0.6
_MULTIPLE_CANDIDATES_SIMILARITY_THRESHOLD = 0.8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _levenshtein(a: str, b: str) -> int:
    """Classic Levenshtein edit distance."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # Rolling two-row DP
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def _line_slice_to_index(lines: list[str], start: int, end_exclusive: int) -> tuple[int, int]:
    """Convert [start, end) line range → (char_start, char_end) indices in the
    '\n'-joined text. ``end_exclusive`` is exclusive."""
    char_start = sum(len(lines[k]) + 1 for k in range(start))
    char_end = sum(len(lines[k]) + 1 for k in range(start, end_exclusive))
    # Remove the trailing newline added after the last included line
    char_end -= 1 if end_exclusive > start else 0
    return char_start, char_end


# ---------------------------------------------------------------------------
# Replacers — each is a generator yielding candidate substrings actually
# present in ``content``. Order matters; we go strict → fuzzy.
# ---------------------------------------------------------------------------
def _simple_replacer(content: str, find: str):
    yield find


def _line_trimmed_replacer(content: str, find: str):
    original_lines = content.split("\n")
    search_lines = find.split("\n")
    if search_lines and search_lines[-1] == "":
        search_lines.pop()
    n = len(search_lines)
    if n == 0:
        return
    for i in range(len(original_lines) - n + 1):
        ok = all(original_lines[i + j].strip() == search_lines[j].strip() for j in range(n))
        if ok:
            char_start, char_end = _line_slice_to_index(original_lines, i, i + n)
            yield content[char_start:char_end]


def _block_anchor_replacer(content: str, find: str):
    original_lines = content.split("\n")
    search_lines = find.split("\n")
    if len(search_lines) < 3:
        return
    if search_lines and search_lines[-1] == "":
        search_lines.pop()
    if len(search_lines) < 3:
        return
    first_line_search = search_lines[0].strip()
    last_line_search = search_lines[-1].strip()
    search_block_size = len(search_lines)

    # Collect candidate (start, end_inclusive) line ranges
    candidates: list[tuple[int, int]] = []
    for i in range(len(original_lines)):
        if original_lines[i].strip() != first_line_search:
            continue
        for j in range(i + 2, len(original_lines)):
            if original_lines[j].strip() == last_line_search:
                candidates.append((i, j))
                break
    if not candidates:
        return

    def _similarity(start: int, end_incl: int) -> float:
        actual = end_incl - start + 1
        lines_to_check = min(search_block_size - 2, actual - 2)
        if lines_to_check <= 0:
            return 1.0
        sim = 0.0
        for j in range(1, min(search_block_size - 1, actual - 1)):
            o = original_lines[start + j].strip()
            s = search_lines[j].strip()
            m = max(len(o), len(s))
            if m == 0:
                continue
            sim += 1 - _levenshtein(o, s) / m
        return sim / lines_to_check

    def _emit(start: int, end_incl: int):
        char_start, char_end = _line_slice_to_index(original_lines, start, end_incl + 1)
        yield_tuple = content[char_start:char_end]
        return yield_tuple

    if len(candidates) == 1:
        s, e = candidates[0]
        if _similarity(s, e) >= _SINGLE_CANDIDATE_SIMILARITY_THRESHOLD:
            yield _emit(s, e)
        return

    # Multiple candidates: pick the most similar above threshold
    best = None
    best_sim = -1.0
    for s, e in candidates:
        sim = _similarity(s, e)
        if sim > best_sim:
            best_sim = sim
            best = (s, e)
    if best is not None and best_sim >= _MULTIPLE_CANDIDATES_SIMILARITY_THRESHOLD:
        yield _emit(best[0], best[1])


def _whitespace_normalized_replacer(content: str, find: str):
    norm = lambda t: re.sub(r"\s+", " ", t).strip()
    normalized_find = norm(find)
    lines = content.split("\n")
    # single-line matches
    for line in lines:
        if norm(line) == normalized_find:
            yield line
        elif normalized_find and normalized_find in norm(line):
            words = [w for w in find.strip().split() if w]
            if words:
                pattern = r"\s+".join(re.escape(w) for w in words)
                m = re.search(pattern, line)
                if m:
                    yield m.group(0)
    # multi-line block matches
    find_lines = find.split("\n")
    if len(find_lines) > 1:
        for i in range(len(lines) - len(find_lines) + 1):
            block = lines[i:i + len(find_lines)]
            if norm("\n".join(block)) == normalized_find:
                yield "\n".join(block)


def _indentation_flexible_replacer(content: str, find: str):
    def _remove_indent(text: str) -> str:
        ls = text.split("\n")
        non_empty = [l for l in ls if l.strip()]
        if not non_empty:
            return text
        min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
        return "\n".join(l if not l.strip() else l[min_indent:] for l in ls)

    normalized_find = _remove_indent(find)
    content_lines = content.split("\n")
    find_lines = find.split("\n")
    n = len(find_lines)
    for i in range(len(content_lines) - n + 1):
        block = "\n".join(content_lines[i:i + n])
        if _remove_indent(block) == normalized_find:
            yield block


def _escape_normalized_replacer(content: str, find: str):
    _UNESCAPE = {
        "n": "\n", "t": "\t", "r": "\r", "'": "'", '"': '"',
        "`": "`", "\\": "\\", "$": "$",
    }

    def _unescape(s: str) -> str:
        out = []
        i = 0
        while i < len(s):
            c = s[i]
            if c == "\\" and i + 1 < len(s):
                nxt = s[i + 1]
                if nxt in _UNESCAPE:
                    out.append(_UNESCAPE[nxt])
                    i += 2
                    continue
                elif nxt == "\n":  # backslash-newline
                    out.append("\n")
                    i += 2
                    continue
            out.append(c)
            i += 1
        return "".join(out)

    unescaped_find = _unescape(find)
    if unescaped_find in content:
        yield unescaped_find
    lines = content.split("\n")
    find_lines = unescaped_find.split("\n")
    n = len(find_lines)
    for i in range(len(lines) - n + 1):
        block = "\n".join(lines[i:i + n])
        if _unescape(block) == unescaped_find:
            yield block


def _multi_occurrence_replacer(content: str, find: str):
    # Yields ``find`` once for each exact occurrence — the caller decides
    # whether multiple occurrences are acceptable (replace_all) or an error.
    if not find:
        # Empty find would loop forever (find("") always returns the start
        # index without advancing). The entry point already rejects empty
        # old_string, but defend here too for direct callers.
        return
    start = 0
    while True:
        idx = content.find(find, start)
        if idx == -1:
            break
        yield find
        start = idx + len(find)


def _trimmed_boundary_replacer(content: str, find: str):
    trimmed_find = find.strip()
    if trimmed_find == find:
        return
    if trimmed_find in content:
        yield trimmed_find
    lines = content.split("\n")
    find_lines = find.split("\n")
    n = len(find_lines)
    for i in range(len(lines) - n + 1):
        block = "\n".join(lines[i:i + n])
        if block.strip() == trimmed_find:
            yield block


def _context_aware_replacer(content: str, find: str):
    find_lines = find.split("\n")
    if len(find_lines) < 3:
        return
    if find_lines and find_lines[-1] == "":
        find_lines.pop()
    if len(find_lines) < 3:
        return
    content_lines = content.split("\n")
    first_line = find_lines[0].strip()
    last_line = find_lines[-1].strip()
    n = len(find_lines)
    for i in range(len(content_lines)):
        if content_lines[i].strip() != first_line:
            continue
        for j in range(i + 2, len(content_lines)):
            if content_lines[j].strip() == last_line:
                block_lines = content_lines[i:j + 1]
                block = "\n".join(block_lines)
                if len(block_lines) == n:
                    matching = 0
                    total = 0
                    for k in range(1, len(block_lines) - 1):
                        bl = block_lines[k].strip()
                        fl = find_lines[k].strip()
                        if bl or fl:
                            total += 1
                            if bl == fl:
                                matching += 1
                    if total == 0 or matching / total >= 0.5:
                        yield block
                break


# Ordered chain — strictest first
_REPLACERS = [
    _simple_replacer,
    _line_trimmed_replacer,
    _block_anchor_replacer,
    _whitespace_normalized_replacer,
    _indentation_flexible_replacer,
    _escape_normalized_replacer,
    _trimmed_boundary_replacer,
    _context_aware_replacer,
    _multi_occurrence_replacer,
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dataclass
class ReplaceResult:
    """Outcome of a fuzzy replace attempt."""
    content: str | None        # new file content on success, else None
    matched_substring: str | None  # the actual substring that was replaced
    replacer_index: int | None    # which replacer level succeeded (0-based)
    error: str | None             # human-readable error when content is None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def fuzzy_replace(content: str, old_string: str, new_string: str, replace_all: bool = False) -> ReplaceResult:
    """Replace ``old_string`` with ``new_string`` in ``content`` using the
    9-level fuzzy matcher.

    Returns a :class:`ReplaceResult`. On success ``content`` holds the new
    text; on failure ``error`` explains why (not found / ambiguous).
    """
    if old_string == new_string:
        return ReplaceResult(None, None, None, "old_string and new_string are identical — nothing to replace.")
    # Empty old_string is invalid — it would cause infinite loops in the
    # multi-occurrence replacer (find("") always returns the start index) and
    # has no meaningful replacement semantics. Models do emit this occasionally.
    if not old_string:
        return ReplaceResult(
            None, None, None,
            "old_string is empty — nothing to search for. "
            "Use write_file if you want to replace the whole file.",
        )

    not_found = True
    for idx, replacer in enumerate(_REPLACERS):
        for candidate in replacer(content, old_string):
            if not candidate:
                continue
            loc = content.find(candidate)
            if loc == -1:
                continue
            not_found = False
            if replace_all:
                # Replace every occurrence of this candidate substring
                new_content = content.replace(candidate, new_string)
                return ReplaceResult(new_content, candidate, idx, None)
            # Unique-match check: only accept if candidate appears exactly once
            first = content.find(candidate)
            last = content.rfind(candidate)
            if first != last:
                continue
            new_content = content[:first] + new_string + content[first + len(candidate):]
            return ReplaceResult(new_content, candidate, idx, None)

    if not_found:
        return ReplaceResult(
            None, None, None,
            "Could not find old_string in the file. It must match (allowing for "
            "whitespace/indentation/escape differences). Use read_file to see the "
            "current content.",
        )
    return ReplaceResult(
        None, None, None,
        "Found multiple matches for old_string. Provide more surrounding context "
        "to make the match unique.",
    )


__all__ = ["fuzzy_replace", "ReplaceResult"]
