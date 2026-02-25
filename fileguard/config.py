"""Application configuration via Pydantic Settings.

All configuration is driven by environment variables. Missing required variables
raise a ``ValidationError`` at startup so misconfigured deployments fail fast.

Usage::

    from fileguard.config import settings

    print(settings.REDIS_URL)

A ``.env`` file in the working directory is loaded automatically when present.
To override settings in tests, set the relevant environment variables before
importing this module, or patch ``fileguard.config.settings`` directly.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str

    # Security
    SECRET_KEY: str

    # ClamAV
    CLAMAV_HOST: str = "clamav"
    CLAMAV_PORT: int = 3310

    # Rate limiting defaults
    DEFAULT_RATE_LIMIT_RPM: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # Worker thread pool
    THREAD_POOL_WORKERS: int = 4

    # Application
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    MAX_FILE_SIZE_MB: int = 50


settings = Settings()
