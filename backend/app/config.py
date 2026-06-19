"""Lightweight settings — no pydantic_settings dependency.

Reads .env file and environment variables with type coercion.
Import time: <1ms vs pydantic_settings ~2600ms.
"""
import hashlib
import os
import secrets
import warnings
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env parser — no dependencies.

    Searches for the file in several candidate locations so the CLI works no
    matter which directory it is launched from:
      1. The explicit path argument (default: CWD/.env)
      2. The backend/ project root (where this package lives) — i.e. the
         directory two levels up from app/config.py
      3. Walk up from CWD a few levels (monorepo layouts)
    The first existing .env wins; values only set if not already present.
    """
    import os as _os

    candidates: list[Path] = [Path(path)]
    # backend/ root: parent of the app/ package directory
    pkg_root = Path(__file__).resolve().parent.parent
    candidates.append(pkg_root / ".env")
    # Walk up from CWD (handle monorepos: backend/, then repo root)
    cwd = Path.cwd()
    for up in range(0, 4):
        candidates.append((cwd.parents[up] if up < len(cwd.parents) else pkg_root) / "backend" / ".env")
    for up in range(0, 4):
        if up < len(cwd.parents):
            candidates.append(cwd.parents[up] / ".env")

    seen: set[Path] = set()
    for env_path in candidates:
        env_path = env_path.resolve()
        if env_path in seen or not env_path.is_file():
            continue
        seen.add(env_path)
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            _os.environ.setdefault(key, value)


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int = 0) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


_DEFAULT_SECRET = "dev-secret-key-change-in-production"


class Settings:
    APP_NAME: str = _env("APP_NAME", "AI Coding Assistant")
    VERSION: str = _env("VERSION", "0.1.0")
    DEBUG: bool = _env_bool("DEBUG", True)

    # Server
    HOST: str = _env("HOST", "0.0.0.0")
    PORT: int = _env_int("PORT", 8765)

    # Zhipu AI
    ZHIPU_API_KEY: str = _env("ZHIPU_API_KEY", "")
    ZHIPU_BASE_URL: str = _env("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4/")
    ZHIPU_MODEL: str = _env("ZHIPU_MODEL", "glm-5.2")

    # Auth
    SECRET_KEY: str = _env("SECRET_KEY", _DEFAULT_SECRET)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 168

    # Database
    DATABASE_URL: str = _env("DATABASE_URL", "sqlite+aiosqlite:///./data/assistant.db")

    # Storage
    DATA_DIR: Path = Path(_env("DATA_DIR", "./data"))
    PROJECTS_DIR: Path = Path(_env("PROJECTS_DIR", "./data/projects"))

    # Terminal sandbox
    COMMAND_TIMEOUT: int = _env_int("COMMAND_TIMEOUT", 60)
    MAX_OUTPUT_SIZE: int = _env_int("MAX_OUTPUT_SIZE", 1_048_576)

    # CORS — comma-separated whitelist (e.g. "http://localhost:5173,http://localhost:3000")
    CORS_ORIGINS: list[str] = [
        o.strip() for o in _env("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173").split(",")
        if o.strip()
    ]

    # Environment selector: "development" | "staging" | "production"
    ENV: str = _env("ENV", "development").lower()

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    # Collected advisories (populated by validate_security). CLI/Web layers
    # can read these to render a nice message instead of relying on warnings.
    security_warnings: list[str] = None

    def validate_security(self) -> None:
        """Validate security-critical settings.

        - In production: refuse to start with default SECRET_KEY or wildcard CORS.
        - In development: record advisories on self.security_warnings so the
          caller (CLI/Web) can display them however it likes. We deliberately
          avoid warnings.warn() here — the bare "file:line: UserWarning:" format
          is ugly and hard to control across import sites.
        """
        self.security_warnings = []
        problems: list[str] = []

        if self.SECRET_KEY == _DEFAULT_SECRET:
            msg = "SECRET_KEY is the default value. Set SECRET_KEY in .env to a random 64+ char string."
            if self.is_production:
                problems.append(msg)
            else:
                self.security_warnings.append(msg)

        if "*" in self.CORS_ORIGINS:
            msg = "CORS_ORIGINS contains '*' — unsafe for production."
            if self.is_production:
                problems.append(msg)
            else:
                self.security_warnings.append(msg)

        if not self.ZHIPU_API_KEY:
            msg = "ZHIPU_API_KEY is empty — LLM calls will fail."
            self.security_warnings.append(msg)

        if problems:
            raise RuntimeError(
                "Refusing to start in production with insecure config:\n  - "
                + "\n  - ".join(problems)
                + "\nFix these in your .env or environment variables."
            )


settings = Settings()
# Validate immediately on import — fail-fast
settings.validate_security()
