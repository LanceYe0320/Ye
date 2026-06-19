from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import get_current_user_id
from app.storage.database import get_db
from app.storage.models import Conversation, Message, MessageRole

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = "New Conversation"
    project_id: Optional[int] = None
    model: str = "glm-4-plus"


class ConversationUpdate(BaseModel):
    title: Optional[str] = None


class ConversationOut(BaseModel):
    id: int
    title: str
    model: str
    project_id: Optional[int] = None

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    tool_calls_json: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


@router.get("/", response_model=List[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=ConversationOut)
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    conv = Conversation(
        title=data.title,
        project_id=data.project_id,
        user_id=user_id,
        model=data.model,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(
    conv_id: int, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)
):
    conv = await db.get(Conversation, conv_id)
    if not conv or conv.user_id != user_id:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.put("/{conv_id}", response_model=ConversationOut)
async def update_conversation(
    conv_id: int,
    data: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    conv = await db.get(Conversation, conv_id)
    if not conv or conv.user_id != user_id:
        raise HTTPException(404, "Conversation not found")
    if data.title is not None:
        conv.title = data.title
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/{conv_id}/messages", response_model=List[MessageOut])
async def get_messages(
    conv_id: int, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)
):
    conv = await db.get(Conversation, conv_id)
    if not conv or conv.user_id != user_id:
        raise HTTPException(404, "Conversation not found")
    result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.id)
    )
    messages = result.scalars().all()
    return [
        MessageOut(
            id=m.id,
            role=m.role.value if isinstance(m.role, MessageRole) else str(m.role),
            content=m.content,
            tool_calls_json=m.tool_calls_json,
            created_at=str(m.created_at),
        )
        for m in messages
    ]


@router.delete("/{conv_id}")
async def delete_conversation(
    conv_id: int, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)
):
    conv = await db.get(Conversation, conv_id)
    if not conv or conv.user_id != user_id:
        raise HTTPException(404, "Conversation not found")
    await db.execute(delete(Message).where(Message.conversation_id == conv_id))
    await db.delete(conv)
    await db.commit()
    return {"ok": True}
