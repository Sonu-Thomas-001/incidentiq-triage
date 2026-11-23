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
    # Directory with trained-model artifacts + manifest.json (produced by `python -m incidentiq_ml train`).
    # Only point this at artifacts you produced yourself: joblib files can execute code when loaded.
    evaluation_dir: str = str(Path(__file__).resolve().parents[3] / "ml" / "artifacts" / "results")
    model_dir: str = str(Path(__file__).resolve().parents[3] / "ml" / "artifacts")

    # Routing policy (Phase 3). Disabled by default: until thresholds are validated on held-out
    # data, every incident takes the human-review path. The defaults below are placeholders.
    routing_enabled: bool = False
    routing_threshold_category: float = Field(default=0.90, ge=0.0, le=1.0)
    routing_threshold_team: float = Field(default=0.90, ge=0.0, le=1.0)

    # Optional Gemini assistance (summaries, field extraction, missing-info hints). Off by default;
    # never used for predictions, confidence or routing. Secrets are server-side only.
    gemini_enabled: bool = False
    google_api_key: SecretStr | None = None
    gemini_model: str = "gemini-flash-latest"
    gemini_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    gemini_max_retries: int = Field(default=2, ge=0, le=5)
    gemini_max_input_chars: int = Field(default=2000, ge=200, le=8000)

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
