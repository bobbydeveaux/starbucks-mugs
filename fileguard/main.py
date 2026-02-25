import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="FileGuard API",
    description="Security-focused file processing gateway",
    version="1.0.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
)


@app.get("/healthz", tags=["health"])
async def health_check() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("FileGuard API starting up")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info("FileGuard API shutting down")
