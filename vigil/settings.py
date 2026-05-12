from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    vigil_model: str = "gemini-2.5-flash"
    vigil_reasoning_model: str = "gemini-2.5-pro"
    vigil_retrieval_backend: Literal["local", "google"] = "local"
    vigil_memory_backend: Literal["local", "google"] = "local"
    vigil_source_backend: Literal["mock", "gemini"] = "mock"
    vigil_action_backend: Literal["mock", "slack"] = "mock"
    google_genai_use_vertexai: bool = False
    google_api_key: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    google_application_credentials: str | None = None
    slack_bot_token: str | None = None
    slack_signing_secret: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
