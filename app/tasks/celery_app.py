from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "industrial_copilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.ingestion_tasks"],
)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.conf.task_acks_late = True

# Registers the Celery signal handlers that back the worker's Prometheus
# metrics (app/observability/metrics.py's celery_tasks_total/
# celery_task_duration_seconds) — a plain `import` for its side effect of
# connecting the signals, not because anything here calls into it directly.
import app.tasks.observability  # noqa: E402,F401
