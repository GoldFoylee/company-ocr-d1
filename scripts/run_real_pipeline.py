"""Run the real recognizer against all 5 golden fixtures and commit the results.

Unlike tests/integration/test_pipeline.py and test_pipeline_real_recognizer.py, which
roll back every write through a savepoint, this script commits through SessionLocal --
the resulting sheets and extractions are real, visible rows: readable via the review
API (GET /review/queue), not seeded synthetic data like scripts/seed_review_demo.py.
"""

from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Extraction
from app.ocr.paddle import PaddleOCRRecognizer
from app.pipeline import run_sheet_pipeline

FIXTURE_DIRECTORY = Path("tests/fixtures/anonymized")
FIXTURE_IDS = tuple(f"sheet_{number:03d}" for number in range(1, 6))
CROP_ROOT = Path("data/real_pipeline_runs")
ROSTER_QUERY = "Morgon Alder"
ROSTER_NAMES = ("Morgan Alder", "Jules Whitaker", "Ravi Calder")


def run_real_pipeline() -> list[dict]:
    """Extract every golden fixture with PaddleOCRRecognizer and commit each sheet."""
    recognizer = PaddleOCRRecognizer()
    summaries = []
    with SessionLocal() as db:
        for fixture_id in FIXTURE_IDS:
            result = run_sheet_pipeline(
                image_path=FIXTURE_DIRECTORY / f"{fixture_id}.jpg",
                crop_root=CROP_ROOT,
                db=db,
                recognizer=recognizer,
                vehicle=f"REAL-RUN-{fixture_id.upper()}",
                branch="Real Recognizer Verification",
                sheet_date=date(2026, 9, 25),
                roster_query=ROSTER_QUERY,
                roster_names=ROSTER_NAMES,
            )
            extractions = db.scalars(
                select(Extraction).where(Extraction.sheet_id == result.sheet_id)
            ).all()
            flagged_count = sum(1 for extraction in extractions if extraction.rule_flag)
            summaries.append(
                {
                    "fixture_id": fixture_id,
                    "sheet_id": result.sheet_id,
                    "row_count": result.row_count,
                    "extraction_count": result.extraction_count,
                    "flagged_count": flagged_count,
                    "clean_count": result.extraction_count - flagged_count,
                }
            )
    return summaries


if __name__ == "__main__":
    for summary in run_real_pipeline():
        print(
            f"{summary['fixture_id']}: sheet_id={summary['sheet_id']} "
            f"rows={summary['row_count']} extractions={summary['extraction_count']} "
            f"flagged={summary['flagged_count']} clean={summary['clean_count']}"
        )
