"""Reset and seed synthetic physical-row data for the review UI workflow."""

import base64
import os
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import Extraction, Sheet

DEMO_IMAGE_PATH = "/synthetic/review-demo-sheet.jpg"
_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_ROW_VALUES = {
    "ds_no": "1",
    "date": "2026-08-01",
    "start_time": "08:00",
    "start_km": "1O0",
    "close_time": "20:00",
    "close_km": "200",
    "total_km": "100",
    "total_time": "12h",
    "toll": "0",
    "parking": "0",
    "journey_details": "Depot to office",
}


def seed_review_demo() -> tuple[int, list[int]]:
    """Create one repeatable synthetic sheet with a complete physical row."""
    crop_root = Path(os.environ.get("OCR_CROP_ROOT", "data/crops")).resolve()
    crop_directory = crop_root / "synthetic-review-demo"
    crop_directory.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        existing_sheet_ids = list(
            db.execute(select(Sheet.id).where(Sheet.image_path == DEMO_IMAGE_PATH)).scalars()
        )
        if existing_sheet_ids:
            db.execute(delete(Extraction).where(Extraction.sheet_id.in_(existing_sheet_ids)))
            db.execute(delete(Sheet).where(Sheet.id.in_(existing_sheet_ids)))

        sheet = Sheet(
            vehicle="FAKE-001",
            branch="Synthetic demo",
            date=date(2026, 8, 1),
            image_path=DEMO_IMAGE_PATH,
            status="review",
        )
        db.add(sheet)
        db.flush()

        extractions = []
        for field_name, value in _ROW_VALUES.items():
            crop_path = crop_directory / f"row01_{field_name}.png"
            crop_path.write_bytes(_ONE_PIXEL_PNG)
            flagged = field_name == "start_km"
            extractions.append(
                Extraction(
                    sheet_id=sheet.id,
                    row_number=1,
                    field_name=field_name,
                    image_crop_ref=str(crop_path),
                    raw_ocr_value=value,
                    confidence=0.54 if flagged else 0.98,
                    rule_flag=flagged,
                    rule_flag_reason="Expected digits only" if flagged else None,
                )
            )
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
