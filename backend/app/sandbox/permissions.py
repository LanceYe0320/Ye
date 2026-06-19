from __future__ import annotations

import re
import shlex

# ---------------------------------------------------------------------------
# Destructive command patterns. Matched against the WHOLE command string
# (lowercased) before allowlist logic. Kept deliberately broad — false
# positives here only block a command, never allow one.
# ---------------------------------------------------------------------------
BLOCKED_COMMANDS = {
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf ~/",
    "rm -rf .",
    "rm -rf *",
    "rm -rf /home",
    "rm -rf /root",
    "rm -rf /users",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    ":(){ :|: & };:",
    "sudo rm",
    "sudo bash",
    "sudo sh",
    "sudo su",
    "format c:",
    "format d:",
    "del /f /s /q c:",
    "rmdir /s /q c:",
}

# Regex patterns for destructive intent (more flexible than substrings)
BLOCKED_PATTERNS = [
    r"rm\s+-rf?\s+[/'\"~.]",   # rm -rf against roots/homes/cwd/globs
    r"sudo\s",                   # any sudo
    r"mkfs\.",
    r"dd\s+if=",
    r">\s*/dev/sd",              # write to block device
    r"chmod\s+777\s+/",          # world-writable root
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\binit\s+0\b",
]
_BLOCKED_RE = [re.compile(p, re.IGNORECASE) for p in BLOCKED_PATTERNS]

# ---------------------------------------------------------------------------
# Shell injection / chaining metacharacters.
# These are ALWAYS rejected, regardless of quoting — command substitution
# ($(...), `...`), process substitution (<(...), >(...)), and command
# separators (;, ||, && as separators, & background) can all smuggle an
# arbitrary payload behind an allowlisted base command.
# ---------------------------------------------------------------------------
# Substrings that indicate command/process substitution or dangerous chaining.
# Checked directly on the raw string so quoting tricks can't hide them.
# NOTE: we only block the OPENING forms — "$(", "`", "<(", ">(". A bare ")" is
# legal inside normal code (function calls, parens in Python/JS), so we don't
# reject it on its own. The opening "$(" is what makes ")" dangerous.
_INJECTION_SUBSTRINGS = [
    "$(",       # command substitution (opening)
    "`",        # backtick command substitution
    "<(",       # process substitution (input)
    ">(",       # process substitution (output)
]
# Separator tokens that are only meaningful at shell-command boundaries.
_SEPARATOR_TOKENS = {";", "||", "&", "&&"}
# `&&` is intentionally allowed for safe command chaining (e.g. git pull && npm
# install) because BOTH sides must be allowlisted — but we still reject it if
# either side contains a destructive pattern. We handle that in _has_chain.

ALLOWED_BY_DEFAULT = [
    "ls",
    "dir",
    "cat",
    "head",
    "tail",
    "grep",
    "find",
    "pwd",
    "echo",
    "wc",
    "sort",
    "uniq",
    "diff",
    "python",
    "python3",
    "pip",
    "pip3",
    "node",
    "npm",
    "npx",
    "yarn",
    "pnpm",
    "git",
    "cargo",
    "rustc",
    "go",
    "java",
    "javac",
    "mvn",
    "gradle",
    "make",
    "cmake",
    "gcc",
    "g++",
    "docker",
    "flutter",
    "dart",
]


def _base_command(cmd: str) -> str:
    """Extract the base command name, stripping any path prefix.

    "/usr/bin/git status" → "git", "./node_modules/.bin/eslint" → "eslint".
    """
    tokens = cmd.strip().split()
    if not tokens:
        return ""
    first = tokens[0].lower()
    # Strip path prefix on both / and \ separators (Windows-aware)
    for sep in ("/", "\\"):
        if sep in first:
            first = first.rsplit(sep, 1)[-1]
    # Strip a leading "./" that survives
    first = first.lstrip(".")
    # Strip Windows .exe/.bat/.cmd/.ps1 suffix so allowlist matches
    for ext in (".exe", ".bat", ".cmd", ".ps1"):
        if first.endswith(ext):
            first = first[: -len(ext)]
    return first


def is_command_allowed(command: str, custom_allowlist: list[str] | None = None) -> tuple[bool, str]:
    """Decide whether a command may run in the sandbox.

    Defense in depth, evaluated in order:
      1. Destructive patterns (rm -rf roots, mkfs, dd, sudo, shutdown, ...)
         → always blocked, even from an allowlisted base command.
      2. Injection / chaining metacharacters ($( ), ` `, <( ), unquoted ;,
         ||, &, backgrounding) → always blocked. These let a payload hide
         behind an allowlisted command.
      3. Base command must be on the (default + custom) allowlist.

    Returns (allowed, reason). reason is "" when allowed.
    """
    cmd = command.strip()
    if not cmd:
        return False, "Empty command"

    # --- 1. Destructive patterns -------------------------------------------
    cmd_lower = cmd.lower()
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return False, f"Blocked command: {blocked}"
    for rx in _BLOCKED_RE:
        if rx.search(cmd):
            return False, f"Blocked pattern: {rx.pattern}"

    # --- 2. Injection / chaining metacharacters ----------------------------
    # Command & process substitution: ALWAYS block, even inside quotes.
    for inj in _INJECTION_SUBSTRINGS:
        if inj in cmd:
            return False, f"Shell metacharacter not allowed: {inj!r}"

    # Separators: block ";" and "||" and background "&" outright. "&&" is
    # tolerated only if BOTH halves are individually allowlisted AND neither
    # half matches a destructive pattern (re-checked per half below).
    try:
        parts = shlex.split(cmd)
    except ValueError:
        # Unparseable (unmatched quotes) — be conservative, reject.
        return False, "Unparseable command (unmatched quotes)"

    # Reject standalone separator tokens
    for p in parts:
        if p in (";", "||"):
            return False, f"Shell chaining not allowed: {p!r}"

    # Backgrounding with a single trailing "&" or "& <cmd>"
    if cmd.endswith(" &") or cmd.endswith("&"):
        return False, "Background execution not allowed: '&'"

    # Handle "&&" chains: each side must independently pass this function.
    if " && " in cmd or cmd.startswith("&&") or cmd.endswith("&&"):
        halves = [h.strip() for h in cmd.split("&&") if h.strip()]
        for half in halves:
            ok, why = is_command_allowed(half, custom_allowlist)
            if not ok:
                return False, f"Chained command rejected ({half!r}): {why}"

    # --- 3. Allowlist ------------------------------------------------------
    base = _base_command(cmd)
    if not base:
        return False, "Could not determine base command"
    all_allowed = ALLOWED_BY_DEFAULT + (custom_allowlist or [])
    if base in all_allowed:
        return True, ""
    return False, f"Command not in allowlist: {base}"
