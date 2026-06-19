from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import chromadb

from app.config import settings
from app.indexer.code_parser import CodeChunk, index_directory, index_file

logger = logging.getLogger(__name__)

_collection = None

_CHROMA_DIR = settings.DATA_DIR / "chroma"
# Per-project mtime cache: {project_path: {rel_path: mtime_ns_int}}. Files
# whose mtime hasn't changed since the last index are skipped (no re-parse,
# no re-embed). Persisted to disk so it survives across runs.
_INDEX_META_FILE = settings.DATA_DIR / "index_mtimes.json"
_index_mtimes: dict[str, dict[str, int]] | None = None


def _load_index_mtimes() -> dict[str, dict[str, int]]:
    """Load the mtime cache (lazy, module-level singleton)."""
    global _index_mtimes
    if _index_mtimes is not None:
        return _index_mtimes
    try:
        if _INDEX_META_FILE.is_file():
            _index_mtimes = json.loads(_INDEX_META_FILE.read_text(encoding="utf-8"))
        else:
            _index_mtimes = {}
    except Exception:
        logger.debug("suppressed", exc_info=True)
        _index_mtimes = {}
    return _index_mtimes


def _save_index_mtimes() -> None:
    try:
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _INDEX_META_FILE.write_text(
            json.dumps(_index_mtimes or {}, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        logger.debug("suppressed", exc_info=True)


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        _collection = client.get_or_create_collection(
            name="code_chunks",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _chunk_id(project_path: str, chunk: CodeChunk) -> str:
    """Stable ID for a code chunk.

    Includes a content hash so that editing a function's body (without moving
    or renaming it) produces a NEW id. This makes incremental re-indexing
    detect content changes: the upsert inserts the fresh chunk, and stale
    chunks are pruned by _prune_stale_chunks(). Without the content hash,
    stale code could linger and be returned by semantic search.
    """
    content_hash = hashlib.md5(chunk.content.encode()).hexdigest()[:12]
    raw = f"{project_path}:{chunk.file_path}:{chunk.start_line}:{chunk.name}:{content_hash}"
    return hashlib.md5(raw.encode()).hexdigest()


def _prune_stale_chunks(collection, project_path: str, live_ids: list[str]) -> int:
    """Delete chunks for a project that aren't in live_ids (orphans).

    Happens when code is deleted, renamed, or its content changed enough to
    produce a new content-hashed id. Returns the number deleted.
    """
    if not live_ids:
        return 0
    live_set = set(live_ids)
    try:
        result = collection.get(where={"project": project_path})
    except Exception:
        logger.debug("suppressed", exc_info=True)
        return 0
    stale = [i for i in result.get("ids", []) if i not in live_set]
    if stale:
        collection.delete(ids=stale)
        logger.debug(f"Pruned {len(stale)} stale chunks for {project_path}")
    return len(stale)


def index_project(project_path: str):
    """Index a project, skipping files unchanged since the last index.

    Uses a per-file mtime cache (~/.ye/index_mtimes.json): files whose mtime
    matches the cached value are neither re-parsed nor re-embedded. Deleted
    files (present in cache but absent on disk) have their chunks pruned.
    """
    collection = _get_collection()
    root = Path(project_path)
    mtimes = _load_index_mtimes()
    cached = mtimes.get(project_path, {})

    # Walk the project, splitting files into "unchanged" (skip) vs "to index".
    skip_paths: set[str] = set()
    current_files: dict[str, int] = {}
    for filepath in root.rglob('*'):
        if not filepath.is_file():
            continue
        rel = str(filepath.relative_to(root)).replace('\\', '/')
        # Reuse code_parser's filter so we skip the same non-code files.
        from app.indexer.code_parser import should_index
        if not should_index(rel):
            continue
        try:
            mtime = filepath.stat().st_mtime_ns
        except OSError:
            continue
        current_files[rel] = mtime
        if cached.get(rel) == mtime:
            skip_paths.add(rel)  # unchanged — no need to re-index

    # Detect deleted files (were indexed, now gone) for pruning.
    deleted_files = set(cached.keys()) - set(current_files.keys())

    if skip_paths:
        logger.info(f"Incremental index: skipping {len(skip_paths)} unchanged files in {project_path}")

    chunks = index_directory(project_path, skip_paths=skip_paths)

    if not chunks and not deleted_files:
        # Update mtime cache even if nothing to do (cheap)
        mtimes[project_path] = current_files
        _save_index_mtimes()
        return 0

    ids = [_chunk_id(project_path, c) for c in chunks]
    documents = [c.content for c in chunks]
    metadatas = [
        {
            "file_path": c.file_path,
            "language": c.language,
            "chunk_type": c.chunk_type,
            "name": c.name,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "project": project_path,
        }
        for c in chunks
    ]

    batch_size = 500
    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i:i + batch_size]
        batch_docs = documents[i:i + batch_size]
        batch_meta = metadatas[i:i + batch_size]
        collection.upsert(ids=batch_ids, documents=batch_docs, metadatas=batch_meta)

    # Prune: (a) orphans from this incremental pass, (b) deleted files' chunks.
    if deleted_files:
        _delete_file_chunks(collection, project_path, list(deleted_files))
    _prune_stale_chunks(collection, project_path, ids)

    # Persist the updated mtime cache.
    mtimes[project_path] = current_files
    _save_index_mtimes()

    logger.info(f"Indexed {len(chunks)} chunks (re-parsed) for project {project_path}")
    return len(chunks)


def _delete_file_chunks(collection, project_path: str, file_paths: list[str]) -> int:
    """Delete all chunks belonging to the given file paths in a project."""
    if not file_paths:
        return 0
    deleted = 0
    for fp in file_paths:
        try:
            collection.delete(where={"project": project_path, "file_path": fp})
            deleted += 1
        except Exception:
            logger.debug("suppressed", exc_info=True)
    if deleted:
        logger.debug(f"Deleted chunks for {deleted} removed files in {project_path}")
    return deleted


def invalidate_file_mtime(project_path: str, file_path: str) -> None:
    """Mark a file's mtime cache entry as stale so the next index picks it up.

    Called after edit_file/write_file so the incremental indexer re-parses
    changed files on the next index_project run, without paying embedding
    cost on every edit.
    """
    mtimes = _load_index_mtimes()
    proj = mtimes.get(project_path)
    if proj is not None and file_path in proj:
        # Force re-index by dropping the entry; index_project will re-add it.
        del proj[file_path]
        _save_index_mtimes()


def index_file_update(project_path: str, file_path: str, content: str):
    chunks = index_file(file_path, content)
    collection = _get_collection()

    # Remove old chunks for this file
    collection.delete(where={"file_path": file_path, "project": project_path})

    if not chunks:
        return 0

    for chunk in chunks:
        chunk.file_path = file_path

    ids = [_chunk_id(project_path, c) for c in chunks]
    documents = [c.content for c in chunks]
    metadatas = [
        {
            "file_path": c.file_path,
            "language": c.language,
            "chunk_type": c.chunk_type,
            "name": c.name,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "project": project_path,
        }
        for c in chunks
    ]

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(chunks)


def search_code(query: str, project_path: str | None = None, n_results: int = 10) -> list[dict]:
    collection = _get_collection()

    where_filter = {"project": project_path} if project_path else None

    kwargs = {
        "query_texts": [query],
        "n_results": min(n_results, 50),
    }
    if where_filter:
        kwargs["where"] = where_filter

    try:
        results = collection.query(**kwargs)
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

    items = []
    for i in range(len(results["ids"][0])):
        items.append({
            "id": results["ids"][0][i],
            "content": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i] if results.get("distances") else None,
        })
    return items
