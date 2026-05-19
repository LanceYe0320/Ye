import warnings
from pathlib import Path

from pydantic_settings import BaseSettings

_DEFAULT_SECRET = "dev-secret-key-change-in-production"


class Settings(BaseSettings):
    APP_NAME: str = "AI Coding Assistant"
    VERSION: str = "0.1.0"
    DEBUG: bool = True

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8765

    # Zhipu AI
    ZHIPU_API_KEY: str = ""
    ZHIPU_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4/"
    ZHIPU_MODEL: str = "glm-4-plus"

    # Auth (simplified for local deployment)
    SECRET_KEY: str = _DEFAULT_SECRET
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 168  # 7 days

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/assistant.db"

    # Storage
    DATA_DIR: Path = Path("./data")
    PROJECTS_DIR: Path = Path("./data/projects")

    # Terminal sandbox
    COMMAND_TIMEOUT: int = 60
    MAX_OUTPUT_SIZE: int = 1_048_576  # 1MB

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8765",
        "*",
    ]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

if settings.SECRET_KEY == _DEFAULT_SECRET:
    warnings.warn(
        "Using default SECRET_KEY — set SECRET_KEY in .env for production!",
        stacklevel=2,
    )
