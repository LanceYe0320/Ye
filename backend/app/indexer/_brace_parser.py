"""Pure-Python multi-language code chunker — a tree-sitter stand-in.

tree-sitter requires native bindings + per-language grammar packages (hundreds
of MB). This module achieves *most* of the structural benefit (splitting a file
into named function/class/method chunks instead of fixed-size line windows)
using only the Python standard library:

  - Brace-matching block tracker (for { } languages) that respects strings,
    char literals, and line/block comments.
  - Per-language signature regexes to name a chunk (function/method/class).

It won't catch every edge case a real parser would (nested generics with
unbalanced braces in strings, JSX, etc.), but it is dramatically better than
the previous "hard-cut every 80 lines" fallback for Go/Rust/Java/C/C++, and
more accurate than the old hand-rolled JS/TS brace counter because it ignores
braces inside strings and comments.
"""
from __future__ import annotations

import re
from app.indexer.code_parser import CodeChunk

# ---------------------------------------------------------------------------
# Signature patterns per language. Each maps a chunk_type to a compiled regex
# that matches a DECLARATION LINE and captures the name in group "name".
# ---------------------------------------------------------------------------

# JS / TS: function foo(...), const foo = (...), class Foo, foo(...) { (method)
_JS_TS_SIGNS = [
    ("class", re.compile(
        r"""^\s*(?:export\s+|default\s+|abstract\s+|declare\s+)*class\s+(?P<name>[A-Za-z_$][\w$]*)""",
        re.MULTILINE,
    )),
    ("function", re.compile(
        r"""^\s*(?:export\s+|default\s+|async\s+|export\s+default\s+)*function\s*\*?\s*(?P<name>[A-Za-z_$][\w$]*)""",
        re.MULTILINE,
    )),
    ("method", re.compile(
        r"""^\s*(?:static\s+|async\s+|get\s+|set\s+|public\s+|private\s+|protected\s+|readonly\s+|abstract\s+)*
        (?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\(""",
        re.MULTILINE | re.VERBOSE,
    )),
    ("function", re.compile(
        r"""^\s*(?:export\s+|const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(?[^=]*=>\s*\{""",
        re.MULTILINE,
    )),
]

_GO_SIGNS = [
    ("function", re.compile(r"""^func\s+(?:\([^)]*\)\s+)?(?P<name>[A-Za-z_]\w*)\s*\(""", re.MULTILINE)),
    ("class", re.compile(r"""^type\s+(?P<name>[A-Za-z_]\w*)\s+struct\b""", re.MULTILINE)),
]

_RUST_SIGNS = [
    ("function", re.compile(
        r"""^\s*(?:pub\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(?P<name>[A-Za-z_]\w*)""",
        re.MULTILINE,
    )),
    ("class", re.compile(
        r"""^\s*(?:pub\s+)?(?:struct|enum|trait|impl)\s+(?P<name>[A-Za-z_]\w*)""",
        re.MULTILINE,
    )),
]

_JAVA_SIGNS = [
    ("class", re.compile(
        r"""^\s*(?:public\s+|private\s+|protected\s+|static\s+|final\s+|abstract\s+)*class\s+(?P<name>[A-Za-z_]\w*)""",
        re.MULTILINE,
    )),
    ("function", re.compile(
        r"""^\s*(?:public|private|protected|static|final|abstract|synchronized|native|\s)*
        [\w<>\[\],\s]+\s+(?P<name>[A-Za-z_]\w*)\s*\([^;]*\)\s*(?:throws[^{]*)?\{""",
        re.MULTILINE | re.VERBOSE,
    )),
]

# C / C++: return-type name(...) {  (skip lines ending with ; to avoid prototypes)
_C_SIGNS = [
    ("function", re.compile(
        r"""^\s*(?:static\s+|inline\s+|extern\s+)*(?:[\w:*<>\s]+)\s+\*?(?P<name>[A-Za-z_]\w*)\s*\([^;]*\)\s*\{""",
        re.MULTILINE | re.VERBOSE,
    )),
]

_LANGUAGE_SIGNS = {
    "javascript": _JS_TS_SIGNS,
    "typescript": _JS_TS_SIGNS,
    "vue": _JS_TS_SIGNS,
    "go": _GO_SIGNS,
    "rust": _RUST_SIGNS,
    "java": _JAVA_SIGNS,
    "cpp": _C_SIGNS,
    "c": _C_SIGNS,
}

