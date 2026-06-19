import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)

# Tuned for SQLite: WAL journaling (concurrent readers + 1 writer),
# NORMAL synchronous (much faster fsync, safe with WAL), a 30s busy timeout
# to tolerate write contention. echo=False keeps SQL out of the logs even when
# DEBUG=True (SQL echo is dev-noise that hurts throughput).
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30, "check_same_thread": False},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Apply connection-level pragmas on every new SQLite connection. journal_mode=WAL
# persists at the DB level, but synchronous/cache_size are per-connection.
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")  # 30s
    finally:
        cursor.close()


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
        # Enable WAL + tune pragmas for concurrency/throughput. WAL allows
        # concurrent readers alongside a writer, which the default (DELETE)
        # journal mode serializes. synchronous=NORMAL is safe under WAL and
        # avoids an fsync per commit.
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA synchronous=NORMAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)
