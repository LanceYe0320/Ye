import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.rate_limit import limiter
from app.storage.database import init_db

logging.basicConfig(level=logging.INFO if not settings.DEBUG else logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME, version=settings.VERSION)

# ---- Rate limiting (slowapi) ---------------------------------------------
# Limiter is created in app.rate_limit so routers can import the same instance.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info(f"{settings.APP_NAME} v{settings.VERSION} started")
    logger.info(f"Zhipu model: {settings.ZHIPU_MODEL}")


from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.files import router as files_router
from app.api.git import router as git_router
from app.api.plugins import router as plugins_router
from app.api.projects import router as projects_router
from app.api.search import router as search_router
from app.api.settings import router as settings_router
from app.api.terminal import router as terminal_router
from app.ws.gateway import router as ws_router
from app.ws.sync_handler import sync_manager

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(files_router)
app.include_router(terminal_router)
app.include_router(conversations_router)
app.include_router(settings_router)
app.include_router(search_router)
app.include_router(plugins_router)
app.include_router(git_router)
app.include_router(ws_router)


@app.websocket("/ws/sync")
async def ws_sync(websocket: WebSocket):
    await sync_manager.handle_connection(websocket)


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.VERSION,
        "status": "running",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# ===== Static files (Web UI) =====
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ===== Web Chat SSE endpoint =====
import json
from fastapi import Depends
from fastapi.responses import StreamingResponse
from app.auth.jwt_handler import get_current_user_id
from app.storage.database import get_db
from app.storage.models import Conversation, Message, MessageRole
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel


class WebChatRequest(BaseModel):
    content: str
    model: str = "glm-5.1"
    stream: bool = True


@app.post("/api/conversations/{conv_id}/messages")
async def send_web_message(
    conv_id: int,
    data: WebChatRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Send a message and stream the AI response via SSE."""
    # Verify conversation ownership
    conv = await db.get(Conversation, conv_id)
    if not conv or conv.user_id != user_id:
        from fastapi import HTTPException
        raise HTTPException(404, "Conversation not found")

    # Save user message
    user_msg = Message(
        conversation_id=conv_id,
        role=MessageRole.user,
        content=data.content,
    )
    db.add(user_msg)
    await db.commit()

    # Auto-title on first message
    if not conv.title or conv.title == "新对话" or conv.title == "New Conversation":
        conv.title = data.content[:40] + ("..." if len(data.content) > 40 else "")
        await db.commit()

    async def generate():
        try:
            # Reuse the shared system prompt (includes Skills discovery) so the
            # SSE path stays consistent with the WebSocket path.
            from app.ws.gateway import get_shared_provider, get_system_prompt
            from app.llm.base_provider import ChatMessage
            from app.conversation import load_history_as_messages

            # Load only the recent window of history via the shared helper
            # (avoids loading + mapping the entire conversation every request).
            recent = await load_history_as_messages(db, conv_id, limit=20)

            system_msg = ChatMessage(role="system", content=get_system_prompt())

            history = [system_msg] + recent

            provider = get_shared_provider()
            full_response_parts: list[str] = []
            total_tokens = 0

            async for chunk in provider.chat(
                messages=history,
                model=data.model,
                temperature=0.7,
                max_tokens=4096,
            ):
                if chunk.type == "text_delta":
                    full_response_parts.append(chunk.text)
                    sse_data = json.dumps({"type": "content", "content": chunk.text}, ensure_ascii=False)
                    yield f"data: {sse_data}\n\n"
                elif chunk.type == "tool_call_start":
                    sse_data = json.dumps({"type": "tool_call", "id": chunk.tool_call_id}, ensure_ascii=False)
                    yield f"data: {sse_data}\n\n"
                elif chunk.type == "tool_call_delta":
                    sse_data = json.dumps({"type": "tool_call", "id": chunk.tool_call_id, "name": chunk.tool_call_name}, ensure_ascii=False)
                    yield f"data: {sse_data}\n\n"
                elif chunk.type == "tool_call_end":
                    sse_data = json.dumps({"type": "tool_result", "id": chunk.tool_call_id, "name": chunk.tool_call_name}, ensure_ascii=False)
                    yield f"data: {sse_data}\n\n"
                elif chunk.type == "usage":
                    total_tokens = chunk.usage.get("total_tokens", 0)
                    sse_data = json.dumps({"type": "usage", "tokens": total_tokens}, ensure_ascii=False)
                    yield f"data: {sse_data}\n\n"
                elif chunk.type == "error":
                    sse_data = json.dumps({"type": "error", "content": chunk.text}, ensure_ascii=False)
                    yield f"data: {sse_data}\n\n"
                elif chunk.type == "done":
                    break

            # Save assistant response
            full_response = "".join(full_response_parts)
            if full_response:
                assistant_msg = Message(
                    conversation_id=conv_id,
                    role=MessageRole.assistant,
                    content=full_response,
                )
                db.add(assistant_msg)
                await db.commit()

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Web chat error: {e}")
            error_data = json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Serve index.html at /web
@app.get("/web")
async def web_ui():
    from fastapi.responses import FileResponse
    index_path = _static_dir / "index.html"
    if index_path.is_file():
        return FileResponse(str(index_path), media_type="text/html")
    return {"error": "Web UI not found"}
