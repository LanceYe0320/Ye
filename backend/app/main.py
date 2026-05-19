import logging

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.storage.database import init_db

logging.basicConfig(level=logging.INFO if not settings.DEBUG else logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME, version=settings.VERSION)

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
from app.api.projects import router as projects_router
from app.api.files import router as files_router
from app.api.terminal import router as terminal_router
from app.api.conversations import router as conversations_router
from app.api.settings import router as settings_router
from app.api.search import router as search_router
from app.api.plugins import router as plugins_router
from app.api.git import router as git_router
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
