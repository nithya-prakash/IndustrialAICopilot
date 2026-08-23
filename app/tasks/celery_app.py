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
