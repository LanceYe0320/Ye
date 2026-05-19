import hashlib
import logging

import chromadb

from app.config import settings
from app.indexer.code_parser import CodeChunk, index_directory, index_file

logger = logging.getLogger(__name__)

_collection = None

_CHROMA_DIR = settings.DATA_DIR / "chroma"


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
    raw = f"{project_path}:{chunk.file_path}:{chunk.start_line}:{chunk.name}"
    return hashlib.md5(raw.encode()).hexdigest()


def index_project(project_path: str):
    chunks = index_directory(project_path)
    collection = _get_collection()

    if not chunks:
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

    logger.info(f"Indexed {len(chunks)} chunks for project {project_path}")
    return len(chunks)


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
