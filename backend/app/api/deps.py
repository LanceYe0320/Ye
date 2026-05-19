from pathlib import Path

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import get_current_user_id
from app.storage.database import get_db
from app.storage.models import Project


async def get_verified_project(
    project_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Verify JWT auth + project ownership. Returns the Project ORM object."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    if project.user_id != user_id:
        raise HTTPException(403, "Access denied")
    return project


def project_root(project: Project) -> Path:
    """Extract resolved root path from a verified project."""
    return Path(project.path).resolve()
