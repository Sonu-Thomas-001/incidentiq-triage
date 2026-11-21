import logging
import secrets
from functools import lru_cache

from pydantic import Field
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
