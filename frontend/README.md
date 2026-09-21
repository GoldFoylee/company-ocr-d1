# Review UI

The React frontend reads the live D3 review API and never substitutes mocked review data.

## Local development

From the repository root:

1. Copy `.env.example` to `.env` and choose unused `DB_HOST_PORT` and `APP_HOST_PORT`
   values when another worktree is running.
2. Start the real backend with `docker compose up -d --build db app`.
3. Apply migrations with `docker compose exec app alembic upgrade head`.
4. Reset the synthetic demo data with
   `docker compose exec app python -m scripts.seed_review_demo`.
5. If the API is not on port 8000, set `VITE_API_BASE_URL` in `frontend/.env`.
6. Run `npm ci`, followed by `npm run dev`, from this directory.

The synthetic seed is deliberately identifiable and safe to reset. It does not use golden
fixtures, real roster data, or real customer information.

The Task D4 checkpoint—reviewing a real fixture through this UI and confirming its corrected
Excel export—remains deferred until Step 0a provides the anonymized golden fixtures. The
synthetic workflow proves the UI/API interaction only; it does not satisfy that checkpoint.

## Tests

- `npm test -- --run` runs the component tests.
- `npm run test:integration` runs the Testing Library workflow against the live backend.
- `npm run build` type-checks and builds the production bundle.
