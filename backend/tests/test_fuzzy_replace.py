"""Tests for the 9-level fuzzy replace used by the edit tool."""
from __future__ import annotations

from app.llm.fuzzy_replace import fuzzy_replace


# ---------------------------------------------------------------------------
# Level 0: exact match
# ---------------------------------------------------------------------------
def test_exact_match_single():
    res = fuzzy_replace("hello world", "world", "there")
    assert res.content == "hello there"
    assert res.replacer_index == 0


def test_exact_match_multiline():
    content = "line1\nline2\nline3"
    res = fuzzy_replace(content, "line2", "LINE2")
    assert res.content == "line1\nLINE2\nline3"


def test_identical_old_new_rejected():
    res = fuzzy_replace("abc", "abc", "abc")
    assert res.content is None
    assert "identical" in res.error.lower()


# ---------------------------------------------------------------------------
# Level 1: line-trimmed (trailing whitespace differs)
# ---------------------------------------------------------------------------
def test_line_trimmed_handles_trailing_whitespace():
    content = "    foo bar   \nbaz"
    res = fuzzy_replace(content, "    foo bar\nbaz", "X\nY")
    assert res.content is not None
    assert "X" in res.content


def test_line_trimmed_leading_whitespace():
    content = "  hello world  \nsecond"
    res = fuzzy_replace(content, "hello world\nsecond", "HI\nSECOND")
    assert res.content is not None
    assert "HI" in res.content


# ---------------------------------------------------------------------------
# Level 2: block anchor (first+last line match, fuzzy middle)
# ---------------------------------------------------------------------------
def test_block_anchor_matches_with_different_middle():
    content = "def foo():\n    x = 1\n    return x\n"
    find = "def foo():\n    y = 2\n    return x\n"
    res = fuzzy_replace(content, find, "REPLACED\n")
    assert res.content is not None
    assert "REPLACED" in res.content


def test_block_anchor_requires_min_three_lines():
    # Only 2 lines — block anchor shouldn't fire; exact should match
    content = "a\nb"
    res = fuzzy_replace(content, "a\nb", "c\nd")
    assert res.content == "c\nd"


# ---------------------------------------------------------------------------
# Level 3: whitespace normalized
# ---------------------------------------------------------------------------
def test_whitespace_normalized_single_line():
    content = "foo    bar     baz"
    res = fuzzy_replace(content, "foo bar baz", "X")
    assert res.content is not None
    assert "X" in res.content


def test_whitespace_normalized_multiline():
    # find is multi-line with irregular spacing; content uses newlines+spaces
    content = "start\nfoo    bar     baz\nend"
    res = fuzzy_replace(content, "foo bar baz", "X")
    assert res.content is not None
    assert "X" in res.content


# ---------------------------------------------------------------------------
# Level 4: indentation flexible
# ---------------------------------------------------------------------------
def test_indentation_flexible():
    content = "    foo\n    bar\n    baz"
    find = "foo\nbar\nbaz"
    res = fuzzy_replace(content, find, "X\nY\nZ")
    assert res.content is not None
    assert "X" in res.content


# ---------------------------------------------------------------------------
# Level 5: escape normalized
# ---------------------------------------------------------------------------
def test_escape_normalized():
    # The find contains escaped chars that the model shouldn't have escaped
    content = 'print("hello\\n")'
    find = 'print("hello\\\\n")'  # model added extra escape
    res = fuzzy_replace(content, find, 'X')
    assert res.content is not None
    assert "X" in res.content


# ---------------------------------------------------------------------------
# Level 6: trimmed boundary
# ---------------------------------------------------------------------------
def test_trimmed_boundary():
    content = "    hello world    "
    find = "  hello world  "
    res = fuzzy_replace(content, find, "X")
    assert res.content is not None
    assert "X" in res.content


# ---------------------------------------------------------------------------
# Level 7: context aware
# ---------------------------------------------------------------------------
def test_context_aware_matches():
    content = "def func():\n    a = 1\n    b = 2\n    return a\n"
    find = "def func():\n    a = 1\n    DIFFERENT = 2\n    return a\n"
    res = fuzzy_replace(content, find, "REPLACED\n")
    assert res.content is not None
    assert "REPLACED" in res.content


# ---------------------------------------------------------------------------
# Ambiguity / not-found
# ---------------------------------------------------------------------------
def test_multiple_matches_without_replace_all_errors():
    content = "x x x"
    res = fuzzy_replace(content, "x", "y", replace_all=False)
    # Level 0 finds 3 matches, must reject as ambiguous.
    assert res.content is None
    assert "multiple" in res.error.lower() or "unique" in res.error.lower()


def test_replace_all_replaces_every_occurrence():
    content = "x x x"
    res = fuzzy_replace(content, "x", "y", replace_all=True)
    assert res.content == "y y y"


def test_not_found_returns_error():
    res = fuzzy_replace("hello world", "nonexistent", "X")
    assert res.content is None
    assert "not find" in res.error.lower() or "could not" in res.error.lower()


# ---------------------------------------------------------------------------
# Real-world-ish cases
# ---------------------------------------------------------------------------
def test_real_code_edit_with_indent_drift():
    """Simulates an LLM that got the indentation slightly wrong."""
    content = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        x = 1\n"
        "        return x\n"
    )
    find = (
        "def bar(self):\n"
        "        x = 1\n"
        "        return x\n"
    )
    res = fuzzy_replace(content, find, "REPLACED")
    assert res.content is not None
    assert "REPLACED" in res.content


def test_unicode_content():
    """Chinese / unicode content should match like any other text."""
    content = "你好世界\n第二行"
    res = fuzzy_replace(content, "你好世界", "Hello World")
    assert res.content == "Hello World\n第二行"
