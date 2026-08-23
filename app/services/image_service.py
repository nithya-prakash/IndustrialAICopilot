import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_config import get_logger
from app.models.image_analysis import ImageAnalysis, ImageAnalysisStatus
from app.vision.analyzer import VisionError, analyze_image
from app.vision.preprocessing import validate_and_preprocess

logger = get_logger("image_service")


class UnsupportedImageTypeError(Exception):
    pass


class ImageTooLargeError(Exception):
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        super().__init__(f"Image exceeds max size of {max_bytes} bytes")


async def _read_upload_within_limit(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ImageTooLargeError(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


async def analyze_uploaded_image(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    tenant_id: str,
    file: UploadFile,
    equipment_type: str | None,
    equipment_id: str | None,
    question: str | None,
) -> ImageAnalysis:
    settings = get_settings()

    if file.content_type not in settings.allowed_image_content_types_list:
        raise UnsupportedImageTypeError(file.content_type)

    raw_content = await _read_upload_within_limit(file, settings.max_image_size_bytes)
    # Raises InvalidImageError if not a real, decodable image — propagates to the route.
    processed_bytes, media_type = validate_and_preprocess(raw_content)

    analysis_id = uuid.uuid4()
    storage_dir = Path(settings.data_dir) / "images"
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / f"{analysis_id}.jpg"
    storage_path.write_bytes(processed_bytes)

    record = ImageAnalysis(
        id=analysis_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        equipment_type=equipment_type,
        equipment_id=equipment_id,
        storage_path=str(storage_path),
        content_type=media_type,
        file_size_bytes=len(processed_bytes),
        vision_provider=settings.vision_provider,
        vision_model=settings.vision_model,
        status=ImageAnalysisStatus.analyzing,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    try:
        result = await analyze_image(processed_bytes, media_type, question=question)
    except VisionError as exc:
        record.status = ImageAnalysisStatus.failed
        record.error_message = str(exc)
        await db.commit()
        await db.refresh(record)
        logger.error(
            "vision_analysis_failed", image_analysis_id=str(analysis_id), error=str(exc)
        )
        return record

    record.status = ImageAnalysisStatus.ready
    record.observations = result.observations
    record.limitations = result.limitations
    record.raw_response = result.raw_response
    await db.commit()
    await db.refresh(record)
    logger.info(
        "vision_analysis_ready",
        image_analysis_id=str(analysis_id),
        observation_count=len(result.observations),
    )
    return record


async def get_image_analysis(
    db: AsyncSession, *, analysis_id: uuid.UUID, tenant_id: str
) -> ImageAnalysis | None:
    result = await db.execute(
        select(ImageAnalysis).where(
            ImageAnalysis.id == analysis_id, ImageAnalysis.tenant_id == tenant_id
        )
    )
    return result.scalar_one_or_none()
