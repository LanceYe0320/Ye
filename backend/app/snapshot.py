"""File-state snapshots + per-step revert, backed by an isolated git bare repo.

Ported from opencode's ``snapshot/index.ts``. The idea: keep a *separate*
git object database (a bare repo) that mirrors the user's working tree, so
we can capture cheap tree hashes at any point and later restore or revert
individual files to a prior snapshot — without touching the user's real
``.git`` directory.

Layout::

    ~/.ye/data/snapshot/<project_key>/<worktree_hash>/
        HEAD, objects/, refs/, info/exclude, ...   (a bare repo)

Why a separate repo (not the user's own git history)?
  * The user's repo may be pristine / committed; we must not pollute it.
  * Snapshot writes happen automatically after each tool step; committing
    into the user's history would be intrusive.
  * A bare repo sharing the work-tree gives us git's diff/checkout speed
    with zero interference.

Public API (all synchronous, matching the project's ``subprocess.run`` style):

    ensure_snapshot_repo(workdir)   -> Path    # lazy init the bare repo
    snapshot(workdir)               -> str|None  # write-tree hash
    diff_files(workdir, hash)       -> list[str] # changed files since hash
    diff_text(workdir, hash)        -> str       # unified diff since hash
    restore(workdir, hash)          -> None      # full restore to snapshot
    revert_files(workdir, hash, files) -> None   # restore specific files

All calls are best-effort: on any git failure they log and degrade
gracefully (return empty/None) rather than raising — snapshots are a
safety net, not a correctness-critical path.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Skip files larger than this when snapshotting (mirrors opencode's 2MB limit).
# Huge generated artifacts bloat the object DB for little replay value.
_LARGE_FILE_LIMIT = 2 * 1024 * 1024


def _data_root() -> Path:
    """``~/.ye/data/snapshot`` — XDG-ish app data dir for snapshots."""
    return Path.home() / ".ye" / "data" / "snapshot"


def _project_key(workdir: Path) -> str:
    """Stable short key identifying a project+worktree pair.

    Uses the resolved absolute path hash so two different checkouts of the
    same repo get separate snapshot stores.
    """
    try:
        resolved = str(workdir.resolve())
    except Exception:
        resolved = str(workdir)
    return hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:12]


def _gitdir_for(workdir: Path) -> Path:
    return _data_root() / _project_key(workdir) / "repo"


def _run_git(args: list[str], *, cwd: Path | None = None, env: dict | None = None,
             check: bool = False) -> subprocess.CompletedProcess:
    """Run a git command, returning the CompletedProcess.

    ``check=False`` by default — callers inspect ``returncode`` themselves.
    """
    full_env = None
    if env:
        import os
        full_env = {**os.environ, **env}
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=full_env,
        creationflags=_creation_flags(),
    )


def _creation_flags() -> int:
    """Windows: hide the console window for spawned git processes."""
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def _is_enabled(workdir: Path) -> bool:
    """Snapshots require the workdir to be inside a git repo."""
    return (workdir / ".git").exists() or _run_git(
        ["rev-parse", "--is-inside-work-tree"], cwd=workdir
    ).returncode == 0


def ensure_snapshot_repo(workdir: Path) -> Path | None:
    """Lazily initialize the bare snapshot repo for ``workdir``.

    Returns the gitdir path, or ``None`` if git is unavailable / workdir
    isn't a git repo. Safe to call repeatedly.
    """
    if not _is_enabled(workdir):
        return None
    gitdir = _gitdir_for(workdir)
    if (gitdir / "HEAD").exists():
        return gitdir
    try:
        gitdir.mkdir(parents=True, exist_ok=True)
        _run_git(["init", "--bare", str(gitdir)], check=False)
        # Match opencode's portability config.
        _run_git(["--git-dir", str(gitdir), "config", "core.autocrlf", "false"])
        _run_git(["--git-dir", str(gitdir), "config", "core.longpaths", "true"])
        _run_git(["--git-dir", str(gitdir), "config", "core.symlinks", "true"])
        logger.info("snapshot repo initialized at %s", gitdir)
        return gitdir
    except Exception as e:
        logger.warning("snapshot init failed: %s", e)
        return None


def _gitdir_args(workdir: Path) -> list[str]:
    """Build the ``--git-dir``/``--work-tree`` prefix for snapshot operations."""
    return ["--git-dir", str(_gitdir_for(workdir)), "--work-tree", str(workdir)]


def _stage_all(workdir: Path) -> None:
    """Stage all changes (tracked + untracked, respecting .gitignore) into the
    snapshot index. Mirrors opencode's ``add()``: diff-files + ls-files --others."""
    gargs = _gitdir_args(workdir)
    # List tracked-but-modified files
    diff = _run_git(gargs + ["diff-files", "--name-only", "-z", "--", "."], cwd=workdir)
    # List untracked files (excluding gitignored)
    other = _run_git(gargs + ["ls-files", "--others", "--exclude-standard", "-z", "--", "."], cwd=workdir)
    if diff.returncode != 0 or other.returncode != 0:
        logger.debug("snapshot stage listing failed (diff=%s other=%s)",
                     diff.returncode, other.returncode)
        return
    files: list[str] = []
    for src in (diff.stdout, other.stdout):
        files.extend(f for f in src.split("\0") if f)
    if not files:
        return
    # Skip oversized files to avoid bloating the object DB.
    pruned = []
    for rel in files:
        try:
            p = workdir / rel
            if p.is_file() and p.stat().st_size > _LARGE_FILE_LIMIT:
                continue
        except OSError:
            pass
        pruned.append(rel)
    if not pruned:
        return
    _run_git(
        gargs + ["add", "--all", "--force", "--"] + pruned,
        cwd=workdir,
    )


