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
    distance: float | None = None


class IndexResponse(BaseModel):
    indexed_chunks: int


@router.post("/index")
async def trigger_index(
    project_id: int,
    background_tasks: BackgroundTasks,
    project: Project = Depends(get_verified_project),
):
    project_path = project.path
    import asyncio
    loop = asyncio.get_event_loop()
    count = await loop.run_in_executor(None, index_project, project_path)
    return {"indexed_chunks": count, "status": "completed"}


@router.post("/search", response_model=list[SearchResult])
async def semantic_search(
    project_id: int,
    query: SearchQuery,
    project: Project = Depends(get_verified_project),
):
    project_path = project.path
    results = search_code(query.query, project_path=project_path, n_results=query.n_results)
    return [SearchResult(**r) for r in results]
