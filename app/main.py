import hmac
import math
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

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
    users,
)
from app.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import dummy_verify_password
from app.logging_config import configure_logging, get_logger
from app.observability.metrics import (
    http_request_duration_seconds,
    http_requests_total,
    llm_cost_tracking_configured,
    rate_limit_exceeded_total,
)

settings = get_settings()

# A client-supplied X-Request-ID is echoed back and written into every log
# line for the request, so it's accepted only if it looks like an ID: short,
# no spaces/newlines/control characters (log injection), else replaced.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def resolve_request_id(client_value: str | None) -> str:
    if client_value and _REQUEST_ID_PATTERN.fullmatch(client_value):
        return client_value
    return str(uuid.uuid4())


def is_cost_tracking_configured(s) -> bool:
    return any(
        rate > 0
        for rate in (
            s.anthropic_input_cost_per_1k_usd,
            s.anthropic_output_cost_per_1k_usd,
            s.openai_input_cost_per_1k_usd,
            s.openai_output_cost_per_1k_usd,
        )
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    get_logger().info("startup", app_env=settings.app_env)
    # Always sets llm_cost_tracking_configured, whether or not a rate is
    # configured — an explicit, always-queryable fact instead of a metric
    # that simply never appears in /metrics when unconfigured (see that
    # gauge's own docstring in app/observability/metrics.py).
    llm_cost_tracking_configured.set(1 if is_cost_tracking_configured(settings) else 0)
    # passlib builds its dummy hash lazily on first use, which would make the
    # very first unknown-username login ~2x slower than every later one —
    # build it now so even that first request doesn't reveal anything.
    dummy_verify_password()
    yield


app = FastAPI(
    title="Industrial Multimodal AI Copilot",
    description="Evidence-based diagnostic copilot for manufacturing technicians.",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    route = request.scope.get("route")
    path_label = getattr(route, "path", None) or "unmatched"
    rate_limit_exceeded_total.labels(path=path_label).inc()
    return _rate_limit_exceeded_handler(request, exc)


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
    request_id = resolve_request_id(request.headers.get("x-request-id"))
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


def _json_safe(value):
    """Non-finite floats (NaN/inf) can't be written as JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Same 422 body FastAPI produces by default, except the echoed `input`
    is made JSON-safe first. A request carrying NaN/Infinity (which Python's
    and JavaScript's JSON encoders both emit) is correctly rejected, but the
    default handler then crashed with a 500 trying to echo that NaN back."""
    return JSONResponse(
        status_code=422, content={"detail": jsonable_encoder(_json_safe(exc.errors()))}
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    get_logger().error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Scraped by Prometheus (see docker-compose.yml + observability/prometheus/).

    When METRICS_TOKEN is set, a matching `Authorization: Bearer <token>`
    header is required — Prometheus sends one via its scrape config's
    `authorization` block. Left unset, the endpoint is open: the local
    stack's default, where every port is bound to 127.0.0.1. Production
    refuses to start without a token (app/config.py)."""
    if settings.metrics_token:
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {settings.metrics_token}"
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Every router declares its own full prefix (APIRouter(prefix=...)) rather
# than getting one here: newer FastAPI versions keep an include-time prefix
# out of the matched route's path, which would turn this router's metric
# label into "/health" instead of "/api/v1/health".
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(images.router)
app.include_router(sensors.router)
app.include_router(copilot.router)
app.include_router(diagnoses.router)
app.include_router(conversations.router)
app.include_router(audit.router)
app.include_router(users.router)
