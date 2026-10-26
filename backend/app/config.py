# =============================================================================
# config.py
# Purpose : One central place for every setting (model API, CORS, upload limits).
# Logic   : Values are read from environment variables or a local ".env" file,
#           so nothing secret or environment-specific is hard-coded.
# Usage   : from .config import settings
# =============================================================================
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All app settings. Each field can be overridden from .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Model API (OpenAI-compatible chat/completions endpoint)
    llm_api_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen2.5vl:7b"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 120.0
    llm_json_mode: bool = True
    mock_llm: bool = False  # True = skip the model and return demo data

    # Web / upload limits
    cors_origins: str = "*"
    max_image_mb: int = 10
    max_images_total: int = 8

    @property
    def max_image_bytes(self) -> int:
        """Max size of one uploaded image, in bytes."""
        return self.max_image_mb * 1024 * 1024


settings = Settings()
