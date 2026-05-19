BLOCKED_COMMANDS = {
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "sudo rm",
    "format c:",
    "format d:",
    "del /f /s /q C:",
    "rmdir /s /q C:",
}

BLOCKED_PATTERNS = [
    "rm -rf /",
    "sudo ",
    "mkfs.",
    "dd if=",
    "> /dev/sd",
    "chmod 777 /",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
]

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
]


def is_command_allowed(command: str, custom_allowlist: list[str] | None = None) -> tuple[bool, str]:
    cmd_lower = command.strip().lower()

    for blocked in BLOCKED_COMMANDS:
        if blocked.lower() in cmd_lower:
            return False, f"Blocked command: {blocked}"

    for pattern in BLOCKED_PATTERNS:
        if pattern.lower() in cmd_lower:
            return False, f"Blocked pattern: {pattern}"

    base_cmd = cmd_lower.split()[0] if cmd_lower.split() else ""
    all_allowed = ALLOWED_BY_DEFAULT + (custom_allowlist or [])

    if base_cmd in all_allowed:
        return True, ""

    return False, f"Command not in allowlist: {base_cmd}"
