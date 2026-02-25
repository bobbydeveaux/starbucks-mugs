"""Shared pytest configuration and fixtures for FileGuard tests.

Sets required environment variables before any fileguard module is imported,
so that ``fileguard.config.get_settings()`` succeeds in the test environment.
"""
from __future__ import annotations

import os

# Set required env vars before any fileguard module is imported
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/fileguard_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-chars-long!!")
os.environ.setdefault("DEFAULT_RATE_LIMIT_RPM", "100")
os.environ.setdefault("RATE_LIMIT_WINDOW_SECONDS", "60")
