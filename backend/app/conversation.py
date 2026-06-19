"""Shared conversation-history helpers.

Loads DB messages into the ChatMessage list consumed by the LLM, with optional
limiting (recent window) so callers don't pull + map the entire history on
every turn. Previously this logic was duplicated in the WebSocket gateway, the
SSE endpoint, and the CLI — each with its own query, its own tool_calls_json
deserialization, and subtly different limiting behavior.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base_provider import ChatMessage, ToolCall
from app.storage.models import Message

logger = logging.getLogger(__name__)


async def load_history_as_messages(
    db: AsyncSession,
    conversation_id: int,
    limit: int | None = None,
) -> list[ChatMessage]:
    """Load a conversation's messages as ChatMessage objects.

    Args:
        db: an open async DB session.
        conversation_id: the conversation to load.
        limit: if set, only the most recent `limit` messages (chronological
            order preserved). Avoids pulling the whole history on long chats.

    Returns the messages in chronological order (oldest first), with
    tool_calls / tool_call_id deserialized from their JSON columns.
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc() if limit else Message.id)
    )
    if limit:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if limit:
        rows = list(reversed(rows))  # restore chronological order

    messages: list[ChatMessage] = []
    for m in rows:
        role = m.role.value if hasattr(m.role, "value") else str(m.role)
        msg_obj = ChatMessage(role=role, content=m.content or "")
        if m.tool_calls_json:
            try:
                tc_data = json.loads(m.tool_calls_json)
                msg_obj.tool_calls = [
                    ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                    for tc in tc_data
                ]
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.debug("suppressed", exc_info=True)
        if m.tool_call_id:
            msg_obj.tool_call_id = m.tool_call_id
        messages.append(msg_obj)
    return messages