# Languages whose blocks are delimited by { }
_BRACE_LANGUAGES = {
    "javascript", "typescript", "vue", "go", "rust", "java", "cpp", "c",
}


# ---------------------------------------------------------------------------
# String / comment aware scanner — so braces inside "..." or // comments don't
# corrupt the nesting depth.
# ---------------------------------------------------------------------------

def _scan_blocks(lines: list[str]) -> list[tuple[int, int, int]]:
    """Return [(start_line_index, end_line_index, depth)] for EVERY { } block.

    Tracks brace depth while skipping over string/char literals and line/block
    comments. Unlike a top-level-only scanner, this yields blocks at ALL depths,
    so nested methods (inside a class) and free functions are both returned.
    `depth` is the nesting level at which the block lives (0 = top level).
    """
    blocks: list[tuple[int, int, int]] = []
    depth = 0
    # For each depth level, remember where it started.
    starts: list[int] = []
    in_block_comment = False

    for i, line in enumerate(lines):
        j = 0
        n = len(line)
        while j < n:
            if in_block_comment:
                end = line.find("*/", j)
                if end == -1:
                    break
                in_block_comment = False
                j = end + 2
                continue
            two = line[j:j + 2]
            ch = line[j]
            if two == "//":
                break
            if two == "/*":
                in_block_comment = True
                j += 2
                continue
            if ch in ('"', "'", "`"):
                quote = ch
                j += 1
                while j < n:
                    if line[j] == "\\":
                        j += 2
                        continue
                    if line[j] == quote:
                        j += 1
                        break
                    j += 1
                continue
            if ch == "{":
                starts.append(i)
                depth += 1
            elif ch == "}":
                depth -= 1
                if starts:
                    s = starts.pop()
                    blocks.append((s, i, depth))
            j += 1

    return blocks


def chunk_brace_language(
    file_path: str, content: str, language: str
) -> list[CodeChunk]:
    """Chunk a brace-delimited language file into named function/class blocks.

    Collects blocks at all nesting levels (so class methods are caught as well
    as free functions) and names each via per-language signature regexes. Blocks
    that don't match any signature (control-flow bodies, object literals) are
    skipped, keeping chunks meaningful for semantic search.
    """
    lines = content.splitlines()
    blocks = _scan_blocks(lines)
    if not blocks:
        from app.indexer.code_parser import _chunk_by_lines
        return _chunk_by_lines(file_path, content, language, max_lines=80)

    signs = _LANGUAGE_SIGNS.get(language, _C_SIGNS)
    chunks: list[CodeChunk] = []

    for start, end, _depth in blocks:
        # Find the declaration region: walk UP from the block start to the first
        # line that clearly ends a prior scope/declaration — a line ending with
        # }, ; , a blank line, or a line containing { (the enclosing block's
        # opener). This stops us from pulling in unrelated declarations above.
        decl_start = start
        for k in range(start, max(-1, start - 8), -1):
            ln = lines[k].rstrip()
            if k < start:
                if ln.endswith("}") or ln.endswith(";") or ln.strip() == "" or "{" in ln:
                    decl_start = k + 1
                    break
            decl_start = k
        decl_window = "\n".join(lines[decl_start:end + 1])
        name = ""
        chunk_type = "block"
        for ctype, rx in signs:
            m = rx.search(decl_window)
            if m:
                name = m.group("name")
                chunk_type = ctype
                break
        # Only keep blocks we can name — skip bare control-flow / literal blocks.
        if not name:
            continue
        chunks.append(CodeChunk(
            file_path=file_path,
            language=language,
            content="\n".join(lines[start:end + 1]),
            chunk_type=chunk_type,
            name=name,
            start_line=start + 1,
            end_line=end + 1,
        ))

    if not chunks:
        from app.indexer.code_parser import _chunk_by_lines
        return _chunk_by_lines(file_path, content, language, max_lines=80)

    # De-duplicate: when a class and its method both match, keep both but guard
    # against identical (name, type, start) duplicates from overlapping regexes.
    seen = set()
    unique: list[CodeChunk] = []
    for c in chunks:
        key = (c.name, c.chunk_type, c.start_line)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def supports_language(language: str) -> bool:
    """Whether this pure-Python parser handles the given language structurally."""
    return language in _BRACE_LANGUAGES
