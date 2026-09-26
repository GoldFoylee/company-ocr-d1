"""Filesystem roots shared by upload and review endpoints."""

import os
from pathlib import Path


def get_upload_root() -> Path:
    return Path(os.environ.get("STORAGE_LOCAL_PATH", "data/uploads")).resolve()


def get_crop_root() -> Path:
    return Path(os.environ.get("OCR_CROP_ROOT", "data/crops")).resolve()
