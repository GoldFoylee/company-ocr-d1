"""Store an uploaded image and run it through the shared sheet pipeline."""

import shutil
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import Sheet
from app.ocr.base import Recognizer
from app.pipeline import PipelineResult, run_sheet_pipeline

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def store_upload(image: UploadFile, upload_root: Path) -> Path:
    """Copy an accepted upload to a generated local path."""
    suffix = ALLOWED_IMAGE_TYPES[image.content_type or ""]
    upload_root.mkdir(parents=True, exist_ok=True)
    destination = upload_root / f"{uuid4().hex}{suffix}"
    try:
        with destination.open("xb") as output:
            shutil.copyfileobj(image.file, output)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def process_uploaded_sheet(
    *,
    image: UploadFile,
    upload_root: Path,
    crop_root: Path,
    db: Session,
    recognizer: Recognizer,
    vehicle: str,
    branch: str,
    sheet_date: date,
) -> tuple[PipelineResult, Sheet]:
    """Persist the upload and synchronously invoke the existing real pipeline."""
    image_path = store_upload(image, upload_root)
    try:
        result = run_sheet_pipeline(
            image_path=image_path,
            crop_root=crop_root,
            db=db,
            recognizer=recognizer,
            vehicle=vehicle,
            branch=branch,
            sheet_date=sheet_date,
            # The current name-matching demonstration uses caller-provided data,
            # never the excluded guest-name crop. Uploads have no real roster
            # source, so matching is deliberately inactive instead of fabricated.
            roster_query="",
            roster_names=(),
        )
    except Exception:
        image_path.unlink(missing_ok=True)
        raise

    sheet = db.get(Sheet, result.sheet_id)
    if sheet is None:
        image_path.unlink(missing_ok=True)
        raise RuntimeError(f"Pipeline committed missing sheet {result.sheet_id}")
    return result, sheet
