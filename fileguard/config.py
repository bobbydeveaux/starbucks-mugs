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

    # Application
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"
    MAX_FILE_SIZE_MB: int = 50
    THREAD_POOL_WORKERS: int = 4


settings = Settings()
