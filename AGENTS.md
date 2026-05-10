# Repository Guidelines

## Project Structure & Module Organization
- `start.py`: Entry point. Creates bot, wires `AppContext`, registers middlewares/routers, starts polling.
- `routers/`: Aiogram handlers grouped by feature. Keep thin, delegate to services.
- `middlewares/`: Cross‑cutting concerns (`db`, `app_context`, `throttling`, `emoji_reaction`, etc.).
- `services/`: Application services/use‑cases. DI container is `services/app_context.py`.
  - `services/interfaces/`: Repository interfaces (protocols).
  - `services/repositories/`: Adapters to `db/` repositories.
- `shared/domain/`: Domain entities and enums (no aiogram/db imports).
- `shared/infrastructure/database/`: SQLAlchemy models + Alembic.
- `db/`: SQLAlchemy repositories and database helpers (legacy Firebird/Mongo logic is adapted here).
- `other/`: Utilities and integrations (Telegram helpers, external APIs, caching, etc.).
- `tests/`: Unit/integration tests (use fakes/mocks; see `tests/fakes.py`).
- `scripts/`: Operational scripts (reports, exchanges, ledger checks).
- `deploy/`: Systemd units and update scripts for production.
- `docs/`: Design and improvement notes.

## Build, Test, and Development Commands
- Install deps: `uv sync`
- Configure: copy `.env.example` to `.env` and fill required keys.
- Run bot locally: `uv run python start.py`
- Clean caches/logs: `./clean.sh`
- Quality (via justfile):
  - Lint: `just lint` (ruff check)
  - Format: `just format` (ruff format)
  - Type check: `just types` (pyright)
  - Tests: `just test` (pytest)
  - Secret scan: `just secrets` (gitleaks; requires local install or use Docker image `zricethezav/gitleaks`)
- Docker image (Just):
  - Build: `just build latest`
  - Push to GHCR: `just push-gitdocker latest` (positional arg; do NOT use `tag=latest`)
- CI: GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to main — gitleaks, ruff, pyright, pytest.
  - Gitleaks allowlist: `.gitleaks.toml` (excludes `.env.example`, `docs/`).

## Coding Style & Naming Conventions
- You must communicate in Russian; code comments and docstrings must stay in English.
- Python 3, 4‑space indentation, UTF‑8.
- Names: `snake_case` for functions/vars, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Prefer type hints across public functions; keep routers thin and delegate to services in `other/`.
- Logging: use `loguru` logger; no `print()` in runtime paths.
- Telegram parse mode:
  - Bot uses HTML parse mode; always escape user-provided text and any `<`/`>` in messages (use `html.escape()` or `&lt;...&gt;`).

## Testing Guidelines
- Add `pytest` tests under `tests/` for new logic (pure utils in `other/`, DB helpers, router helpers via unit‑level functions).
- Keep tests isolated from Telegram/DB: mock network and DB calls; use small fixtures.
- External boundaries (Telegram / Stellar / Grist) MUST go through the mock servers in `tests/conftest.py` (`mock_telegram`, `mock_horizon`, `mock_grist`). No local aiogram/stellar fakes. See `docs/conventions.md#tests`.
- Run locally (if added): `uv run pytest -q`.

## Commit & Pull Request Guidelines
- Use Conventional Commits: `feat(scope):`, `fix(scope):`, `refactor(scope):` (emojis optional, keep scope meaningful).
- Before every `git push`, run `uv run ruff format --check .` in addition to the relevant lint/type/test checks; do not push while the format check fails.
- PRs: concise description, motivation, screenshots/log snippets when UI/log behavior changes; reference issues; note config or migration impacts.
- Keep diffs focused; include follow‑ups in separate PRs.

## Deployment
- **After every `git push` to main, always run `just push-gitdocker latest`** to build and push the Docker image to GHCR. The production server pulls from GHCR, so without this step the deploy won't happen.

## Security & Configuration Tips
- Never commit secrets. `.env` is ignored; keep tokens/DSNs there. Validate critical settings on startup.
- Limit admin capabilities to configured chat/user IDs; avoid username‑based checks.
- Be mindful of rate limits; use provided throttling middleware.

## Router/Agent Instructions
- New feature: create `routers/<feature>.py` with `register_handlers(dp, bot)`. Optionally set `register_handlers.priority` (lower loads earlier).
- Keep handlers thin: move use‑cases to `services/`, keep integrations in `other/`, and DB access in `db/`.

## Task Intake Protocol
- For each new task, first analyze the requirements and explicitly state which files or directories need to change.
- `docs/exec-plans/` is always pre-approved for edits needed to create, update, move, or complete execution plans.
- Do not edit any other files until there is direct permission that names the specific file(s) or directory that may be modified.
- Shortcut: a user reply with a single `+` means "you may modify all files/directories you proposed in the immediately previous message."

## AI-First Execution Plan Rule
- For every non-trivial task, create an execution plan file in `docs/exec-plans/active/` before code changes.
- Use `docs/exec-plans/TEMPLATE.md` as the required format.
- When task is completed, move the plan file to `docs/exec-plans/completed/` and mark checklist items.
