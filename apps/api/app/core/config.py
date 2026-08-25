"""Application configuration using pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings, loaded from environment variables."""

    app_name: str = "Modeem AI Platform API"
    service_name: str = "modeem-ai-api"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_version: str = "v1"

    database_url: str = ""

    # Redis-ready configuration (no worker implementation in this phase).
    redis_url: str = "redis://localhost:6379/0"

    # Authentication (Phase 2A). AUTH_SECRET must come from the environment.
    # Falls back to SESSION_SECRET (provided by the hosting environment) so
    # development works without duplicating secrets. Never hardcode a value.
    auth_secret: str = ""
    session_secret: str = ""
    session_ttl_seconds: int = 60 * 60 * 12  # 12 hours

    # Connections (Phase 2B): AES-256-GCM key, URL-safe Base64 of 32 random
    # bytes. MUST be independent of AUTH_SECRET / SESSION_SECRET — never
    # derived from or defaulted to them. In development, connection
    # operations fail clearly until this is configured.
    connection_encryption_key: str = ""

    # Bootstrap admin (development convenience; never commit real values).
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    bootstrap_tenant_name: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment != "production" and not settings.auth_secret:
        # Development convenience only; production requires explicit AUTH_SECRET.
        settings.auth_secret = settings.session_secret

    from app.core.security import validate_auth_secret_for_production

    validate_auth_secret_for_production(settings.environment, settings.auth_secret)

    if settings.environment == "production":
        from app.services.credential_crypto import validate_encryption_key

        # Fail startup clearly if the key is missing or malformed. Never
        # log or include the key value itself.
        validate_encryption_key(settings.connection_encryption_key)
    return settings
