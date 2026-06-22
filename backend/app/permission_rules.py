"""Permission ruleset — triplet (permission, pattern, action) with glob matching.

Ported and simplified from opencode's ``core/permission.ts`` + the bash
``arity`` table. The existing ``app/permissions.py`` maps a *tool name* to a
single auto/ask/deny level — coarse and unable to express rules like
"edit_file is allowed on src/** but ask everywhere else" or "run_command
git is auto but run_command rm is deny".

This module adds a richer layer on top:

    Rule(permission="edit_file", pattern="src/**", action="allow")
    Rule(permission="run_command", pattern="git *",   action="allow")
    Rule(permission="run_command", pattern="rm *",     action="deny")
    Rule(permission="run_command", pattern="*",        action="ask")

Evaluation: walk rules in order, **last match wins** (mirrors opencode's
``findLast``), falling back to "ask" when nothing matches.

For ``run_command`` we normalize the command to its *arity prefix* before
matching (``git checkout main`` → ``git checkout``, ``npm run dev`` →
``npm run dev``), so a single rule covers a whole subcommand family.

The legacy ``app/permissions.py`` API is preserved; this module is the
progressive upgrade path and is consulted first by the tool executor.
"""
from __future__ import annotations

import fnmatch
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_RULES_FILE = Path.home() / ".ye" / "permission_rules.json"

VALID_ACTIONS = ("allow", "deny", "ask")


# ---------------------------------------------------------------------------
# Bash command arity — how many leading tokens define the "command".
# Mirrors opencode's permission/arity.ts. ``git checkout main`` → 2 tokens
# ("git checkout"), ``npm run dev`` → 3 tokens. Flags never count.
# Used to normalize shell commands before glob-matching against rules.
# ---------------------------------------------------------------------------
BASH_ARITY: dict[str, int] = {
    "cat": 1, "cd": 1, "chmod": 1, "chown": 1, "cp": 1, "echo": 1,
    "env": 1, "export": 1, "grep": 1, "kill": 1, "killall": 1, "ln": 1,
    "ls": 1, "mkdir": 1, "mv": 1, "ps": 1, "pwd": 1, "rm": 1, "rmdir": 1,
    "sleep": 1, "source": 1, "tail": 1, "touch": 1, "unset": 1, "which": 1,
    "dir": 1, "type": 1, "del": 1, "copy": 1, "move": 1, "cls": 1,
    "aws": 3, "az": 3, "bazel": 2, "brew": 2, "bun": 2, "bun run": 3,
    "bun x": 3, "cargo": 2, "cargo add": 3, "cargo run": 3, "cdk": 2,
    "cmake": 2, "composer": 2, "deno": 2, "deno task": 3, "docker": 2,
    "docker builder": 3, "docker compose": 3, "docker container": 3,
    "docker image": 3, "docker network": 3, "docker volume": 3,
    "gh": 3, "git": 2, "git config": 3, "git remote": 3, "git stash": 3,
    "go": 2, "gradle": 2, "helm": 2, "make": 2, "mvn": 2, "ng": 2,
    "npm": 2, "npm exec": 3, "npm init": 3, "npm run": 3, "npm view": 3,
    "npx": 2, "nvm": 2, "nx": 2, "pip": 2, "pip3": 2, "pipenv": 2,
    "pnpm": 2, "pnpm dlx": 3, "pnpm exec": 3, "pnpm run": 3, "poetry": 2,
    "psql": 2, "python": 2, "python3": 2, "rake": 2, "rustup": 2,
    "systemctl": 2, "terraform": 2, "tmux": 2, "vercel": 2,
    "yarn": 2, "yarn dlx": 3, "yarn run": 3,
}


def command_arity_prefix(command: str) -> str:
    """Normalize a shell command to its arity prefix for rule matching.

    Strips flags, then takes the leading N tokens where N is determined by
    the longest matching entry in BASH_ARITY. ``git checkout main`` →
    ``git checkout``; ``npm run dev`` → ``npm run dev``; ``python script.py``
    → ``python script.py`` (arity 2 = command + script).
    """
    # Tokenize, dropping flags (tokens starting with -).
    tokens = [t for t in command.strip().split() if not t.startswith("-")]
    if not tokens:
        return ""
    # Try longest-prefix match against BASH_ARITY.
    for length in range(min(len(tokens), 3), 0, -1):
        prefix = " ".join(tokens[:length])
        if prefix in BASH_ARITY:
            arity = BASH_ARITY[prefix]
            return " ".join(tokens[:arity])
    # Unknown command: use base + first arg (arity 2 default for "tool target").
    if len(tokens) >= 2:
        return " ".join(tokens[:2])
    return tokens[0]


