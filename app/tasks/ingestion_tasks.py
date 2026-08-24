from app.services.ingestion_service import process_document_version_sync
from app.tasks.celery_app import celery_app


# max_retries stays 0 deliberately, not by oversight. Transient Qdrant
# failures during ingestion (ensure_collection/upsert_chunks) are already
# retried at the call level — see app/core/retry.py / app/rag/qdrant_store.py
# — which is safe because retrying the *same* upsert with the *same*
# point_ids is idempotent. A whole-task-level Celery retry would not be
# idempotent as this function is currently written: process_document_version
# generates a fresh uuid4() point_id and DocumentChunk row per chunk on
# every invocation, so retrying the full task after a partial success
# (e.g. Qdrant write succeeded, then the process died before the Postgres
# commit) would insert a second, duplicate set of chunks/points rather than
# safely repeating the first attempt. Making a full-task retry safe would
# need deterministic point IDs (e.g. derived from version_id + chunk_index)
# or a delete-before-insert step — a real change to the ingestion write
# path, not something to bolt on alongside this fix.
@celery_app.task(name="ingestion.process_document_version", bind=True, max_retries=0)
def process_document_version_task(self, document_version_id: str) -> None:
    process_document_version_sync(document_version_id)
