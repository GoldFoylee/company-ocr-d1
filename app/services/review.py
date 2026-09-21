import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Extraction, Reviewer, Sheet
from app.schemas.review import FieldCorrectionRequest, ReviewQueueItemResponse

audit_logger = logging.getLogger("audit.review")


def get_review_queue(
    db: Session,
    sheet_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ReviewQueueItemResponse]:
    """Retrieve flagged extractions that are awaiting review.

    A field is defined as awaiting review when rule_flag is True and
    reviewed_at is None.
    """
    stmt = (
        select(Extraction, Sheet)
        .join(Sheet, Extraction.sheet_id == Sheet.id)
        .where(Extraction.rule_flag.is_(True), Extraction.reviewed_at.is_(None))
        .order_by(Extraction.id.asc())
    )

    if sheet_id is not None:
        stmt = stmt.where(Extraction.sheet_id == sheet_id)

    stmt = stmt.offset(offset).limit(limit)
    rows = db.execute(stmt).all()

    return [
        ReviewQueueItemResponse(
            id=extraction.id,
            sheet_id=extraction.sheet_id,
            field_name=extraction.field_name,
            image_crop_ref=extraction.image_crop_ref,
            raw_ocr_value=extraction.raw_ocr_value,
            confidence=extraction.confidence,
            rule_flag=extraction.rule_flag,
            rule_flag_reason=extraction.rule_flag_reason,
            final_value=extraction.final_value,
            reviewer_id=extraction.reviewer_id,
            created_at=extraction.created_at,
            reviewed_at=extraction.reviewed_at,
            vehicle=sheet.vehicle,
            branch=sheet.branch,
            sheet_date=sheet.date,
            sheet_status=sheet.status,
        )
        for extraction, sheet in rows
    ]


def submit_field_correction(
    db: Session,
    extraction_id: int,
    correction: FieldCorrectionRequest,
) -> Extraction:
    """Submit a human correction or confirmation for a single extraction."""
    extraction = db.get(Extraction, extraction_id)
    if extraction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Extraction with id {extraction_id} not found",
        )

    if correction.reviewer_id is not None:
        reviewer = db.get(Reviewer, correction.reviewer_id)
        if reviewer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Reviewer with id {correction.reviewer_id} not found",
            )
        extraction.reviewer_id = correction.reviewer_id

    extraction.final_value = correction.final_value
    extraction.reviewed_at = datetime.now(UTC)

    db.commit()
    db.refresh(extraction)
    return extraction


def verify_sheet(
    db: Session,
    sheet_id: int,
    force: bool = False,
    reviewer_id: int | None = None,
) -> tuple[Sheet, bool, int]:
    """Mark a sheet as fully verified.

    Validates that no unreviewed flagged fields remain on the sheet.
    If unreviewed flagged fields exist and force is True, allows verification
    while recording a structured audit log.
    """
    sheet = db.get(Sheet, sheet_id)
    if sheet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sheet with id {sheet_id} not found",
        )

    if reviewer_id is not None:
        reviewer = db.get(Reviewer, reviewer_id)
        if reviewer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Reviewer with id {reviewer_id} not found",
            )

    unreviewed_extractions = (
        db.execute(
            select(Extraction).where(
                Extraction.sheet_id == sheet_id,
                Extraction.rule_flag.is_(True),
                Extraction.reviewed_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    unreviewed_count = len(unreviewed_extractions)

    if unreviewed_count > 0 and not force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot mark sheet as verified: {unreviewed_count} flagged "
                "field(s) awaiting review. Correct remaining flagged fields or "
                "use force verification with audit trail."
            ),
        )

    verified_via_force = False
    if unreviewed_count > 0 and force:
        verified_via_force = True
        audit_logger.warning(
            "AUDIT FORCE VERIFY: Sheet %s (%s, %s) force-verified with %s flagged fields. "
            "Extractions: %s. Reviewer: %s at %s",
            sheet.id,
            sheet.vehicle,
            sheet.branch,
            unreviewed_count,
            [e.id for e in unreviewed_extractions],
            reviewer_id or "unspecified",
            datetime.now(UTC).isoformat(),
            extra={
                "audit_event": "force_sheet_verification",
                "sheet_id": sheet.id,
                "vehicle": sheet.vehicle,
                "branch": sheet.branch,
                "unreviewed_count": unreviewed_count,
                "unreviewed_extraction_ids": [e.id for e in unreviewed_extractions],
                "reviewer_id": reviewer_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    sheet.status = "verified"
    db.commit()
    db.refresh(sheet)
    return sheet, verified_via_force, unreviewed_count
