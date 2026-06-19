"""Git worktree management for Ye CLI.


Provides isolated git worktrees so agents or tasks can work
on separate branches without affecting the main working tree.
"""

from __future__ import annotations
import logging

import subprocess
from pathlib import Path



logger = logging.getLogger(__name__)
def create_worktree(name: str, cwd: Path) -> tuple[Path, str]:
    """Create a new git worktree. Returns (worktree_path, branch_name).

    Args:
        name: Name for the worktree and branch.
        cwd: Current working directory (must be a git repo).

    Returns:
        Tuple of (worktree_path, branch_name).
    """
    branch = f"ye/{name}"
    worktree_dir = cwd / ".ye" / "worktrees" / name

    try:
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree_dir), "-b", branch],
            capture_output=True, text=True, cwd=str(cwd), timeout=15,
        )
        if result.returncode != 0:
            return Path(), f"Error creating worktree: {result.stderr.strip()}"
    except Exception as e:
        return Path(), f"Error: {e}"

    return worktree_dir, branch


def remove_worktree(name: str, cwd: Path) -> str:
    """Remove a git worktree and its branch."""
    worktree_dir = cwd / ".ye" / "worktrees" / name
    if not worktree_dir.exists():
        return f"Worktree '{name}' not found."

    try:
        result = subprocess.run(
            ["git", "worktree", "remove", str(worktree_dir), "--force"],
            capture_output=True, text=True, cwd=str(cwd), timeout=15,
        )
        if result.returncode != 0:
            return f"Error removing worktree: {result.stderr.strip()}"
    except Exception as e:
        return f"Error: {e}"

    # Clean up the branch
    try:
        subprocess.run(
            ["git", "branch", "-D", f"ye/{name}"],
            capture_output=True, text=True, cwd=str(cwd), timeout=10,
        )
    except Exception:
        logger.debug("suppressed", exc_info=True)
        pass

    return f"Worktree '{name}' removed."


def list_worktrees(cwd: Path) -> str:
    """List all ye-managed worktrees."""
    worktree_base = cwd / ".ye" / "worktrees"
    if not worktree_base.is_dir():
        return "No worktrees."

    entries = []
    for d in sorted(worktree_base.iterdir()):
        if d.is_dir():
            branch = f"ye/{d.name}"
            entries.append(f"  {d.name} -> {branch} ({d})")
    return "\n".join(entries) if entries else "No worktrees."
