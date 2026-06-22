"""Tests for the snapshot/revert system (isolated git bare repo)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import snapshot


def _git(args, cwd):
    """Helper: run git in cwd, return CompletedProcess."""
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fresh git repo with one initial commit."""
    d = tmp_path / "repo"
    d.mkdir()
    # git init + minimal identity so commits work
    _git(["init"], cwd=d)
    _git(["config", "user.email", "test@test.test"], cwd=d)
    _git(["config", "user.name", "Test"], cwd=d)
    (d / "README.md").write_text("# init\n", encoding="utf-8")
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "init"], cwd=d)
    return d


def test_snapshot_captures_tree_hash(repo: Path):
    h = snapshot.snapshot(repo)
    assert h is not None
    assert len(h) == 40  # SHA-1 tree hash


def test_snapshot_idempotent_when_no_changes(repo: Path):
    """Two consecutive snapshots with no file changes yield the same hash."""
    h1 = snapshot.snapshot(repo)
    h2 = snapshot.snapshot(repo)
    assert h1 == h2


def test_snapshot_reflects_new_file(repo: Path):
    h1 = snapshot.snapshot(repo)
    (repo / "new.txt").write_text("hello", encoding="utf-8")
    h2 = snapshot.snapshot(repo)
    assert h1 != h2
    changed = snapshot.diff_files(repo, h1)
    assert "new.txt" in changed


def test_snapshot_reflects_modification(repo: Path):
    (repo / "README.md").write_text("# v1\n", encoding="utf-8")
    h1 = snapshot.snapshot(repo)
    (repo / "README.md").write_text("# v2\n", encoding="utf-8")
    changed = snapshot.diff_files(repo, h1)
    assert "README.md" in changed


def test_restore_reverts_to_snapshot(repo: Path):
    """restore() brings the working tree back to the snapshot state."""
    # Baseline snapshot
    (repo / "file.txt").write_text("original", encoding="utf-8")
    h = snapshot.snapshot(repo)
    # Mutate
    (repo / "file.txt").write_text("modified", encoding="utf-8")
    (repo / "added.txt").write_text("new file", encoding="utf-8")
    assert (repo / "added.txt").exists()
    # Restore
    ok = snapshot.restore(repo, h)
    assert ok is True
    # file.txt back to original; added.txt... note: restore via read-tree +
    # checkout-index restores tracked files but does NOT delete extra files.
    # That's the documented behavior — revert_files handles deletions.
    assert (repo / "file.txt").read_text(encoding="utf-8") == "original"


def test_revert_files_restores_specific_file(repo: Path):
    (repo / "a.txt").write_text("A1", encoding="utf-8")
    (repo / "b.txt").write_text("B1", encoding="utf-8")
    h = snapshot.snapshot(repo)
    (repo / "a.txt").write_text("A2", encoding="utf-8")
    (repo / "b.txt").write_text("B2", encoding="utf-8")
    n = snapshot.revert_files(repo, h, ["a.txt"])
    assert n >= 1
    assert (repo / "a.txt").read_text(encoding="utf-8") == "A1"
    # b.txt untouched
    assert (repo / "b.txt").read_text(encoding="utf-8") == "B2"


def test_revert_files_deletes_post_snapshot_files(repo: Path):
    """Files created after the snapshot are removed by revert_files."""
    h = snapshot.snapshot(repo)
    (repo / "created.txt").write_text("new", encoding="utf-8")
    assert (repo / "created.txt").exists()
    n = snapshot.revert_files(repo, h, ["created.txt"])
    assert n >= 1
    assert not (repo / "created.txt").exists()


def test_diff_text_returns_unified_diff(repo: Path):
    (repo / "f.txt").write_text("line1\n", encoding="utf-8")
    h = snapshot.snapshot(repo)
    (repo / "f.txt").write_text("line1\nline2\n", encoding="utf-8")
    diff = snapshot.diff_text(repo, h)
    assert "+line2" in diff


def test_snapshot_outside_git_repo_returns_none(tmp_path: Path):
    """Non-git directory: snapshot gracefully degrades to None."""
    d = tmp_path / "nogit"
    d.mkdir()
    assert snapshot.snapshot(d) is None


def test_diff_files_outside_git_repo_empty(tmp_path: Path):
    d = tmp_path / "nogit"
    d.mkdir()
    assert snapshot.diff_files(d, "deadbeef") == []


def test_ensure_snapshot_repo_creates_bare_repo(repo: Path):
    gitdir = snapshot.ensure_snapshot_repo(repo)
    assert gitdir is not None
    assert (gitdir / "HEAD").exists()
    # Idempotent: second call returns same path without error
    gitdir2 = snapshot.ensure_snapshot_repo(repo)
    assert gitdir2 == gitdir


def test_cleanup_runs_without_error(repo: Path):
    """cleanup() should not raise even on a fresh repo."""
    snapshot.snapshot(repo)  # ensure there's something to gc
    snapshot.cleanup(repo)  # should not raise
