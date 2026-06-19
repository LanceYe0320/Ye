from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.auth.jwt_handler import decode_access_token
from app.llm.base_provider import ChatMessage, StreamingChunk, ToolCall
from app.llm.tools import build_tool_executor
from app.llm.zhipu_provider import ZhipuProvider
from app.storage.database import async_session
from app.storage.models import Conversation, Message, MessageRole

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Provider Singleton: shared across all WebSocket connections ---
_provider_instance: ZhipuProvider | None = None


def get_shared_provider() -> ZhipuProvider:
    """Get or create the shared ZhipuProvider singleton.

    Reusing one provider across connections avoids:
      - Re-creating HTTP client pools per connection
      - Duplicate TCP+TLS handshakes to the API
      - Wasting memory on per-connection caches
    """
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = ZhipuProvider()
        logger.info("Created shared ZhipuProvider singleton")
    return _provider_instance


_mcp_session_instance = None


async def get_shared_mcp_session():
    """Get or create the shared MCP ClientSession (lazy, process-global).

    Connected once; its discovered tools are registered into every WS
    executor via _register_mcp_into(). Returns None if no servers configured.
    """
    global _mcp_session_instance
    if _mcp_session_instance is not None:
        return _mcp_session_instance
    from app.mcp_client import ClientSession, load_server_configs
    configs = load_server_configs()
    if not configs:
        return None
    _mcp_session_instance = ClientSession()
    try:
        await _mcp_session_instance.connect(configs)
    except Exception as e:
        logger.warning(f"MCP connect failed: {e}")
    return _mcp_session_instance


async def _register_mcp_into(executor) -> int:
    """Register MCP tools into a WS executor (no-op if MCP unavailable)."""
    sess = await get_shared_mcp_session()
    if sess is None or not sess.is_connected:
        return 0
    from app.llm.tools import register_mcp_tools
    return register_mcp_tools(executor, sess)


def _ws_auth(websocket: WebSocket) -> int | None:
    """Extract and validate JWT from WebSocket query params or headers.
    Returns user_id or None.

    Delegates to app.ws.sync_handler._extract_ws_user_id (single source of truth).
    """
    # Lazy import to avoid circular dependency at module load time
    from app.ws.sync_handler import _extract_ws_user_id
    return _extract_ws_user_id(websocket)


_ws_system_prompt_cache: str | None = None
_ws_skills_injected: bool = False


def get_system_prompt() -> str:
    """Get the system prompt for WebSocket connections — uses centralized prompts.py.

    The WS prompt is constant for the lifetime of the process, so it's built
    once and cached (previously rebuilt on every incoming message). Available
    Skills are appended to the cached prompt once.
    """
    global _ws_system_prompt_cache, _ws_skills_injected
    if _ws_system_prompt_cache is None:
        from app.prompts import SystemPrompt
        _ws_system_prompt_cache = SystemPrompt.build(is_websocket=True)
    if not _ws_skills_injected:
        from app.skills import discover_skills, render_skills_for_prompt
        skills_ctx = render_skills_for_prompt(discover_skills())
        if skills_ctx:
            _ws_system_prompt_cache = _ws_system_prompt_cache + skills_ctx
        _ws_skills_injected = True
    return _ws_system_prompt_cache


def _build_harness_executor(provider: ZhipuProvider) -> tuple:
    """Build a ToolExecutor with full Harness (Registry + Budget + Trace + FailureHandler).

    Returns (executor, registry) so callers can reuse the registry across turns.
    Budget, Trace, and FailureHandler are created per-turn.
    """
    from app.tool_registry import get_registry
    from app.failure import FailureHandler

    executor = build_tool_executor(provider)
    registry = get_registry()
    executor.set_registry(registry)
    return executor, registry


