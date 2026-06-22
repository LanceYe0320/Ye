"""Tests for the lightweight post-edit diagnostics module."""
from __future__ import annotations

from pathlib import Path

from app.lint import diagnose, diagnostic_block


def test_clean_python_no_errors(tmp_path: Path):
    f = tmp_path / "clean.py"
    f.write_text("x = 1\nprint(x)\n", encoding="utf-8")
    assert diagnose(f) == []


def test_python_syntax_error_detected(tmp_path: Path):
    f = tmp_path / "broken.py"
    f.write_text("def foo(\n", encoding="utf-8")  # unclosed paren
    errors = diagnose(f)
    assert len(errors) > 0
    assert any("syntax" in e.lower() or "compile" in e.lower() or "foo" in e or "line" in e.lower() for e in errors)


def test_python_indentation_error_detected(tmp_path: Path):
    f = tmp_path / "indent.py"
    f.write_text("def foo():\nprint('bad indent')\n", encoding="utf-8")
    errors = diagnose(f)
    assert len(errors) > 0


def test_clean_json_no_errors(tmp_path: Path):
    f = tmp_path / "ok.json"
    f.write_text('{"key": "value"}\n', encoding="utf-8")
    assert diagnose(f) == []


def test_json_error_detected(tmp_path: Path):
    f = tmp_path / "bad.json"
    f.write_text('{"key": value}\n', encoding="utf-8")  # unquoted value
    errors = diagnose(f)
    assert len(errors) > 0
    assert "json" in errors[0].lower()


def test_unsupported_file_type_returns_empty(tmp_path: Path):
    f = tmp_path / "readme.md"
    f.write_text("# hello\n", encoding="utf-8")
    assert diagnose(f) == []


def test_nonexistent_file_returns_empty(tmp_path: Path):
    assert diagnose(tmp_path / "nope.py") == []


def test_diagnostic_block_empty_when_clean(tmp_path: Path):
    f = tmp_path / "clean.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert diagnostic_block(f) == ""


def test_diagnostic_block_formatted_when_errors(tmp_path: Path):
    f = tmp_path / "broken.py"
    f.write_text("def foo(\n", encoding="utf-8")
    block = diagnostic_block(f)
    assert block.startswith('<diagnostics file="broken.py">')
    assert block.endswith("</diagnostics>")


def test_diagnostic_block_accepts_string_path(tmp_path: Path):
    f = tmp_path / "broken.py"
    f.write_text("def (\n", encoding="utf-8")
    block = diagnostic_block(str(f))
    assert "<diagnostics" in block


def test_errors_capped_at_max(tmp_path: Path):
    """A file with many errors should be truncated to a reasonable count."""
    f = tmp_path / "many.py"
    # Each line is a syntax error on its own
    f.write_text("\n".join("def (" for _ in range(50)), encoding="utf-8")
    errors = diagnose(f)
    assert len(errors) <= 20  # _MAX_ERRORS


def test_javascript_clean_when_node_absent(tmp_path: Path):
    """If node isn't installed, JS diagnosis returns [] gracefully."""
    f = tmp_path / "ok.js"
    f.write_text("const x = 1;\n", encoding="utf-8")
    # Should not raise regardless of whether node is present
    result = diagnose(f)
    assert isinstance(result, list)
