from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Reviewer(Base):
    __tablename__ = "reviewers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sheet(Base):
    __tablename__ = "sheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle: Mapped[str] = mapped_column(String(255))
    branch: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    image_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), server_default="pending", index=True)
    force_verified: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    force_verified_by: Mapped[int | None] = mapped_column(
        ForeignKey("reviewers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    force_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Extraction(Base):
    __tablename__ = "extractions"
    __table_args__ = (
        CheckConstraint("row_number >= 1", name="ck_extractions_row_number_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(default=1)
    field_name: Mapped[str] = mapped_column(String(255))
    image_crop_ref: Mapped[str] = mapped_column(Text)
    raw_ocr_value: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rule_flag: Mapped[bool] = mapped_column(Boolean, server_default="false")
    rule_flag_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(
        ForeignKey("reviewers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
