import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "IncidentIQ-Triage"
    app_env: str = "development"
    secret_key: str = ""
    access_token_expire_minutes: int = 60
    jwt_algorithm: str = "HS256"
    database_url: str = "sqlite:///./incidentiq.db"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )
    log_level: str = "INFO"
    demo_password: str = ""
    # Offline evaluation summaries written by `python -m app.scripts.rag_eval`.
    evaluation_dir: str = str(Path(__file__).resolve().parents[2] / "data" / "evaluation")

    # Retrieval-augmented assignment: a local Chroma index of ServiceNow incidents that already have
    # an assignment group. Ticket text is embedded with a Gemini embedding model (redacted/clipped).
    chroma_dir: str = str(Path(__file__).resolve().parents[2] / "data" / "chroma")
    embedding_model: str = "gemini-embedding-001"
    # Embedding models are served from regional endpoints (not "global").
    embedding_location: str = "us-central1"
    embedding_dimensions: int = Field(default=768, ge=128, le=3072)
    rag_top_k: int = Field(default=7, ge=3, le=20)
    # Below this best-neighbour cosine similarity the ticket is "unlike anything indexed": no answer.
    rag_min_similarity: float = Field(default=0.5, ge=0.0, le=1.0)
    rag_min_index_size: int = Field(default=20, ge=1)

    # Routing policy (Phase 3). Disabled by default: until thresholds are validated on held-out
    # data, every incident takes the human-review path. The defaults below are placeholders.
    routing_enabled: bool = False
    routing_threshold_category: float = Field(default=0.90, ge=0.0, le=1.0)
    routing_threshold_team: float = Field(default=0.90, ge=0.0, le=1.0)

    # Optional Gemini assistance (summaries, field extraction, missing-info hints). Off by default;
    # never used for predictions, confidence or routing. Secrets are server-side only.
    gemini_enabled: bool = False
    google_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    # Vertex AI with Application Default Credentials (no API key). Newer Gemini models are served
    # from the "global" location.
    google_genai_use_vertexai: bool = False
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    gemini_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    gemini_max_retries: int = Field(default=2, ge=0, le=5)
    gemini_max_input_chars: int = Field(default=2000, ge=200, le=8000)

    # Autopilot: poll ServiceNow for new unassigned tickets and triage them. Off by default.
    autopilot_enabled: bool = False
    # Also assign locally (audited, never written to ServiceNow) when the routing policy passes.
    autopilot_auto_assign: bool = False
    autopilot_interval_seconds: float = Field(default=300.0, ge=30, le=86400)
    autopilot_max_per_cycle: int = Field(default=25, ge=1, le=100)

    # ServiceNow (user-owned Personal Developer Instance). Off by default; secrets stay server-side.
    servicenow_enabled: bool = False
    # read_only (default): GETs only. live: PATCH of the approved assignment group allowed.
    servicenow_mode: Literal["read_only", "live"] = "read_only"
    servicenow_instance_url: str | None = None
    servicenow_auth: Literal["basic", "oauth"] = "basic"
    servicenow_username: str | None = None
    servicenow_password: SecretStr | None = None
    servicenow_oauth_client_id: str | None = None
    servicenow_oauth_client_secret: SecretStr | None = None
    servicenow_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    servicenow_max_retries: int = Field(default=2, ge=0, le=5)
    servicenow_page_size_max: int = Field(default=100, ge=1, le=1000)
    # Escape hatch for self-hosted/test hosts; the default only accepts https *.service-now.com.
    servicenow_allow_any_host: bool = False

    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        if self.app_env != "development":
            raise RuntimeError("SECRET_KEY must be set when APP_ENV is not 'development'")
        return _ephemeral_key()


@lru_cache
def _ephemeral_key() -> str:
    logger.warning("SECRET_KEY not set: using an ephemeral key; tokens die on restart")
    return secrets.token_urlsafe(48)


@lru_cache
def get_settings() -> Settings:
    return Settings()
