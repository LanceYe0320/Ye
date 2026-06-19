"""Security tests for the command sandbox permission layer.

These pin down the attack vectors that must ALWAYS be blocked, regardless of
shell-quoting tricks. They exist so any future change to permissions.py can't
silently reopen an injection vector.
"""
from __future__ import annotations

import pytest

from app.sandbox.permissions import is_command_allowed


# ---------------------------------------------------------------------------
# Commands that must ALWAYS be DENIED (destructive / injection)
# ---------------------------------------------------------------------------
class TestAlwaysBlocked:
    @pytest.mark.parametrize("cmd", [
        # rm -rf on roots and homes (not just "/")
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf ~/",
        "rm -rf /home",
        "rm -rf /root",
        "rm -rf /Users",
        "rm -rf .",
        "rm -rf *",
        # destructive disk ops
        "mkfs.ext4 /dev/sda",
        "dd if=/dev/zero of=/dev/sda",
        # privilege escalation
        "sudo rm -rf /tmp",
        "sudo bash",
        # fork bomb
        ":(){ :|: & };:",
        # Windows destruction
        "format c:",
        "del /f /s /q C:\\",
        "rmdir /s /q C:\\Windows",
        # shutdown / reboot
        "shutdown -h now",
        "reboot",
        "poweroff",
        "halt",
    ])
    def test_destructive_commands_blocked(self, cmd):
        allowed, _ = is_command_allowed(cmd)
        assert not allowed, f"Should block destructive command: {cmd!r}"

    @pytest.mark.parametrize("cmd", [
        # command substitution — must be blocked EVEN when shlex parses fine
        'cat $(rm -rf /tmp)',
        'echo `rm -rf /tmp`',
        'ls "$(whoami)"',
        # process / arithmetic substitution
        'cat <(rm important.txt)',
        # command chaining with dangerous payloads
        'ls; rm -rf /',
        'ls && rm -rf /',
        'ls || rm -rf /',
        # backgrounding a destructive payload
        'rm -rf / &',
    ])
    def test_injection_vectors_blocked(self, cmd):
        allowed, _ = is_command_allowed(cmd)
        assert not allowed, f"Should block injection vector: {cmd!r}"


# ---------------------------------------------------------------------------
# Commands that should be ALLOWED (legitimate dev workflow)
# ---------------------------------------------------------------------------
class TestLegitimateAllowed:
    @pytest.mark.parametrize("cmd", [
        "ls -la",
        "cat README.md",
        "grep -rn 'foo' src/",
        "git status",
        "git add .",
        "git commit -m 'fix'",
        "python main.py",
        "pip install requests",
        "npm install",
        "node server.js",
        "cargo build",
        "docker ps",
        "find . -name '*.py'",
        # piped commands (pipe is allowed)
        "grep foo file.txt | head",
        "cat a && cat b",          # && with safe commands is allowed
        "echo hello world",
        "dir",                      # Windows
    ])
    def test_dev_commands_allowed(self, cmd):
        allowed, _ = is_command_allowed(cmd)
        assert allowed, f"Should allow legitimate command: {cmd!r}"


# ---------------------------------------------------------------------------
# Path-stripping: /usr/bin/git should still resolve to git
# ---------------------------------------------------------------------------
class TestPathStripping:
    def test_absolute_path_resolves(self):
        allowed, _ = is_command_allowed("/usr/bin/git status")
        assert allowed

    def test_relative_path_resolves(self):
        allowed, _ = is_command_allowed("./node_modules/.bin/eslint .")
        # .bin isn't in the allowlist by name — but eslint-style invocation
        # via a path should at least not crash. We just assert a bool result.
        assert isinstance(allowed, bool)


# ---------------------------------------------------------------------------
# Custom allowlist
# ---------------------------------------------------------------------------
class TestCustomAllowlist:
    def test_custom_allowlist_grants(self):
        allowed, _ = is_command_allowed("my-tool --flag", custom_allowlist=["my-tool"])
        assert allowed

    def test_custom_allowlist_does_not_grant_blocked(self):
        # even with a custom allowlist, destructive commands stay blocked
        allowed, _ = is_command_allowed("my-tool; rm -rf /", custom_allowlist=["my-tool"])
        assert not allowed
