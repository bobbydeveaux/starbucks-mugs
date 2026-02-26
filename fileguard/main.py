import logging

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from fileguard.api.middleware.auth import AuthMiddleware
from fileguard.api.middleware.logging import RequestLoggingMiddleware
from fileguard.api.routes.reports import router as reports_router
from fileguard.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="FileGuard API",
    description="Security-focused file processing gateway",
    version="1.0.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
)

app.add_middleware(AuthMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(reports_router)

# Redis client stored on app state so it can be accessed by routes and tests
app.state.redis = None


@app.get("/healthz", tags=["health"])
async def health_check() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("FileGuard API starting up")
    app.state.redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    logger.info("Redis client initialised")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if app.state.redis is not None:
        await app.state.redis.aclose()
        logger.info("Redis client closed")
    logger.info("FileGuard API shutting down")
