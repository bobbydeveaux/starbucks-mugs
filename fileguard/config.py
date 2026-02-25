"""Application configuration via Pydantic Settings.

All configuration is driven by environment variables. Missing required variables
raise a ``ValidationError`` at startup so misconfigured deployments fail fast.

Usage::

    from fileguard.config import get_settings

    settings = get_settings()
    print(settings.redis_url)

The ``get_settings`` function is cached with ``functools.lru_cache``. To override
settings in tests, patch ``fileguard.config.get_settings`` or set the relevant
environment variables before calling ``get_settings()`` for the first time.
"""
from __future__ import annotations

import functools

from pydantic import Field, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """FileGuard application settings.

    Environment variables are read case-insensitively. A ``.env`` file in the
    working directory is loaded automatically when present.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = Field(
        ...,
        description="Async PostgreSQL DSN, e.g. postgresql+asyncpg://user:pass@host/db",
    )

    # Redis
    redis_url: RedisDsn = Field(
        ...,
        description="Redis DSN, e.g. redis://localhost:6379/0",
    )

    # Security
    secret_key: str = Field(
        ...,
        min_length=32,
        description="HMAC signing key for audit log integrity (min 32 chars)",
    )

    # Rate limiting defaults
    default_rate_limit_rpm: int = Field(
        default=100,
        ge=1,
        le=100_000,
        description="Default per-tenant requests-per-minute limit when not overridden",
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        description="Sliding window duration in seconds (default: 60 for per-minute limiting)",
    )

    # Worker thread pool
    extractor_max_workers: int = Field(
        default=4,
        ge=1,
        description="Thread pool size for CPU-bound document extraction",
    )

    # Environment
    environment: str = Field(
        default="production",
        description="Deployment environment: development, staging, or production",
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode (never set True in production)",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not (v.startswith("postgresql") or v.startswith("sqlite")):
            raise ValueError("database_url must be a PostgreSQL or SQLite DSN")
        return v


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton.

    The first call reads environment variables (and ``.env``). Subsequent calls
    return the cached instance. Clear the cache with ``get_settings.cache_clear()``
    between tests.
    """
    return Settings()
