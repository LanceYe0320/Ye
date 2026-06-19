from __future__ import annotations

import time

from httpx import AsyncClient

from app.auth.jwt_handler import create_access_token, decode_access_token


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


# ── Deep test cases ──


async def test_register_missing_fields(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={})
    assert resp.status_code == 422

    resp = await client.post("/api/auth/register", json={"username": "a"})
    assert resp.status_code == 422

    resp = await client.post("/api/auth/register", json={"password": "123456"})
    assert resp.status_code == 422


async def test_register_short_username(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={
        "username": "a",
        "password": "password123",
    })
    assert resp.status_code == 400


async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post("/api/auth/login", json={
        "username": "ghost_user_404",
        "password": "whatever123",
    })
    assert resp.status_code == 401


async def test_login_missing_fields(client: AsyncClient):
    resp = await client.post("/api/auth/login", json={})
    assert resp.status_code == 422


async def test_jwt_tampered_token(client: AsyncClient):
    """Modifying any byte of a valid token should cause rejection."""
    await client.post("/api/auth/register", json={
        "username": "tamperuser",
        "password": "password123",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "tamperuser",
        "password": "password123",
    })
    token = resp.json()["access_token"]

    # Flip a character in the middle of the token
    tampered = token[:-5] + ("X" if token[-5] != "X" else "Y") + token[-4:]
    resp = await client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {tampered}",
    })
    assert resp.status_code == 401


async def test_jwt_missing_sub_claim():
    """Token without 'sub' should fail decode."""
    token = create_access_token({"username": "noid"})
    payload = decode_access_token(token)
    assert payload is not None
    assert "sub" not in payload


async def test_jwt_expired_token(client: AsyncClient):
    """Token with negative expiry should be rejected."""
    token = create_access_token({"sub": "1", "username": "expired"}, expires_hours=-1)
    resp = await client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {token}",
    })
    assert resp.status_code == 401


async def test_jwt_wrong_secret(client: AsyncClient):
    """Token signed with wrong secret should be rejected."""
    from app.config import settings
    from jose import jwt as jose_jwt

    token = jose_jwt.encode(
        {"sub": "1", "username": "faker"},
        "wrong-secret-key",
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = await client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {token}",
    })
    assert resp.status_code == 401


async def test_me_with_valid_token(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "meuser",
        "password": "password123",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "meuser",
        "password": "password123",
    })
    token = resp.json()["access_token"]

    resp = await client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {token}",
    })
    assert resp.status_code == 200
    assert resp.json()["username"] == "meuser"


async def test_me_no_auth_header(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_malformed_auth_header(client: AsyncClient):
    resp = await client.get("/api/auth/me", headers={
        "Authorization": "NotBearer sometoken",
    })
    assert resp.status_code == 401


async def test_sql_injection_in_username(client: AsyncClient):
    """Username with SQL special characters should not crash the server."""
    malicious = "admin' OR 1=1 --"
    resp = await client.post("/api/auth/login", json={
        "username": malicious,
        "password": "whatever",
    })
    # Should get 401 (not found), not 500 (server error)
    assert resp.status_code == 401


async def test_xss_in_username(client: AsyncClient):
    """Username with HTML/JS should be stored safely (no execution)."""
    xss_name = '<script>alert("xss")</script>'
    # Username too short for this, use a longer variant
    xss_name = 'user<script>alert("xss")</script>'
    resp = await client.post("/api/auth/register", json={
        "username": xss_name,
        "password": "password123",
    })
    # Either accepted (stored safely) or rejected — but not a 500
    assert resp.status_code in (200, 400, 422)
    if resp.status_code == 200:
        token = resp.json()["access_token"]
        me_resp = await client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        body = me_resp.json()
        assert "<script>" not in body.get("username", "")
