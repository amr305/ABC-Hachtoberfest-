# =============================================================================
# config.py
# Purpose : One central place for every setting (model API, CORS, upload limits).
# Logic   : Values are read from environment variables or backend/.env,
#           independent of the directory used to start Uvicorn.
# Usage   : from .config import settings
# =============================================================================
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """All app settings. Each field can be overridden from .env."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # AI service base URL (supports a trailing /v1 for existing configs)
    llm_api_url: str = "http://localhost:8001"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 300.0

    # Web / upload limits
    cors_origins: str = "*"
    max_image_mb: int = 10
    max_images_total: int = 8

    @property
    def max_image_bytes(self) -> int:
        """Max size of one uploaded image, in bytes."""
        return self.max_image_mb * 1024 * 1024


settings = Settings()
