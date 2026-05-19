from httpx import AsyncClient


async def test_register(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={
        "username": "newuser",
        "password": "password123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["username"] == "newuser"


async def test_register_duplicate(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "dupuser",
        "password": "password123",
    })
    resp = await client.post("/api/auth/register", json={
        "username": "dupuser",
        "password": "password123",
    })
    assert resp.status_code == 409


async def test_register_short_password(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={
        "username": "shortpw",
        "password": "12345",
    })
    assert resp.status_code == 400


async def test_login(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "loginuser",
        "password": "password123",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "loginuser",
        "password": "password123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "wrongpw",
        "password": "password123",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "wrongpw",
        "password": "wrong",
    })
    assert resp.status_code == 401
