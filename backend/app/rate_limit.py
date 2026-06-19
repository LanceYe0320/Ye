"""Shared rate-limiting configuration.

The Limiter instance is created here and attached to the FastAPI app in
main.py. Import this module in any router that needs rate limiting.

Example::

    from app.rate_limit import limiter
    @router.post("/login")
    @limiter.limit("5/minute")
    async def login(request: Request, ...): ...
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Keyed by client IP. Memory storage is fine for single-process uvicorn.
# For multi-worker deployments switch to redis:// via STORAGE_URI env var.
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
