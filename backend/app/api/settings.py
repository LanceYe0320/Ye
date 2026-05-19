import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import get_current_user_id
from app.storage.database import get_db
from app.storage.models import UserSettings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    settings: dict


class SettingsOut(BaseModel):
    settings: dict


DEFAULT_SETTINGS = {
    "model": "glm-4-plus",
    "temperature": 0.7,
    "max_tokens": 4096,
    "theme": "dark",
    "terminal_allowlist": [],
}


async def _get_or_create_user_settings(db: AsyncSession, user_id: int) -> UserSettings:
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    us = result.scalar_one_or_none()
    if not us:
        us = UserSettings(user_id=user_id, settings_json=json.dumps(DEFAULT_SETTINGS))
        db.add(us)
        await db.commit()
        await db.refresh(us)
    return us


@router.get("/", response_model=SettingsOut)
async def get_settings(
    db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)
):
    us = await _get_or_create_user_settings(db, user_id)
    return SettingsOut(settings=json.loads(us.settings_json))


@router.put("/", response_model=SettingsOut)
async def update_settings(
    data: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    us = await _get_or_create_user_settings(db, user_id)
    current = json.loads(us.settings_json)
    current.update(data.settings)
    us.settings_json = json.dumps(current)
    await db.commit()
    await db.refresh(us)
    return SettingsOut(settings=json.loads(us.settings_json))
