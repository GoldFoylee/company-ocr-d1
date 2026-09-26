"""Regression coverage for the extraction row-number backfill."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "7c2b15a9e4d1_add_extraction_row_number.py"
)


def _migration_module() -> ModuleType:
    spec = spec_from_file_location("row_number_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_row_number_backfill_parses_real_pipeline_crop_paths() -> None:
    migration = _migration_module()

    assert migration._row_number_from_crop_ref(
        "/app/data/real_pipeline_runs/sheet_000123/row01_ds_no.jpg"
    ) == 1
    assert migration._row_number_from_crop_ref(
        "/app/data/real_pipeline_runs/sheet_000123/row15_journey_details.jpg"
    ) == 15


def test_row_number_backfill_handles_cross_platform_and_legacy_paths() -> None:
    migration = _migration_module()

    assert migration._row_number_from_crop_ref(
        r"C:\data\crops\sheet_000123\row09_total_km.jpg"
    ) == 9
    assert migration._row_number_from_crop_ref("/legacy/crops/cell.jpg") == 1
