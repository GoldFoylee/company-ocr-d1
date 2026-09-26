"""Request and response schemas for sheet ingestion."""

from pydantic import BaseModel


class SheetUploadResponse(BaseModel):
    """Persisted result returned after synchronous OCR processing."""

    sheet_id: int
    row_count: int
    extraction_count: int
    status: str
