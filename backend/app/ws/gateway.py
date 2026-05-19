import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.llm.base_provider import ChatMessage, StreamingChunk, ToolCall
from app.llm.tools import build_tool_executor
from app.llm.zhipu_provider import ZhipuProvider
from app.storage.database import async_session
from app.storage.models import Message, MessageRole

logger = logging.getLogger(__name__)

router = APIRouter()


def get_system_prompt() -> str:
    return """You are an AI coding assistant. You can help users with:
- Reading, writing, and editing files
- Running terminal commands
- Answering programming questions
- Debugging code
- Code review and refactoring

Use the available tools to interact with the user's file system and terminal.
Always explain what you're doing before making changes.
Be concise but thorough in your explanations."""


@router.websocket("/ws/chat/{conversation_id}")
async def websocket_chat(websocket: WebSocket, conversation_id: int):
    await websocket.accept()
    provider = ZhipuProvider()
    executor = build_tool_executor(provider)

    try:
        while True:
            data = await websocket.receive_text()
            request = json.loads(data)
            user_content = request.get("content", "")
            model = request.get("model", "glm-4-plus")

            # Save user message
            async with async_session() as db:
                msg = Message(
                    conversation_id=conversation_id,
                    role=MessageRole.USER,
                    content=user_content,
                )
                db.add(msg)
                await db.commit()

                # Load conversation history
                from sqlalchemy import select
                result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.id)
                )
                db_messages = result.scalars().all()

            # Build message list for LLM
            messages = [ChatMessage(role="system", content=get_system_prompt())]
            for m in db_messages:
                role = m.role.value if hasattr(m.role, "value") else str(m.role)
                msg_obj = ChatMessage(role=role, content=m.content)
                if m.tool_calls_json:
                    try:
                        tc_data = json.loads(m.tool_calls_json)
                        msg_obj.tool_calls = [
                            ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                            for tc in tc_data
                        ]
                    except (json.JSONDecodeError, KeyError):
                        pass
                if m.tool_call_id:
                    msg_obj.tool_call_id = m.tool_call_id
                messages.append(msg_obj)

            # Run agentic loop and stream to client
            assistant_content = ""
            tool_calls_data = []

            async for chunk in executor.run_agentic_loop(messages=messages, model=model):
                await websocket.send_text(json.dumps(_chunk_to_dict(chunk)))

                if chunk.type == "text_delta":
                    assistant_content += chunk.text
                elif chunk.type == "tool_call_end":
                    tool_calls_data.append({
                        "id": chunk.tool_call_id,
                        "name": chunk.tool_call_name,
                        "arguments": chunk.tool_call_arguments,
                    })

            # Save assistant response
            async with async_session() as db:
                msg = Message(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=assistant_content,
                    tool_calls_json=json.dumps(tool_calls_data) if tool_calls_data else None,
                )
                db.add(msg)
                await db.commit()

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "text": str(e)}))
        except Exception:
            pass


@router.websocket("/ws/terminal/{project_id}")
async def websocket_terminal(websocket: WebSocket, project_id: int):
    await websocket.accept()

    try:
        from app.api.files import get_project_root
        from app.sandbox.runner import stream_command

        async with async_session() as db:
            root = await get_project_root(project_id, db)

        current_proc = None

        while True:
            data = await websocket.receive_text()
            request = json.loads(data)

            if request.get("type") == "interrupt":
                if current_proc is not None and current_proc.returncode is None:
                    current_proc.kill()
                    await websocket.send_text(json.dumps({
                        "type": "stdout", "data": "^C\n",
                    }))
                    await websocket.send_text(json.dumps({
                        "type": "exit", "exit_code": -1,
                    }))
                continue

            command = request.get("command", "")
            if not command:
                continue

            proc_holder = {}
            async for event in stream_command(command, cwd=root, process_holder=proc_holder):
                current_proc = proc_holder.get("proc")
                await websocket.send_text(json.dumps(event))
            current_proc = None

    except WebSocketDisconnect:
        logger.info("Terminal WebSocket disconnected")
    except Exception as e:
        logger.error(f"Terminal WebSocket error: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "data": str(e)}))
        except Exception:
            pass


def _chunk_to_dict(chunk: StreamingChunk) -> dict:
    d = {"type": chunk.type}
    if chunk.text:
        d["text"] = chunk.text
    if chunk.tool_call_id:
        d["tool_call_id"] = chunk.tool_call_id
    if chunk.tool_call_name:
        d["tool_call_name"] = chunk.tool_call_name
    if chunk.tool_call_arguments:
        d["tool_call_arguments"] = chunk.tool_call_arguments
    if chunk.usage:
        d["usage"] = chunk.usage
    return d
