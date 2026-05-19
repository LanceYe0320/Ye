import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.storage.database import init_db, engine
from app.storage.models import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    yield
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_token(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={
        "username": "testuser",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
async def auth_headers(auth_token: str):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
async def project_id(client: AsyncClient, auth_headers: dict, tmp_path):
    resp = await client.post("/api/projects/", json={
        "name": "Test Project",
        "path": str(tmp_path),
    }, headers=auth_headers)
    assert resp.status_code == 200
    return resp.json()["id"]
