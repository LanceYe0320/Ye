"""Tests for the triplet permission ruleset + bash arity normalization."""
from __future__ import annotations

from app.permission_rules import (
    BASH_ARITY, Rule, Ruleset, check, check_tool,
    command_arity_prefix, _glob_match,
)


# ---------------------------------------------------------------------------
# Glob matching
# ---------------------------------------------------------------------------
def test_glob_exact():
    assert _glob_match("edit_file", "edit_file")
    assert not _glob_match("edit_file", "write_file")


def test_glob_star_matches_anything():
    assert _glob_match("anything", "*")


def test_glob_double_star_crosses_separators():
    assert _glob_match("src/a/b.py", "src/**")
    assert _glob_match("src/a/b/c.py", "src/**")


def test_glob_single_star_no_separator():
    """Single * should NOT cross path separators (only ** does)."""
    assert _glob_match("src/main.py", "src/*.py")  # one segment
    assert not _glob_match("src/a/main.py", "src/*.py")  # two segments


def test_glob_question_mark():
    assert _glob_match("a.py", "?.py")
    assert not _glob_match("ab.py", "?.py")


def test_glob_case_insensitive():
    assert _glob_match("Edit_File", "edit_file")


# ---------------------------------------------------------------------------
# Rule + Ruleset evaluation (last match wins)
# ---------------------------------------------------------------------------
def test_ruleset_last_match_wins():
    rs = Ruleset(rules=[
        Rule("run_command", "git *", "allow"),
        Rule("run_command", "git push *", "ask"),   # later, overrides
    ])
    assert rs.evaluate("run_command", "git push origin").action == "ask"
    # Non-push git still allow
    assert rs.evaluate("run_command", "git status").action == "allow"


def test_ruleset_default_ask_when_no_match():
    rs = Ruleset(rules=[Rule("read_file", "*", "allow")])
    # No rule matches write_file → default ask
    assert rs.evaluate("write_file", "x.py").action == "ask"


def test_rule_matches_both_permission_and_pattern():
    r = Rule("edit_file", "src/**", "allow")
    assert r.matches("edit_file", "src/a.py")
    assert not r.matches("edit_file", "test/a.py")  # pattern mismatch
    assert not r.matches("write_file", "src/a.py")  # permission mismatch


# ---------------------------------------------------------------------------
# Default ruleset — public check() / check_tool()
# ---------------------------------------------------------------------------
def test_check_read_tools_allow():
    assert check("read_file", "any.py") == "allow"
    assert check("glob", "**/*.py") == "allow"
    assert check("grep", "pattern") == "allow"


def test_check_write_tools_ask():
    assert check("write_file", "any.py") == "ask"
    assert check("edit_file", "any.py") == "ask"


def test_check_destructive_commands_deny():
    # check() takes the pattern directly; for run_command destructive base
    # commands the pattern is the base name. check_tool() additionally
    # extracts the base command from a full command string.
    assert check("run_command", "rm") == "deny"
    assert check("run_command", "sudo") == "deny"
    assert check("run_command", "mkfs.ext4") == "deny"
    # Full command strings go through check_tool which splits base cmd
    assert check_tool("run_command", command="rm -rf x") == "deny"
    assert check_tool("run_command", command="sudo ls") == "deny"
    assert check_tool("run_command", command="mkfs.ext4 /dev/sda") == "deny"


def test_check_safe_commands_allow():
    assert check("run_command", "git status") == "allow"
    assert check("run_command", "ls -la") == "allow"
    assert check("run_command", "cat file.txt") == "allow"


def test_check_unknown_command_asks():
    # An arity-normalized unknown command falls to the catch-all ask rule
    assert check("run_command", "someobscurecmd --flag") == "ask"


# ---------------------------------------------------------------------------
# check_tool — arity normalization for run_command
# ---------------------------------------------------------------------------
def test_check_tool_run_command_uses_arity():
    # "git checkout main" arity-normalizes to "git checkout" → matches "git *"
    assert check_tool("run_command", command="git checkout main") == "allow"
    # rm anywhere → deny
    assert check_tool("run_command", command="rm -rf node_modules") == "deny"


def test_check_tool_file_tools_use_path():
    assert check_tool("edit_file", file_path="src/a.py") == "ask"
    assert check_tool("read_file", file_path="src/a.py") == "allow"


def test_check_tool_glob_uses_pattern():
    assert check_tool("glob", pattern="**/*.py") == "allow"


# ---------------------------------------------------------------------------
# Bash arity normalization
# ---------------------------------------------------------------------------
def test_arity_simple_command():
    assert command_arity_prefix("ls -la") == "ls"
    assert command_arity_prefix("rm file.txt") == "rm"


def test_arity_two_token_command():
    # git has arity 2 → "git checkout" / "git status" (command + subcommand)
    assert command_arity_prefix("git checkout main") == "git checkout"
    assert command_arity_prefix("git status") == "git status"


def test_arity_three_token_command():
    # npm run has arity 3
    result = command_arity_prefix("npm run dev")
    assert result == "npm run dev"


def test_arity_strips_flags():
    # --no-pager is a flag, dropped; remaining "git log" → arity 2
    assert command_arity_prefix("git --no-pager log") == "git log"


def test_arity_unknown_command():
    # Unknown → arity defaults to 2 (command + first arg)
    result = command_arity_prefix("mycustomtool foo bar")
    assert result == "mycustomtool foo"


def test_arity_empty():
    assert command_arity_prefix("") == ""


def test_arity_dict_has_common_commands():
    # Sanity: ensure the table covers the common stacks
    for cmd in ("git", "npm", "python", "docker", "cargo", "pip", "yarn", "go"):
        assert cmd in BASH_ARITY
