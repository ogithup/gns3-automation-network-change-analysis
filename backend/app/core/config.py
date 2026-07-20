"""Application settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="NETTWIN_",
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "NetTwin AI"
    environment: str = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    gns3_server_url: str = "http://localhost:3080"
    gns3_request_timeout: float = Field(default=10.0, gt=0)
    gns3_retry_attempts: int = Field(default=2, ge=0)
    ai_provider: str = "auto"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    gemini_request_timeout: float = Field(default=30.0, gt=0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
