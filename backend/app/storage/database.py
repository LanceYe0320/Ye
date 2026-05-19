import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    from app.storage.models import Base

    try:
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        settings.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("Failed to create data directories: %s", e)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
