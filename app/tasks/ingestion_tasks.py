from app.services.ingestion_service import process_document_version_sync
from app.tasks.celery_app import celery_app


@celery_app.task(name="ingestion.process_document_version", bind=True, max_retries=0)
def process_document_version_task(self, document_version_id: str) -> None:
    process_document_version_sync(document_version_id)