# ---------------------------------------------------------------------------
# Glob matching — fnmatch with ** support (opencode uses a similar wildcard lib)
# ---------------------------------------------------------------------------
def _glob_match(text: str, pattern: str) -> bool:
    """Glob match with ``**`` recursive-directory support.

    ``src/**`` matches ``src/a/b.py``; ``*`` matches anything except ``/``;
    ``**`` matches across path separators. Case-insensitive on Windows.
    """
    if not pattern or pattern == "*":
        return True
    # Translate ** to a regex that crosses separators; * to non-separator.
    # Build regex char-by-char for predictability.
    i = 0
    regex = ["^"]
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                regex.append(".*")
                i += 2
                # Consume an optional trailing slash so "src/**" matches "src"
                if i < len(pattern) and pattern[i] == "/":
                    regex.append("/?")
                    i += 1
                continue
            regex.append("[^/]*")
            i += 1
        elif c == "?":
            regex.append("[^/]")
            i += 1
        else:
            regex.append(re.escape(c))
            i += 1
    regex.append("$")
    flags = re.IGNORECASE
    return re.match("".join(regex), text, flags) is not None


# ---------------------------------------------------------------------------
# Rule + Ruleset
# ---------------------------------------------------------------------------
@dataclass
class Rule:
    """A single permission rule: match (permission, pattern) → action."""
    permission: str   # tool name, or "edit"/"write" category, or "run_command"
    pattern: str      # glob: "src/**", "git *", "*"
    action: str       # "allow" | "deny" | "ask"

    def matches(self, permission: str, pattern: str) -> bool:
        return _glob_match(permission, self.permission) and _glob_match(pattern, self.pattern)


@dataclass
class Ruleset:
    """Ordered list of rules. Last match wins."""
    rules: list[Rule] = field(default_factory=list)

    def evaluate(self, permission: str, pattern: str) -> Rule:
        """Return the last matching rule, or a default 'ask' rule."""
        for rule in reversed(self.rules):
            if rule.matches(permission, pattern):
                return rule
        return Rule(permission=permission, pattern="*", action="ask")

    def add(self, rule: Rule) -> None:
        self.rules.append(rule)


# ---------------------------------------------------------------------------
# Built-in default ruleset — mirrors the legacy app/permissions.py defaults
# but expressed as triplets. Read-only tools auto-allow; writes ask; the
# nastiest shell commands are denied outright.
# ---------------------------------------------------------------------------
def _default_rules() -> list[Rule]:
    # Order matters under last-match-wins: BROAD rules first, SPECIFIC rules
    # last. This way the specific "run_command git * allow" overrides the
    # broad "run_command * ask", and the narrower "rm * deny" overrides
    # both. User rules added via add_rule() are appended AFTER these, so
    # they always win over the built-in defaults — which is the intended
    # behaviour (user config takes precedence).
    return [
        # --- Broad baselines (ask by default) ---
        Rule("write_file", "*", "ask"),
        Rule("edit_file", "*", "ask"),
        Rule("append_file", "*", "ask"),
        Rule("run_command", "*", "ask"),
        # --- Read-only exploration: always allow ---
        Rule("read_file", "*", "allow"),
        Rule("list_files", "*", "allow"),
        Rule("glob", "*", "allow"),
        Rule("grep", "*", "allow"),
        Rule("search_codebase", "*", "allow"),
        Rule("project_overview", "*", "allow"),
        Rule("web_search", "*", "allow"),
        Rule("web_fetch", "*", "allow"),
        # --- Safe shell commands: allow (still pass through the sandbox
        # injection/destructive gate in app.sandbox.permissions) ---
        Rule("run_command", "git *", "allow"),
        Rule("run_command", "ls *", "allow"),
        Rule("run_command", "ls", "allow"),
        Rule("run_command", "dir *", "allow"),
        Rule("run_command", "cat *", "allow"),
        Rule("run_command", "grep *", "allow"),
        Rule("run_command", "find *", "allow"),
        Rule("run_command", "pwd", "allow"),
        Rule("run_command", "echo *", "allow"),
        # --- Destructive shell commands: deny outright ---
        # Cover both the arity-normalized form ("rm", arity 1) and any form
        # with arguments ("rm *"). Without the bare-name rule, a command
        # like "rm" alone would fall through to the catch-all ask.
        Rule("run_command", "rm", "deny"),
        Rule("run_command", "rm *", "deny"),
        Rule("run_command", "rmdir", "deny"),
        Rule("run_command", "rmdir *", "deny"),
        Rule("run_command", "del", "deny"),
        Rule("run_command", "del *", "deny"),
        Rule("run_command", "format", "deny"),
        Rule("run_command", "format *", "deny"),
        Rule("run_command", "mkfs*", "deny"),
        Rule("run_command", "dd", "deny"),
        Rule("run_command", "dd *", "deny"),
        Rule("run_command", "sudo", "deny"),
        Rule("run_command", "sudo *", "deny"),
        Rule("run_command", "shutdown*", "deny"),
        Rule("run_command", "reboot*", "deny"),
        # NOTE: no global catch-all here — evaluate() already falls back to
        # "ask" when no rule matches, and an explicit "*/*" rule would
        # shadow every earlier specific rule under last-match-wins.
    ]


