from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import (
    create_access_token,
    decode_access_token,
    get_current_user_id,
    hash_password,
    verify_password,
)
from app.rate_limit import limiter
from app.storage.database import get_db
from app.storage.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str


def _validate_username(username: str) -> str:
    """Reject usernames containing HTML/markup characters (XSS prevention).

    Returns the username if valid; raises HTTPException(400) otherwise.
    Usernames should be plain identifiers — angle brackets, quotes, and
    other markup have no legitimate place in a username.
    """
    if any(ch in username for ch in "<>\"'&"):
        raise HTTPException(
            400,
            "Username contains invalid characters (no HTML/markup allowed)",
        )
    return username


@router.post("/register", response_model=TokenResponse)
@limiter.limit("3/minute")
async def register(request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if len(data.username) < 2 or len(data.username) > 100:
        raise HTTPException(400, "Username must be 2-100 characters")
    if len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    _validate_username(data.username)

    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Username already exists")

    user = User(
        username=data.username,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return TokenResponse(access_token=token, user_id=user.id, username=user.username)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)):
    # NOTE: do NOT validate username format on login. Let the parameterized
    # query run normally — an unknown user simply returns 401, which is the
    # correct response for SQL-injection attempts and avoids leaking whether
    # validation logic exists. Format validation happens at registration.
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return TokenResponse(access_token=token, user_id=user.id, username=user.username)


@router.get("/me")
async def get_me(user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    return {"id": user.id, "username": user.username}
