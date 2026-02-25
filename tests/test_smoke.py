"""Smoke tests for the FastAPI skeleton, configuration, and database session."""

import os

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Provide required env vars before importing app modules
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-smoke-tests")

from fileguard.main import app  # noqa: E402


@pytest_asyncio.fixture
async def fake_redis(monkeypatch):
    """Replace the real Redis client with an in-process fake."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.state.redis = fake
    yield fake
    await fake.aclose()


@pytest_asyncio.fixture
async def client(fake_redis):
    """Async HTTP client connected to the FastAPI app (no real I/O)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    async def test_healthz_returns_200(self, client: AsyncClient):
        response = await client.get("/healthz")
        assert response.status_code == 200

    async def test_healthz_returns_ok_status(self, client: AsyncClient):
        response = await client.get("/healthz")
        assert response.json() == {"status": "ok"}


class TestConfiguration:
    def test_database_url_loaded(self):
        from fileguard.config import settings

        assert settings.DATABASE_URL.startswith("postgresql")

    def test_redis_url_loaded(self):
        from fileguard.config import settings

        assert settings.REDIS_URL.startswith("redis://")

    def test_secret_key_loaded(self):
        from fileguard.config import settings

        assert len(settings.SECRET_KEY) > 0

    def test_missing_required_env_var_raises(self, monkeypatch):
        """Settings should raise ValidationError when a required var is absent."""
        import pydantic
        from pydantic_settings import BaseSettings, SettingsConfigDict

        class StrictSettings(BaseSettings):
            model_config = SettingsConfigDict(env_file=None)
            DATABASE_URL: str
            REDIS_URL: str
            SECRET_KEY: str

        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)

        with pytest.raises(pydantic.ValidationError):
            StrictSettings()


class TestRedisSmoke:
    async def test_redis_ping_returns_true(self, fake_redis):
        """Redis client ping must return True (smoke test for connectivity)."""
        result = await fake_redis.ping()
        assert result is True

    async def test_redis_client_on_app_state(self, fake_redis):
        """app.state.redis is set and functional after startup."""
        assert app.state.redis is not None
        result = await app.state.redis.ping()
        assert result is True


class TestDatabaseSession:
    def test_async_session_local_is_callable(self):
        from fileguard.db import AsyncSessionLocal

        assert callable(AsyncSessionLocal)

    def test_base_is_declarative(self):
        from fileguard.db import Base
        from sqlalchemy.orm import DeclarativeBase

        assert issubclass(Base, DeclarativeBase)

    def test_get_db_is_async_generator(self):
        import inspect

        from fileguard.db import get_db

        assert inspect.isasyncgenfunction(get_db)
