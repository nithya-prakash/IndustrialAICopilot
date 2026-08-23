import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.image_analysis import ImageAnalysis
from app.models.user import User
from app.schemas.image import ImageAnalysisResponse
from app.services.image_service import (
    ImageTooLargeError,
    UnsupportedImageTypeError,
    analyze_uploaded_image,
    get_image_analysis,
)
from app.vision.preprocessing import InvalidImageError

router = APIRouter(prefix="/api/v1/images", tags=["images"])


def _to_response(record: ImageAnalysis) -> ImageAnalysisResponse:
    return ImageAnalysisResponse(
        id=record.id,
        status=record.status,
        equipment_type=record.equipment_type,
        equipment_id=record.equipment_id,
        vision_provider=record.vision_provider,
        vision_model=record.vision_model,
        observations=record.observations or [],
        limitations=record.limitations or [],
        error_message=record.error_message,
        created_at=record.created_at,
    )


@router.post(
    "/analyze", response_model=ImageAnalysisResponse, status_code=status.HTTP_201_CREATED
)
async def analyze(
    file: UploadFile = File(...),
    equipment_type: str | None = Form(default=None),
    equipment_id: str | None = Form(default=None),
    question: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImageAnalysisResponse:
    try:
        record = await analyze_uploaded_image(
            db,
            owner_id=user.id,
            tenant_id=user.tenant_id,
            file=file,
            equipment_type=equipment_type,
            equipment_id=equipment_id,
            question=question,
        )
    except UnsupportedImageTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only JPEG, PNG, and WebP images are supported",
        ) from exc
    except ImageTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except InvalidImageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _to_response(record)


@router.get("/{analysis_id}", response_model=ImageAnalysisResponse)
async def get_one(
    analysis_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImageAnalysisResponse:
    record = await get_image_analysis(db, analysis_id=analysis_id, tenant_id=user.tenant_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image analysis not found"
        )
    return _to_response(record)