def snapshot(workdir: Path) -> str | None:
    """Capture a snapshot of the current working tree.

    Returns the tree hash (a 40-char SHA-1), or ``None`` if snapshots are
    unavailable or nothing could be captured.
    """
    gitdir = ensure_snapshot_repo(workdir)
    if gitdir is None:
        return None
    try:
        _stage_all(workdir)
        result = _run_git(_gitdir_args(workdir) + ["write-tree"], cwd=workdir)
        if result.returncode != 0:
            logger.debug("snapshot write-tree failed: %s", result.stderr.strip())
            return None
        tree_hash = result.stdout.strip()
        if len(tree_hash) == 40:
            logger.info("snapshot captured: %s", tree_hash)
            return tree_hash
        return None
    except Exception as e:
        logger.warning("snapshot capture failed: %s", e)
        return None


def diff_files(workdir: Path, hash: str) -> list[str]:
    """List files changed since ``hash`` (relative paths, forward slashes)."""
    gitdir = ensure_snapshot_repo(workdir)
    if gitdir is None:
        return []
    try:
        _stage_all(workdir)
        result = _run_git(
            _gitdir_args(workdir) + ["diff", "--cached", "--no-ext-diff",
                                     "--name-only", hash, "--", "."],
            cwd=workdir,
        )
        if result.returncode != 0:
            return []
        return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def diff_text(workdir: Path, hash: str) -> str:
    """Unified diff of all changes since ``hash``."""
    gitdir = ensure_snapshot_repo(workdir)
    if gitdir is None:
        return ""
    try:
        _stage_all(workdir)
        result = _run_git(
            _gitdir_args(workdir) + ["diff", "--cached", "--no-ext-diff", hash, "--", "."],
            cwd=workdir,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def restore(workdir: Path, hash: str) -> bool:
    """Restore the *entire* working tree to the snapshot at ``hash``.

    Returns True on success, False otherwise. Destructive — callers should
    confirm with the user.
    """
    gitdir = ensure_snapshot_repo(workdir)
    if gitdir is None:
        return False
    try:
        r1 = _run_git(_gitdir_args(workdir) + ["read-tree", hash], cwd=workdir)
        if r1.returncode != 0:
            logger.warning("snapshot restore read-tree failed: %s", r1.stderr.strip())
            return False
        r2 = _run_git(_gitdir_args(workdir) + ["checkout-index", "-a", "-f"], cwd=workdir)
        if r2.returncode != 0:
            logger.warning("snapshot restore checkout failed: %s", r2.stderr.strip())
            return False
        logger.info("snapshot restored to %s", hash)
        return True
    except Exception as e:
        logger.warning("snapshot restore failed: %s", e)
        return False


def revert_files(workdir: Path, hash: str, files: list[str]) -> int:
    """Revert specific ``files`` to their state at ``hash``.

    Files that didn't exist at ``hash`` are deleted (they were created after
    the snapshot). Returns the number of files reverted.
    """
    gitdir = ensure_snapshot_repo(workdir)
    if gitdir is None:
        return 0
    reverted = 0
    for rel in files:
        rel_fwd = rel.replace("\\", "/")
        abs_path = workdir / rel_fwd
        # Try to checkout the file from the snapshot tree.
        r = _run_git(
            _gitdir_args(workdir) + ["checkout", hash, "--", rel_fwd],
            cwd=workdir,
        )
        if r.returncode == 0:
            reverted += 1
            continue
        # If checkout failed, check whether the file existed in the snapshot.
        tree = _run_git(
            _gitdir_args(workdir) + ["ls-tree", hash, "--", rel_fwd],
            cwd=workdir,
        )
        if tree.returncode == 0 and tree.stdout.strip():
            # Existed but checkout failed — leave as-is (don't delete).
            continue
        # Didn't exist at snapshot → it was created after; delete it.
        try:
            if abs_path.exists():
                abs_path.unlink()
                reverted += 1
        except OSError:
            pass
    logger.info("reverted %d/%d files to %s", reverted, len(files), hash)
    return reverted


def cleanup(workdir: Path) -> None:
    """Run ``git gc`` on the snapshot repo to prune old objects.

    Call periodically (e.g. on session exit) to keep the object DB bounded.
    """
    gitdir = _gitdir_for(workdir)
    if not (gitdir / "HEAD").exists():
        return
    try:
        _run_git(_gitdir_args(workdir) + ["gc", "--prune=7.days"], cwd=workdir)
        logger.info("snapshot gc done for %s", gitdir)
    except Exception as e:
        logger.debug("snapshot gc failed: %s", e)


__all__ = [
    "ensure_snapshot_repo",
    "snapshot",
    "diff_files",
    "diff_text",
    "restore",
    "revert_files",
    "cleanup",
]
