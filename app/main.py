import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.routes import (
    audit,
    auth,
    conversations,
    copilot,
    diagnoses,
    documents,
    health,
    images,
    sensors,
)
from app.config import get_settings
from app.logging_config import configure_logging, get_logger
from app.observability.metrics import http_request_duration_seconds, http_requests_total

settings = get_settings()
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    get_logger().info("startup", app_env=settings.app_env)
    yield


app = FastAPI(
    title="Industrial Multimodal AI Copilot",
    description="Evidence-based diagnostic copilot for manufacturing technicians.",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)

    start = time.perf_counter()
    response = await call_next(request)
    duration_seconds = time.perf_counter() - start
    duration_ms = round(duration_seconds * 1000, 2)

    get_logger().info(
        "request_completed",
        method=request.method,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    # Route pattern (e.g. "/api/v1/diagnoses/{diagnosis_id}"), not the raw
    # path — using the raw path would make every UUID-bearing URL its own
    # label value, and an unmatched/scanned path its own label forever.
    route = request.scope.get("route")
    path_label = getattr(route, "path", None) or "unmatched"
    http_requests_total.labels(
        method=request.method, path=path_label, status_code=str(response.status_code)
    ).inc()
    http_request_duration_seconds.labels(method=request.method, path=path_label).observe(
        duration_seconds
    )

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    get_logger().error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Scraped by Prometheus (see docker-compose.yml + observability/prometheus/).
    Intentionally unauthenticated, matching standard Prometheus practice —
    Prometheus has no bearer token to send. Reachable only from the compose
    network in normal operation; a real deployment would firewall this port
    to the scraper's network rather than rely on obscurity, same as any
    other internal-only endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(images.router)
app.include_router(sensors.router)
app.include_router(copilot.router)
app.include_router(diagnoses.router)
app.include_router(conversations.router)
app.include_router(audit.router)