def _create_turn_harness(session_id: str = "") -> tuple:
    """Create fresh Budget, Trace, and FailureHandler for one conversation turn.

    Returns (budget, trace, failure_handler).
    """
    from app.budget import TokenBudget, BudgetConfig
    from app.execution_trace import ExecutionTrace
    from app.failure import FailureHandler

    budget = TokenBudget(BudgetConfig(
        max_total_tokens=200_000,
        max_tool_calls=50,
        max_duration_seconds=300,
        enabled=True,
    ))
    budget.start()

    trace = ExecutionTrace(session_id=session_id)

    failure_handler = FailureHandler()
    return budget, trace, failure_handler


@router.websocket("/ws/chat/{conversation_id}")
async def websocket_chat(websocket: WebSocket, conversation_id: int):
    # Auth check
    user_id = _ws_auth(websocket)
    if user_id is None:
        await websocket.close(code=4001, reason="Authentication required")
        return

    # Verify conversation ownership
    async with async_session() as db:
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()
        if not conversation or conversation.user_id != user_id:
            await websocket.close(code=4003, reason="Conversation not found or access denied")
            return

    await websocket.accept()
    provider = get_shared_provider()
    executor, _registry = _build_harness_executor(provider)

    # Register MCP tools (if any servers are configured) into this executor.
    try:
        await _register_mcp_into(executor)
    except Exception as e:
        logger.debug(f"MCP register (ws): {e}")

    # Per-connection TodoList (TodoWrite). Bound each turn so the todo_write
    # tool works over WebSocket the same way it does in the CLI.
    from app.todo_store import TodoList
    from app.llm.tools.todo_ops import set_active_todos
    conn_todos = TodoList()

    try:
        while True:
            data = await websocket.receive_text()
            request = json.loads(data)
            user_content = request.get("content", "")
            model = request.get("model", "glm-4-plus")

            # --- Harness: fresh per-turn controls ---
            session_id = f"ws-{conversation_id}"
            turn_budget, turn_trace, turn_failures = _create_turn_harness(session_id)
            turn_trace.start(user_content)
            executor.set_budget(turn_budget)
            executor.set_trace(turn_trace)
            executor.set_failure_handler(turn_failures)
            # Bind the connection's todo list for this turn.
            set_active_todos(conn_todos)

            # Save user message
            async with async_session() as db:
                msg = Message(
                    conversation_id=conversation_id,
                    role=MessageRole.USER,
                    content=user_content,
                )
                db.add(msg)
                await db.commit()

                # Load conversation history via the shared helper (avoids
                # duplicating the query + tool_calls_json deserialization).
                from app.conversation import load_history_as_messages
                db_messages = await load_history_as_messages(db, conversation_id)

            # Build message list for LLM
            messages = [ChatMessage(role="system", content=get_system_prompt())]
            messages.extend(db_messages)

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
                elif chunk.type == "usage":
                    # Send budget zone to client so UI can show cost status
                    zone = turn_budget.check_zone().value
                    tokens = turn_budget.state.total_tokens_used
                    await websocket.send_text(json.dumps({
                        "type": "harness_budget",
                        "zone": zone,
                        "tokens_used": tokens,
                        "max_tokens": turn_budget.config.max_total_tokens,
                    }))

            # --- Harness: finalize trace ---
            turn_trace.finish(output=assistant_content[:500])

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
            logger.debug("suppressed error", exc_info=True)


@router.websocket("/ws/terminal/{project_id}")
async def websocket_terminal(websocket: WebSocket, project_id: int):
    # Auth check
    user_id = _ws_auth(websocket)
    if user_id is None:
        await websocket.close(code=4001, reason="Authentication required")
        return

    try:
        from app.api.deps import project_root
        from app.sandbox.runner import stream_command
        from app.storage.models import Project

        # Verify project ownership
        async with async_session() as db:
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project or project.user_id != user_id:
                await websocket.close(code=4003, reason="Project not found or access denied")
                return
            root = project_root(project)

        await websocket.accept()

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
            logger.debug("suppressed error", exc_info=True)


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
