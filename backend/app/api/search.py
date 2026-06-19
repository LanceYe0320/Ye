from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from app.api.deps import get_verified_project
from app.indexer.vector_store import index_project, search_code
from app.storage.models import Project

router = APIRouter(prefix="/api/projects/{project_id}", tags=["search"])


class SearchQuery(BaseModel):
    query: str
    n_results: int = 10


class SearchResult(BaseModel):
    id: str
    content: str
    metadata: dict
    distance: Optional[float] = None


class IndexResponse(BaseModel):
    indexed_chunks: int


@router.post("/index")
async def trigger_index(
    project_id: int,
    background_tasks: BackgroundTasks,
    project: Project = Depends(get_verified_project),
):
    project_path = project.path
    # index_project does CPU-bound parsing + embedding; run off the event loop.
    count = await asyncio.to_thread(index_project, project_path)
    return {"indexed_chunks": count, "status": "completed"}


@router.post("/search", response_model=List[SearchResult])
async def semantic_search(
    project_id: int,
    query: SearchQuery,
    project: Project = Depends(get_verified_project),
):
    project_path = project.path
    # search_code runs the embedding model + ChromaDB query synchronously and is
    # CPU/IO-bound — offload it so it doesn't block the FastAPI event loop.
    results = await asyncio.to_thread(
        search_code, query.query, project_path=project_path, n_results=query.n_results
    )
    return [SearchResult(**r) for r in results]
