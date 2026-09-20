from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check — used by CI, Docker healthchecks, and the frontend
    to confirm the API is up before making real requests."""
    return {"status": "ok"}
