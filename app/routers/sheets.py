"""HTTP endpoints for sheet ingestion."""

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi import Path as ApiPath
from sqlalchemy.orm import Session

from app.database import get_db
from app.ocr.base import Recognizer
from app.ocr.provider import get_recognizer
from app.schemas.sheets import SheetDetailResponse, SheetSummaryResponse, SheetUploadResponse
from app.services.sheet_review import get_sheet_detail, list_sheets
from app.services.sheet_upload import ALLOWED_IMAGE_TYPES, process_uploaded_sheet
from app.storage import get_crop_root, get_upload_root

router = APIRouter()


@router.get("", response_model=list[SheetSummaryResponse], summary="List uploaded sheets")
@router.get("/", response_model=list[SheetSummaryResponse], include_in_schema=False)
def get_sheets(db: Annotated[Session, Depends(get_db)]) -> list[SheetSummaryResponse]:
    return list_sheets(db)


@router.post(
    "/upload",
    response_model=SheetUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and synchronously process one log sheet",
)
def upload_sheet(
    image: Annotated[UploadFile, File(description="JPEG or PNG log-sheet image")],
    vehicle: Annotated[str, Form(min_length=1, max_length=255)],
    branch: Annotated[str, Form(min_length=1, max_length=255)],
    sheet_date: Annotated[date, Form(description="Sheet metadata date")],
    db: Annotated[Session, Depends(get_db)],
    recognizer: Annotated[Recognizer, Depends(get_recognizer)],
    upload_root: Annotated[Path, Depends(get_upload_root)],
    crop_root: Annotated[Path, Depends(get_crop_root)],
) -> SheetUploadResponse:
    """Run blocking OCR in FastAPI's worker thread and return when persisted.

    This endpoint is intentionally declared with plain ``def``. FastAPI runs
    synchronous route functions in its threadpool, so the roughly 80-second OCR
    workload does not block the event loop or unrelated API requests.
    """
    content_type = image.content_type or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload must be a JPEG or PNG image",
        )

    normalized_vehicle = vehicle.strip()
    normalized_branch = branch.strip()
    if not normalized_vehicle or not normalized_branch:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vehicle and branch must not be blank",
        )

    try:
        result, sheet = process_uploaded_sheet(
            image=image,
            upload_root=upload_root,
            crop_root=crop_root,
            db=db,
            recognizer=recognizer,
            vehicle=normalized_vehicle,
            branch=normalized_branch,
            sheet_date=sheet_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return SheetUploadResponse(
        sheet_id=result.sheet_id,
        row_count=result.row_count,
        extraction_count=result.extraction_count,
        status=sheet.status,
    )


@router.get(
    "/{sheet_id}",
    response_model=SheetDetailResponse,
    summary="Get a sheet in physical review-grid order",
)
def get_sheet(
    sheet_id: Annotated[int, ApiPath(ge=1)],
    db: Annotated[Session, Depends(get_db)],
) -> SheetDetailResponse:
    return get_sheet_detail(db, sheet_id)
