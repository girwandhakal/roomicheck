from __future__ import annotations

import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from .config import get_settings
from .observability import configure_logging
from .routes import router


settings = get_settings()
configure_logging()
logger = logging.getLogger("roomicheck.http")
app = FastAPI(
    title="RoomiCheck API",
    version="0.1.0",
    description="Anonymous adaptive co-living questionnaire API.",
)


@app.middleware("http")
async def log_request(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.error("request_failed", extra={"fields": {
            "method": request.method,
            "path": request.url.path,
            "status": 500,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }})
        raise
    logger.info("request_completed", extra={"fields": {
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }})
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)
