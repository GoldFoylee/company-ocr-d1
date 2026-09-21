from datetime import date, datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ReviewQueueItemResponse(BaseModel):
    """Represents a flagged extraction item awaiting review."""

    id: int
    sheet_id: int
    field_name: str
    image_crop_ref: str
    raw_ocr_value: str
    confidence: float | None = None
    rule_flag: bool
    rule_flag_reason: str | None = None
    final_value: str | None = None
    reviewer_id: int | None = None
    created_at: datetime
    reviewed_at: datetime | None = None

    # Contextual sheet metadata for the reviewer
    vehicle: str | None = None
    branch: str | None = None
    sheet_date: date | None = None
    sheet_status: str | None = None

    model_config = ConfigDict(from_attributes=True)


class FieldCorrectionRequest(BaseModel):
    """Payload to submit a human correction or confirmation for an extraction."""

    final_value: str = Field(
        ...,
        validation_alias=AliasChoices("final_value", "value", "corrected_value"),
        description="The corrected or confirmed value for this field.",
    )
    reviewer_id: int | None = Field(
        default=None,
        description="Optional ID of the reviewer submitting the correction.",
    )

    model_config = ConfigDict(populate_by_name=True)


class FieldCorrectionResponse(BaseModel):
    """Extraction representation returned after submitting a correction."""

    id: int
    sheet_id: int
    field_name: str
    image_crop_ref: str
    raw_ocr_value: str
    confidence: float | None = None
    rule_flag: bool
    rule_flag_reason: str | None = None
    final_value: str | None = None
    reviewer_id: int | None = None
    created_at: datetime
    reviewed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SheetVerificationRequest(BaseModel):
    """Optional payload when marking a sheet as verified."""

    reviewer_id: int | None = Field(
        default=None,
        description="Optional ID of the reviewer who verified the sheet.",
    )
    force: bool = Field(
        default=False,
        description="Force verification even if unreviewed flagged fields remain (audited).",
    )


class SheetVerificationResponse(BaseModel):
    """Sheet state returned after verification."""

    id: int
    vehicle: str
    branch: str
    date: date
    image_path: str
    status: str
    force_verified: bool = False
    force_verified_by: int | None = None
    force_verified_at: datetime | None = None
    verified_via_force: bool = False
    unreviewed_flagged_count: int = 0

    model_config = ConfigDict(from_attributes=True)
