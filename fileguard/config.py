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

    # Google Cloud DLP (optional — required when pii_backend=google_dlp)
    GOOGLE_DLP_PROJECT_ID: str = ""
    GOOGLE_DLP_CREDENTIALS_FILE: str = ""
    GOOGLE_DLP_MIN_LIKELIHOOD: str = "LIKELY"
    GOOGLE_DLP_TIMEOUT: float = 30.0

    # AWS Macie (optional — required when pii_backend=aws_macie)
    MACIE_STAGING_BUCKET: str = ""
    MACIE_REGION: str = "eu-west-2"
    MACIE_POLL_INTERVAL: float = 5.0
    MACIE_JOB_TIMEOUT: float = 300.0

    # Compliance reports
    REPORTS_DIR: str = "/tmp/fileguard/reports"
    REPORT_CADENCE: str = "daily"  # "daily" or "weekly"

    # Redacted file storage and signed URLs
    REDACTED_FILES_DIR: str = "/tmp/fileguard/redacted"
    REDACTED_URL_TTL_SECONDS: int = 3600  # 1 hour default
    REDACTED_BASE_URL: str = ""  # e.g. "https://api.example.com"


settings = Settings()
