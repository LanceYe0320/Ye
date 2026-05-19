from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import get_current_user_id
from app.plugins.manager import plugin_manager
from app.storage.database import get_db
from app.storage.models import Project

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.get("/")
async def list_plugins():
    return {
        "installed": plugin_manager.discover_plugins(),
        "active": plugin_manager.list_active_plugins(),
    }


@router.post("/{plugin_name}/activate")
async def activate_plugin(
    plugin_name: str,
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        return {"ok": False, "error": "Project not found"}
    success = await plugin_manager.activate_plugin(plugin_name, project.path)
    return {"ok": success}


@router.post("/{plugin_name}/deactivate")
async def deactivate_plugin(plugin_name: str):
    success = await plugin_manager.deactivate_plugin(plugin_name)
    return {"ok": success}
