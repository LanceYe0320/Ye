"""Tests for tool-call repair (salvaging malformed GLM/DeepSeek/Qwen tool calls)."""
from __future__ import annotations

from app.llm.base_provider import ToolCall
from app.llm.tool_repair import repair_tool_call


KNOWN = {"edit_file", "write_file", "read_file", "glob", "grep", "run_command", "list_files"}


def _tc(name: str, **args) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=args)


# ---------------------------------------------------------------------------
# Tool-name repair
# ---------------------------------------------------------------------------
def test_repairs_tool_name_alias():
    """Models often emit 'edit' / 'replace_in_file' instead of 'edit_file'."""
    repaired = repair_tool_call(_tc("replace_in_file", file_path="a.py"), KNOWN)
    assert repaired is not None
    assert repaired.name == "edit_file"


def test_repairs_tool_name_case_insensitive():
    repaired = repair_tool_call(_tc("Edit_File", file_path="a.py"), KNOWN)
    assert repaired is not None
    assert repaired.name == "edit_file"


def test_repairs_uppercase_name():
    repaired = repair_tool_call(_tc("EDIT_FILE", file_path="a.py"), KNOWN)
    assert repaired is not None
    assert repaired.name == "edit_file"


def test_no_repair_when_name_already_known():
    repaired = repair_tool_call(_tc("edit_file", file_path="a.py", old_string="x", new_string="y"), KNOWN)
    # Name is fine; args are canonical; nothing to repair.
    assert repaired is None


def test_repairs_bash_to_run_command():
    repaired = repair_tool_call(_tc("bash", command="ls"), KNOWN)
    assert repaired is not None
    assert repaired.name == "run_command"


def test_genuinely_unknown_tool_not_repaired():
    """If neither the name nor any alias matches a known tool, return None."""
    repaired = repair_tool_call(_tc("totally_made_up", foo="bar"), KNOWN)
    assert repaired is None


# ---------------------------------------------------------------------------
# Parameter-name repair (camelCase → snake_case)
# ---------------------------------------------------------------------------
def test_repairs_camelcase_params():
    """GLM/DeepSeek emit filePath/oldString instead of file_path/old_string."""
    repaired = repair_tool_call(
        _tc("edit_file", filePath="a.py", oldString="x", newString="y"),
        KNOWN,
    )
    assert repaired is not None
    assert "file_path" in repaired.arguments
    assert "old_string" in repaired.arguments
    assert "new_string" in repaired.arguments
    assert repaired.arguments["file_path"] == "a.py"
    assert repaired.arguments["old_string"] == "x"
    assert repaired.arguments["new_string"] == "y"


def test_repairs_write_camelcase():
    repaired = repair_tool_call(
        _tc("write_file", filePath="a.py", content="hi"),
        KNOWN,
    )
    assert repaired is not None
    assert "path" in repaired.arguments  # canonical for write_file
    assert repaired.arguments["path"] == "a.py"


def test_keeps_correct_snake_case():
    repaired = repair_tool_call(
        _tc("edit_file", file_path="a.py", old_string="x", new_string="y"),
        KNOWN,
    )
    # Already correct snake_case params → no repair needed.
    assert repaired is None


# ---------------------------------------------------------------------------
# edit_file slot-swap fixes
# ---------------------------------------------------------------------------
def test_repairs_edit_missing_filepath_from_old():
    """Model puts path in old_string and old text in new_string."""
    repaired = repair_tool_call(
        _tc("edit_file", oldString="src/main.py", newString="old text"),
        KNOWN,
    )
    assert repaired is not None
    assert repaired.arguments["file_path"] == "src/main.py"


def test_repairs_glob_absolute_path():
    repaired = repair_tool_call(
        _tc("glob", pattern="C:\\Users\\foo\\bar\\**\\*.py"),
        KNOWN,
    )
    assert repaired is not None
    # Should be normalized to a relative pattern
    assert ":\\" not in repaired.arguments["pattern"]


def test_repairs_glob_posix_absolute():
    repaired = repair_tool_call(
        _tc("glob", pattern="/home/foo/bar/**/*.py"),
        KNOWN,
    )
    assert repaired is not None
    assert not repaired.arguments["pattern"].startswith("/home")


def test_glob_relative_pattern_untouched():
    repaired = repair_tool_call(_tc("glob", pattern="**/*.py"), KNOWN)
    assert repaired is None  # nothing wrong


# ---------------------------------------------------------------------------
# Combined repairs
# ---------------------------------------------------------------------------
def test_combined_name_and_param_repair():
    repaired = repair_tool_call(
        _tc("Edit", filePath="a.py", oldString="x", newString="y"),
        KNOWN,
    )
    assert repaired is not None
    assert repaired.name == "edit_file"
    assert "file_path" in repaired.arguments
    assert "old_string" in repaired.arguments
    assert "new_string" in repaired.arguments