# ---------------------------------------------------------------------------
# Persistence — load/save user-defined rules on top of defaults
# ---------------------------------------------------------------------------
_cache: Ruleset | None = None


def _load() -> Ruleset:
    global _cache
    if _cache is not None:
        return _cache
    ruleset = Ruleset(rules=_default_rules())
    if _RULES_FILE.is_file():
        try:
            data = json.loads(_RULES_FILE.read_text(encoding="utf-8"))
            for entry in data.get("rules", []):
                ruleset.add(Rule(
                    permission=entry["permission"],
                    pattern=entry.get("pattern", "*"),
                    action=entry["action"],
                ))
        except Exception as e:
            logger.warning("failed to load permission rules: %s", e)
    _cache = ruleset
    return ruleset


def _invalidate() -> None:
    global _cache
    _cache = None


def _save() -> None:
    rs = _load()
    user_rules = []
    defaults = _default_rules()
    # Only persist rules that differ from / extend the defaults.
    default_keys = {(r.permission, r.pattern, r.action) for r in defaults}
    for r in rs.rules:
        if (r.permission, r.pattern, r.action) not in default_keys:
            user_rules.append({
                "permission": r.permission, "pattern": r.pattern, "action": r.action,
            })
    _RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RULES_FILE.write_text(
        json.dumps({"rules": user_rules}, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def check(permission: str, pattern: str = "*") -> str:
    """Evaluate the ruleset for (permission, pattern). Returns allow/deny/ask."""
    return _load().evaluate(permission, pattern).action


def check_tool(tool_name: str, **tool_args) -> str:
    """Convenience: evaluate a tool call against the ruleset.

    For ``run_command`` we evaluate BOTH the base command (first token, e.g.
    ``rm``) and the arity-normalized form (e.g. ``git checkout``) and take
    the stricter result — so a destructive base command (``rm``) is denied
    even when the arity form would be allowed. For file tools the
    ``path``/``file_path`` arg is the pattern.
    """
    if tool_name == "run_command":
        cmd = tool_args.get("command", "")
        if not cmd:
            return check(tool_name, "*")
        base = cmd.strip().split()[0] if cmd.strip() else "*"
        arity_form = command_arity_prefix(cmd)
        # Evaluate both; deny wins, then allow, then ask.
        results = [check(tool_name, base), check(tool_name, arity_form)]
        if "deny" in results:
            return "deny"
        if "allow" in results:
            return "allow"
        return "ask"
    elif tool_name in ("edit_file", "write_file", "read_file", "append_file"):
        pattern = tool_args.get("file_path") or tool_args.get("path") or "*"
        return check(tool_name, pattern)
    elif tool_name in ("glob", "grep"):
        pattern = tool_args.get("pattern", "*")
        return check(tool_name, pattern)
    return check(tool_name, "*")


def add_rule(permission: str, pattern: str, action: str) -> None:
    """Append a user rule and persist it."""
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action {action!r}; use {VALID_ACTIONS}")
    rs = _load()
    rs.add(Rule(permission=permission, pattern=pattern, action=action))
    _save()
    _invalidate()


def list_rules() -> list[Rule]:
    """Return the full effective ruleset (defaults + user rules)."""
    return list(_load().rules)


__all__ = [
    "Rule", "Ruleset", "check", "check_tool", "add_rule", "list_rules",
    "command_arity_prefix", "BASH_ARITY",
]
