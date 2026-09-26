# Draft 1 — Project Conventions

Read this before writing any code or opening a plan. Applies to human contributors and any
agent session (ECC or otherwise) working in this repo.

## Branching
- `main` = production. Protected: PR-only, CI must pass, 1 approval required, no direct pushes.
- `develop` = integration branch. Protected: PR-only, CI must pass.
- Feature branches: `feature/<short-name>`, branched from `develop`, PR back into `develop`.
- `develop` → `main` promotion happens via its own PR, after a feature (or batch of features)
  has been verified against a real billing cycle's data.

## Stack
- Backend: Python 3.11 (pinned via `.python-version` — do not let this drift; see
  the setup notes on the python/python3 interpreter mismatch), FastAPI, SQLAlchemy +
  Alembic, PostgreSQL 16.
- Frontend: React (Vite + TypeScript), calling the backend over HTTP; CORS is
  configured in `app/main.py` for the local dev origin — add any new deployed
  frontend origin there too.
- Git host: GitHub. CI config (`.github/workflows/ci.yml`) assumes GitHub Actions.
- OpenCV (headless) for grid/cell detection.
- The OCR backend is pluggable behind `app/ocr/base.py`'s `Recognizer` interface — business
  logic and the review API must never import a specific OCR library directly.
- Excel export via openpyxl/pandas, matching accounts' existing column layout exactly.

## Docker platform requirement
- The `app` service in `docker-compose.yml` must specify `platform: linux/amd64`. PaddlePaddle
  3.3.1 has no arm64 wheel, so Apple Silicon machines cannot build the app image natively for
  linux/arm64. Compose applies this base-service platform pin when merging the standard
  `docker-compose.override.yml` too; do not duplicate it in `Dockerfile.dev` or the override.

## Testing requirement
- Every new module ships with unit tests in the same PR — no follow-up "add tests later" PRs.
- Any change touching the CV/OCR pipeline must run against the golden fixtures in
  `tests/fixtures/` (real sample sheets + hand-verified expected output) and must not regress
  their expected output.
- Target ≥80% coverage repo-wide (enforced in CI). The validation-rule engine specifically
  should aim for full branch coverage, since it's the last line of defense on financial fields.
- No PR merges without CI green.

## Raw-fixture guard and public branches
- **Before committing, every contributor must install the repository's pre-commit hook**
  with `./scripts/install_dev_hooks.sh`. The hook runs
  `scripts/check_no_raw_fixtures.sh` before Git creates a commit. The tracked
  `.pre-commit-config.yaml` alone does not install a hook in a clone. Check
  that `$(git rev-parse --git-path hooks)/pre-commit` exists and is executable.
- Do not use `git commit --no-verify` to skip the hook. An exceptional bypass
  requires a deliberate, documented reason in the PR and a successful manual
  run of `scripts/check_no_raw_fixtures.sh` before pushing. A failing raw-fixture
  check is never a reason to bypass it. Git technically permits `--no-verify`;
  this is a contributor requirement, not a claim that Git makes bypass impossible.
- The routine local Docker backend test command is `./scripts/test_backend.sh`.
  It runs the guard inside the dev image before pytest, including in linked
  worktrees. Bare `docker compose exec app pytest` does not run the guard.
- CI also runs the guard in both GitHub Actions jobs. This is a **develop/main
  merge gate**, not a pre-push barrier: a raw fixture pushed to a public feature
  branch has already reached the public repository, even if its PR never merges.
  The pre-commit hook, run before a push, is the first line of defense.
- This guard checks Git-tracked files under `tests/fixtures/raw/`. It is not a
  general scan for sensitive content elsewhere. Review all data before staging
  and pushing, including files under other paths.

## Stop conditions (agent sessions, every task)
Unless a human explicitly says otherwise for that specific action, in that specific session:
- Never merge or approve a pull request. Open it (draft or ready) and stop; a human merges.
- Never change repository settings (branch protection, collaborators, secrets, webhooks, etc.).
- Never `--force`/`--amend` on `develop` or `main`. The one standing exception:
  force-push-with-lease **a feature branch to itself**, after rebasing that same branch on its
  own base — never onto `develop` or `main`, and never another contributor's branch.

These hold regardless of how confident the session is that CI is green or the change is safe.
When a task's own instructions repeat or narrow these (e.g. "same stop conditions as always"),
that phrase means exactly this section.

## Data logging (hard requirement, not an implementation detail)
Every field extraction must be written to the `extractions` table with:
image crop reference, raw OCR guess, confidence score, rule-flag result (and why), the
human-corrected final value, and metadata (vehicle, branch, date, field name, reviewer id,
timestamp). Draft 2's training pipeline depends on this schema existing exactly as specified —
do not simplify it "for now."

## Working style (multi-agent / ECC)
- Plan before implementing: `/ecc:plan` for anything beyond a trivial fix — read the plan
  before approving it.
- TDD: write the failing test first for pipeline and business-logic code.
- Fresh-context review (`/code-review`) before opening a PR.
- Parallel work: when multiple agent sessions run at once, use separate git worktrees per
  component (e.g. grid detection, OCR wrapper, validation engine each in their own worktree)
  so working directories never collide. Merge each into `develop` via its own PR once its own
  tests pass — don't let one large branch accumulate every component at once.
- Before starting Docker services in a new worktree, give that worktree a unique
  `COMPOSE_PROJECT_NAME`, `DB_HOST_PORT`, and `APP_HOST_PORT` in its local `.env` (for example,
  `feature-grid-detection`, `5433`, and `8001`). Both ports use the same Compose substitution
  pattern defined in `docker-compose.yml`; the containers still listen on `db:5432` and
  `app:8000` inside their isolated Compose network. `DATABASE_URL` therefore remains pointed at
  `db:5432`. Every simultaneously running worktree must use a distinct project name and host
  ports so its containers, volume, database, and API do not collide with another worktree.
