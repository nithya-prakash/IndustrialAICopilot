import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.deps import get_current_user
from app.core.rate_limit import limiter
from app.database import get_db
from app.models.document import Document, DocumentVersion
from app.models.user import User
from app.schemas.document import DocumentListResponse, DocumentResponse
from app.services.document_service import (
    DocumentNotFoundError,
    FileTooLargeError,
    InvalidFileContentError,
    UnsupportedFileTypeError,
    delete_document,
    get_document,
    list_documents,
    upload_document,
)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
_settings = get_settings()


def _to_response(
    document: Document, version: DocumentVersion | None, chunk_count: int
) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        original_filename=document.original_filename,
        equipment_type=document.equipment_type,
        equipment_id=document.equipment_id,
        version_number=version.version_number if version else None,
        status=version.status if version else None,
        error_message=version.error_message if version else None,
        page_count=version.page_count if version else None,
        used_ocr=version.used_ocr if version else None,
        chunk_count=chunk_count,
        created_at=document.created_at,
    )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(_settings.rate_limit_upload)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    equipment_type: str | None = Form(default=None),
    equipment_id: str | None = Form(default=None),
    document_id: uuid.UUID | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    try:
        document, version = await upload_document(
            db,
            owner_id=user.id,
            tenant_id=user.tenant_id,
            file=file,
            equipment_type=equipment_type,
            equipment_id=equipment_id,
            document_id=document_id,
        )
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF uploads are supported",
        ) from exc
    except InvalidFileContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from exc

    return _to_response(document, version, chunk_count=0)


@router.get("", response_model=DocumentListResponse)
async def list_all(
    equipment_type: str | None = None,
    equipment_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    rows = await list_documents(
        db, tenant_id=user.tenant_id, equipment_type=equipment_type, equipment_id=equipment_id
    )
    return DocumentListResponse(
        documents=[_to_response(doc, version, count) for doc, version, count in rows]
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_one(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    document = await get_document(db, document_id=document_id, tenant_id=user.tenant_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    current = next((v for v in document.versions if v.is_current), None)
    chunk_count = len(current.chunks) if current else 0
    return _to_response(document, current, chunk_count)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_one(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_document(
            db, document_id=document_id, tenant_id=user.tenant_id, actor_user_id=user.id
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from exc
