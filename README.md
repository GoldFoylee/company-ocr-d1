# Draft 1 — Car Log OCR Pipeline

Automates converting handwritten car-log sheets into verified Excel exports. Full spec: link
your Draft 1 doc here.

## Quickstart

1. `cp .env.example .env` and adjust if needed.
2. `./scripts/install_dev_hooks.sh` (required once per clone, before committing).
3. `docker compose up -d --build db app`
4. `docker compose exec app alembic upgrade head`
5. `docker compose exec app python -m scripts.seed_review_demo`
6. `npm --prefix frontend ci`
7. `npm --prefix frontend run dev`

The review UI is available at `http://localhost:5173`. Its seeded data is entirely synthetic;
running the seed command again resets only the synthetic demo sheet.

Run backend tests with `./scripts/test_backend.sh` (optional pytest arguments
follow the script name). This runs `scripts/check_no_raw_fixtures.sh` inside the
dev Docker image before pytest and mounts Git metadata read-only so it also
works from linked worktrees. `./scripts/test_backend.sh --guard-only` checks the
guard without starting the database. Do not replace this command with a bare
`docker compose exec app pytest`, which skips the local guard. Run frontend
tests with `npm --prefix frontend test -- --run`.

Read `PROJECT_CONVENTIONS.md` before opening a PR or starting an agent session.
