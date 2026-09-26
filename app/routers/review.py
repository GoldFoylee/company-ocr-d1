from pathlib import Path as FilePath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Extraction
from app.schemas.review import (
    FieldCorrectionRequest,
    FieldCorrectionResponse,
    ReviewQueueItemResponse,
    SheetVerificationRequest,
    SheetVerificationResponse,
)
from app.services.review import (
    get_review_queue,
    submit_field_correction,
    verify_sheet,
)
from app.services.sheet_review import EXCLUDED_FIELD
from app.storage import get_crop_root

router = APIRouter()

_IMAGE_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


@router.get(
    "/crops/{extraction_id}",
    response_class=FileResponse,
    summary="Serve a stored extraction crop",
)
def get_extraction_crop(
    extraction_id: Annotated[int, Path(ge=1)],
    db: Annotated[Session, Depends(get_db)],
    crop_root: Annotated[FilePath, Depends(get_crop_root)],
) -> FileResponse:
    """Serve only non-guest image crops contained by the configured crop root."""
    extraction = db.get(Extraction, extraction_id)
    if extraction is None or extraction.field_name == EXCLUDED_FIELD:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found")

    root = crop_root.resolve()
    crop = FilePath(extraction.image_crop_ref).resolve()
    media_type = _IMAGE_MEDIA_TYPES.get(crop.suffix.lower())
    if not crop.is_relative_to(root) or not crop.is_file() or media_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found")

    return FileResponse(crop, media_type=media_type)


@router.get(
    "/queue",
    response_model=list[ReviewQueueItemResponse],
    summary="List flagged fields awaiting review",
)
@router.get(
    "/flagged-fields",
    response_model=list[ReviewQueueItemResponse],
    summary="List flagged fields awaiting review (alias)",
    include_in_schema=False,
)
def list_flagged_fields(
    db: Annotated[Session, Depends(get_db)],
    sheet_id: Annotated[
        int | None,
        Query(description="Filter by specific sheet ID"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of items to return"),
    ] = 100,
    offset: Annotated[
        int,
        Query(ge=0, description="Offset for pagination"),
    ] = 0,
) -> list[ReviewQueueItemResponse]:
    """Retrieve all flagged fields awaiting human review.

    Flagged fields are extractions with rule_flag=True that have not yet been
    reviewed (reviewed_at is null).
    """
    return get_review_queue(db=db, sheet_id=sheet_id, limit=limit, offset=offset)


@router.post(
    "/fields/{extraction_id}/correction",
    response_model=FieldCorrectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit human correction for an extraction",
)
@router.patch(
    "/fields/{extraction_id}",
    response_model=FieldCorrectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit human correction for an extraction (alias)",
    include_in_schema=False,
)
@router.put(
    "/fields/{extraction_id}",
    response_model=FieldCorrectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit human correction for an extraction (alias)",
    include_in_schema=False,
)
def correct_field(
    extraction_id: Annotated[
        int,
        Path(ge=1, description="ID of the extraction to correct"),
    ],
    payload: FieldCorrectionRequest,
    db: Annotated[Session, Depends(get_db)],
) -> FieldCorrectionResponse:
    """Submit a verified or corrected value for a single field extraction.

    Updates final_value, sets reviewed_at to the current timestamp, and
    records the reviewer_id if provided.
    """
    extraction = submit_field_correction(
        db=db,
        extraction_id=extraction_id,
        correction=payload,
    )
    return FieldCorrectionResponse.model_validate(extraction)


@router.post(
    "/sheets/{sheet_id}/verify",
    response_model=SheetVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark a sheet as fully verified",
)
def mark_sheet_verified(
    sheet_id: Annotated[
        int,
        Path(ge=1, description="ID of the sheet to mark verified"),
    ],
    db: Annotated[Session, Depends(get_db)],
    force: Annotated[
        bool,
        Query(
            description="Force verification even if unreviewed flagged fields remain",
        ),
    ] = False,
    reviewer_id: Annotated[
        int | None,
        Query(
            description="Optional ID of the reviewer verifying the sheet",
        ),
    ] = None,
    payload: SheetVerificationRequest | None = None,
) -> SheetVerificationResponse:
    """Mark a sheet as fully verified.

    Requires all flagged fields to have been reviewed first. If unreviewed
    flagged fields remain, returns HTTP 400 unless force=true is supplied,
    which records a structured audit trail.
    """
    effective_force = force or (payload.force if payload else False)
    effective_reviewer_id = reviewer_id or (payload.reviewer_id if payload else None)

    sheet, verified_via_force, unreviewed_count = verify_sheet(
        db=db,
        sheet_id=sheet_id,
        force=effective_force,
        reviewer_id=effective_reviewer_id,
    )

    return SheetVerificationResponse(
        id=sheet.id,
        vehicle=sheet.vehicle,
        branch=sheet.branch,
        date=sheet.date,
        image_path=sheet.image_path,
        status=sheet.status,
        force_verified=sheet.force_verified,
        force_verified_by=sheet.force_verified_by,
        force_verified_at=sheet.force_verified_at,
        verified_via_force=verified_via_force,
        unreviewed_flagged_count=unreviewed_count,
    )
