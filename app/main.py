from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import review

app = FastAPI(title="Draft 1 — Car Log OCR Pipeline")

# The React dev server runs on a different origin (localhost:5173 by default)
# than this API (localhost:8000). Without CORSMiddleware, the browser blocks
# the frontend's requests to this backend during local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # add your deployed frontend origin later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review.router, prefix="/review", tags=["review"])
app.add_api_route(
    "/sheets/{sheet_id}/verify",
    review.mark_sheet_verified,
    methods=["POST"],
    response_model=review.SheetVerificationResponse,
    tags=["sheets"],
    summary="Mark a sheet as fully verified (alias)",
    include_in_schema=False,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check — used by CI, Docker healthchecks, and the frontend
    to confirm the API is up before making real requests."""
    return {"status": "ok"}
