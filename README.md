# Draft 1 — Car Log OCR Pipeline

Automates converting handwritten car-log sheets into verified Excel exports. Full spec: link
your Draft 1 doc here.

## Quickstart

1. `cp .env.example .env` and adjust if needed.
2. `docker compose up -d --build db app`
3. `docker compose exec app alembic upgrade head`
4. `docker compose exec app python -m scripts.seed_review_demo`
5. `npm --prefix frontend ci`
6. `npm --prefix frontend run dev`

The review UI is available at `http://localhost:5173`. Its seeded data is entirely synthetic;
running the seed command again resets only the synthetic demo sheet.

Run backend tests with `docker compose exec app pytest` and frontend tests with
`npm --prefix frontend test -- --run`.

Read `PROJECT_CONVENTIONS.md` before opening a PR or starting an agent session.
