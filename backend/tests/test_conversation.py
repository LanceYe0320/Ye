"""Tests for the shared conversation history loader."""
from __future__ import annotations

import pytest

from app.conversation import load_history_as_messages
from app.storage.models import Conversation, Message, MessageRole


class TestLoadHistoryAsMessages:
    @pytest.mark.asyncio
    async def test_empty_conversation(self, db_session):
        msgs = await load_history_as_messages(db_session, conversation_id=999)
        assert msgs == []

    @pytest.mark.asyncio
    async def test_loads_messages_chronologically(self, db_session, tmp_path):
        # Create a conversation + a few messages
        conv = Conversation(user_id=1, title="t")
        db_session.add(conv)
        await db_session.flush()
        cid = conv.id
        m1 = Message(conversation_id=cid, role=MessageRole.USER, content="hello")
        m2 = Message(conversation_id=cid, role=MessageRole.ASSISTANT, content="hi there")
        db_session.add_all([m1, m2])
        await db_session.commit()

        msgs = await load_history_as_messages(db_session, cid)
        assert len(msgs) == 2
        assert msgs[0].content == "hello"
        assert msgs[1].content == "hi there"

    @pytest.mark.asyncio
    async def test_limit_returns_recent(self, db_session, tmp_path):
        conv = Conversation(user_id=1, title="t")
        db_session.add(conv)
        await db_session.flush()
        cid = conv.id
        for i in range(5):
            db_session.add(Message(
                conversation_id=cid, role=MessageRole.USER, content=f"msg-{i}"
            ))
        await db_session.commit()

        msgs = await load_history_as_messages(db_session, cid, limit=2)
        assert len(msgs) == 2
        # Should be the most recent 2, in chronological order
        assert msgs[0].content == "msg-3"
        assert msgs[1].content == "msg-4"

    @pytest.mark.asyncio
    async def test_deserializes_tool_calls(self, db_session, tmp_path):
        import json
        conv = Conversation(user_id=1, title="t")
        db_session.add(conv)
        await db_session.flush()
        cid = conv.id
        db_session.add(Message(
            conversation_id=cid,
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls_json=json.dumps([
                {"id": "call_1", "name": "read_file", "arguments": {"path": "x.py"}}
            ]),
        ))
        await db_session.commit()
        msgs = await load_history_as_messages(db_session, cid)
        assert len(msgs) == 1
        assert msgs[0].tool_calls is not None
        assert len(msgs[0].tool_calls) == 1
        assert msgs[0].tool_calls[0].name == "read_file"

    @pytest.mark.asyncio
    async def test_bad_tool_calls_json_skipped(self, db_session, tmp_path):
        conv = Conversation(user_id=1, title="t")
        db_session.add(conv)
        await db_session.flush()
        cid = conv.id
        db_session.add(Message(
            conversation_id=cid, role=MessageRole.ASSISTANT, content="c",
            tool_calls_json="{bad json",
        ))
        await db_session.commit()
        msgs = await load_history_as_messages(db_session, cid)
        assert len(msgs) == 1
        # tool_calls stays empty/default (bad json swallowed)
        assert msgs[0].content == "c"


# Provide a db_session fixture (autocommit AsyncSession) for these tests.
# Reuses the engine from the app's storage layer with rollback isolation.
@pytest.fixture
async def db_session():
    from app.storage.database import async_session, init_db
    from app.storage.models import Base, User
    await init_db()
    async with async_session() as session:
        # Clean slate
        for tbl in reversed(Base.metadata.sorted_tables):
            await session.execute(tbl.delete())
        await session.commit()
        # Seed a user (id=1) so Conversation.user_id FK is satisfied.
        session.add(User(username="tester", hashed_password="x"))
        await session.commit()
        yield session
        for tbl in reversed(Base.metadata.sorted_tables):
            await session.execute(tbl.delete())
        await session.commit()
