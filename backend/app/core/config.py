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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

