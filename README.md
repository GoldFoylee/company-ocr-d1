# Draft 1 — Car Log OCR Pipeline

Automates converting handwritten car-log sheets into verified Excel exports. Full spec: link
your Draft 1 doc here.

## Quickstart

1. `cp .env.example .env` and adjust if needed.
2. `docker compose up -d db`
3. `python -m venv .venv && source .venv/bin/activate`
4. `pip install -r requirements-dev.txt`
5. `pre-commit install`
6. `alembic upgrade head`
7. `uvicorn app.main:app --reload`
8. `pytest`

Read `PROJECT_CONVENTIONS.md` before opening a PR or starting an agent session.
