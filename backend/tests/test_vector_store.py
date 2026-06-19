"""Tests for the vector store indexer — chunk identity & stale pruning.

These verify the content-hash fix: editing a function body produces a new
chunk id and the old one is pruned, so semantic search never returns code
that no longer exists.
"""
from __future__ import annotations

import pytest

from app.indexer.code_parser import CodeChunk
from app.indexer import vector_store


@pytest.fixture
def fresh_store(monkeypatch, tmp_path):
    """Point the vector store at an isolated temp DB so tests don't pollute."""
    # Reset the module-level collection cache
    monkeypatch.setattr(vector_store, "_collection", None)
    monkeypatch.setattr(vector_store, "_CHROMA_DIR", tmp_path / "chroma")
    return vector_store


def _chunk(name, content, start=1):
    return CodeChunk(
        file_path="src/app.py",
        language="python",
        chunk_type="function",
        name=name,
        start_line=start,
        end_line=start + content.count("\n"),
        content=content,
    )


class TestChunkIdentity:
    def test_same_content_same_id(self, fresh_store):
        c = _chunk("foo", "def foo():\n    return 1\n")
        assert fresh_store._chunk_id("proj", c) == fresh_store._chunk_id("proj", c)

    def test_different_content_different_id(self, fresh_store):
        """The core fix: editing the body changes the id."""
        v1 = _chunk("foo", "def foo():\n    return 1\n")
        v2 = _chunk("foo", "def foo():\n    return 2\n")  # body changed
        assert fresh_store._chunk_id("proj", v1) != fresh_store._chunk_id("proj", v2)

    def test_different_function_same_id_structure(self, fresh_store):
        a = _chunk("foo", "def foo():\n    pass\n")
        b = _chunk("bar", "def bar():\n    pass\n")
        assert fresh_store._chunk_id("proj", a) != fresh_store._chunk_id("proj", b)


class TestStalePruning:
    def test_prune_removes_orphans(self, fresh_store):
        coll = fresh_store._get_collection()
        # seed two chunks
        c1 = _chunk("foo", "def foo():\n    return 1\n")
        c2 = _chunk("bar", "def bar():\n    return 2\n")
        ids = [fresh_store._chunk_id("proj", c) for c in (c1, c2)]
        coll.upsert(ids=ids, documents=[c1.content, c2.content],
                    metadatas=[{"project": "proj", "file_path": "x", "language": "py",
                                "chunk_type": "function", "name": c1.name,
                                "start_line": 1, "end_line": 2},
                               {"project": "proj", "file_path": "x", "language": "py",
                                "chunk_type": "function", "name": c2.name,
                                "start_line": 1, "end_line": 2}])
        # now pretend only c1 is live — c2 was deleted
        deleted = fresh_store._prune_stale_chunks(coll, "proj", [ids[0]])
        assert deleted == 1
        # c2's chunk should be gone
        remaining = coll.get(where={"project": "proj"})
        assert ids[1] not in remaining["ids"]
        assert ids[0] in remaining["ids"]

    def test_prune_no_orphans_returns_zero(self, fresh_store):
        coll = fresh_store._get_collection()
        c1 = _chunk("foo", "def foo():\n    return 1\n")
        ids = [fresh_store._chunk_id("proj", c1)]
        coll.upsert(ids=ids, documents=[c1.content],
                    metadatas=[{"project": "proj", "file_path": "x", "language": "py",
                                "chunk_type": "function", "name": "foo",
                                "start_line": 1, "end_line": 2}])
        assert fresh_store._prune_stale_chunks(coll, "proj", ids) == 0


class TestIncrementalIndex:
    """Verify mtime-based incremental indexing skips unchanged files."""

    def test_invalidate_file_mtime(self, fresh_store, monkeypatch, tmp_path):
        # Seed the mtime cache with an entry, then invalidate it.
        monkeypatch.setattr(fresh_store, "_index_mtimes", {"proj": {"src/a.py": 12345}})
        fresh_store._save_index_mtimes()
        fresh_store.invalidate_file_mtime("proj", "src/a.py")
        mt = fresh_store._load_index_mtimes()
        assert "src/a.py" not in mt.get("proj", {})

    def test_index_directory_skip_paths(self, monkeypatch, tmp_path):
        from app.indexer import code_parser
        # Create two files
        (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
        # Index all
        all_chunks = code_parser.index_directory(str(tmp_path))
        names_all = {c.name for c in all_chunks}
        assert "a" in names_all and "b" in names_all
        # Index with a.py skipped
        chunks = code_parser.index_directory(str(tmp_path), skip_paths={"a.py"})
        names = {c.name for c in chunks}
        assert "a" not in names
        assert "b" in names
