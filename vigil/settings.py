from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    vigil_model: str = "gemini-2.5-flash"
    vigil_reasoning_model: str = "gemini-2.5-pro"
    vigil_retrieval_backend: Literal["local", "rag_engine"] = "local"
    vigil_storage_backend: Literal["local", "firestore"] = "local"
    vigil_memory_backend: Literal["local", "google"] = "local"
    vigil_memory_bank_name: str | None = None
    vigil_agent_engine_id: str | None = None
    vigil_audit_log_path: str | None = ".vigil/audit.jsonl"
    vigil_decision_store_path: str | None = ".vigil/decisions.jsonl"
    vigil_firestore_collection_prefix: str = "vigil"
    vigil_source_backend: Literal["mock", "gemini_web"] = "mock"
    vigil_action_backend: Literal["mock", "slack"] = "mock"
    vigil_retrieval_top_k: int = 6
    vigil_retrieval_min_score: float = 0.08
    vigil_rag_corpus: str | None = None
    vigil_rag_distance_threshold: float = 0.5
    google_genai_use_vertexai: bool = False
    google_api_key: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    google_application_credentials: str | None = None
    slack_bot_token: str | None = None
    slack_signing_secret: str | None = None
    slack_bot_token_secret: str | None = None
    slack_signing_secret_secret: str | None = None
    google_api_key_secret: str | None = None

    @model_validator(mode="after")
    def resolve_secret_manager_values(self) -> "Settings":
        self.slack_bot_token = self.slack_bot_token or _read_secret(
            self.slack_bot_token_secret,
            project_id=self.google_cloud_project,
        )
        self.slack_signing_secret = self.slack_signing_secret or _read_secret(
            self.slack_signing_secret_secret,
            project_id=self.google_cloud_project,
        )
        self.google_api_key = self.google_api_key or _read_secret(
            self.google_api_key_secret,
            project_id=self.google_cloud_project,
        )
        return self


def _read_secret(secret_ref: str | None, *, project_id: str | None) -> str | None:
    if not secret_ref:
        return None
    try:
        from google.cloud import secretmanager
    except ImportError:
        return None

    name = _secret_version_name(secret_ref, project_id=project_id)
    if not name:
        return None
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def _secret_version_name(secret_ref: str, *, project_id: str | None) -> str | None:
    if secret_ref.startswith("projects/"):
        if "/versions/" in secret_ref:
            return secret_ref
        return f"{secret_ref}/versions/latest"
    if not project_id:
        return None
    return f"projects/{project_id}/secrets/{secret_ref}/versions/latest"


@lru_cache
def get_settings() -> Settings:
    return Settings()
