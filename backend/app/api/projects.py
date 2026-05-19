from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import get_current_user_id
from app.storage.database import get_db
from app.storage.models import Project

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    path: str


class ProjectOut(BaseModel):
    id: int
    name: str
    path: str


@router.get("/", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)
):
    result = await db.execute(select(Project).where(Project.user_id == user_id))
    return result.scalars().all()


@router.post("/", response_model=ProjectOut)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    project_path = Path(data.path).resolve()
    if not project_path.exists():
        raise HTTPException(400, f"Path does not exist: {data.path}")
    project = Project(name=data.name, path=str(project_path), user_id=user_id)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}")
async def delete_project(
    project_id: int, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)
):
    project = await db.get(Project, project_id)
    if not project or project.user_id != user_id:
        raise HTTPException(404, "Project not found")
    await db.delete(project)
    await db.commit()
    return {"ok": True}
