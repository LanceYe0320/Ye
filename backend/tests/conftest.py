import asyncio

import pytest

# Try to import the full app — skip integration tests if dependencies are missing
try:
    from app.main import app
    from app.storage.database import engine, init_db
    from app.storage.models import Base
    _HAS_FULL_APP = True
    # Disable rate limiting during tests — the test suite fires many rapid
    # requests through the ASGI transport and would otherwise hit 429s.
    try:
        from app.rate_limit import limiter
        limiter.enabled = False
    except Exception:
        pass
except ImportError:
    _HAS_FULL_APP = False


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_db():
    if not _HAS_FULL_APP:
        yield
        return
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
    if not _HAS_FULL_APP:
        pytest.skip("Full app dependencies not available")
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_token(client):
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
async def project_id(client, auth_headers: dict, tmp_path):
    resp = await client.post("/api/projects/", json={
        "name": "Test Project",
        "path": str(tmp_path),
    }, headers=auth_headers)
    assert resp.status_code == 200
    return resp.json()["id"]
