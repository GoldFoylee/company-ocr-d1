"""Reset and seed synthetic data for the review UI development workflow."""

from datetime import date

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import Extraction, Sheet

DEMO_IMAGE_PATH = "/synthetic/review-demo-sheet.jpg"


def seed_review_demo() -> tuple[int, list[int]]:
    """Create one repeatable synthetic sheet with two flagged extractions."""
    with SessionLocal() as db:
        existing_sheet_ids = list(
            db.execute(select(Sheet.id).where(Sheet.image_path == DEMO_IMAGE_PATH)).scalars()
        )
        if existing_sheet_ids:
            db.execute(delete(Extraction).where(Extraction.sheet_id.in_(existing_sheet_ids)))
            db.execute(delete(Sheet).where(Sheet.id.in_(existing_sheet_ids)))

        sheet = Sheet(
            vehicle="SYNTHETIC-01",
            branch="Demo",
            date=date(2026, 9, 21),
            image_path=DEMO_IMAGE_PATH,
            status="review",
        )
        db.add(sheet)
        db.flush()

        extractions = [
            Extraction(
                sheet_id=sheet.id,
                field_name="driver_name",
                image_crop_ref="/synthetic/crops/driver-name.png",
                raw_ocr_value="Jahn Doe",
                confidence=0.61,
                rule_flag=True,
                rule_flag_reason="Name needs review",
            ),
            Extraction(
                sheet_id=sheet.id,
                field_name="end_km",
                image_crop_ref="/synthetic/crops/end-km.png",
                raw_ocr_value="12B45",
                confidence=0.72,
                rule_flag=True,
                rule_flag_reason="Expected digits only",
            ),
        ]
        db.add_all(extractions)
        db.commit()

        extraction_ids = [extraction.id for extraction in extractions]
        return sheet.id, extraction_ids


if __name__ == "__main__":
    seeded_sheet_id, seeded_extraction_ids = seed_review_demo()
    print(
        "Seeded synthetic review sheet "
        f"{seeded_sheet_id} with extractions {seeded_extraction_ids}."
    )
