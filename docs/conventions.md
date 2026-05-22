# Conventions

## Scope
Coding and integration conventions for this repository.

## Code Structure

1. Handlers
- Keep router handlers minimal.
- Parse input, enforce access checks, call services, send response.
- Non-trivial behavior belongs in `services/` or focused modules in `other/`.

2. Services
- Services orchestrate business flow and adapters.
- Prefer explicit dependencies via `AppContext`.
- Keep method names behavior-oriented.

3. Persistence
- DB reads/writes go through repositories in `db/repositories/`.
- Avoid ad-hoc SQL in routers.
- Runtime DB access uses SQLAlchemy `AsyncSession` from `db.session.AsyncSessionPool`.
- Do not import `sqlalchemy.orm.Session` or create sync SQLAlchemy engines in bot runtime code.
- Repositories should not own transactions. Middleware, service unit-of-work methods, or standalone scripts call `await session.commit()` / `await session.rollback()`.

## Data and Contracts

1. Parse, do not guess.
- Validate required fields for commands/events.
- For channel contracts (`#skynet ... command=...`), reject invalid payloads with explicit error paths.

2. Keep contracts explicit.
- If changing external/event behavior, update `docs/contracts` (to be added in later iteration) and tests in the same change.

## Logging

1. Use `loguru`.
- No `print()` in runtime paths.
- Log moderation actions and failures with stable fields (`action`, `chat_id`, `user_id`, `source` where applicable).

2. Prefer artifacts for moderation decisions.
- Ban/restrict/unban flows should leave observable artifacts (logs and/or SpamGroup messages).

## Tests

### General

1. Add tests for behavior changes.
- Router-level behavior in `tests/routers/`.
- Repository/service logic in dedicated test modules.

2. Keep tests deterministic.
- Use mocks/fakes for network and external APIs.
- Avoid hidden time/random coupling unless explicitly controlled.

### External boundaries — mandatory mock servers

Any test that exercises code touching an external system MUST go through
the project's local mock servers in `tests/conftest.py`. Do not invent
local duck-typed fakes for aiogram / Stellar / Grist clients — they hide
real serialization and API drift bugs.

| Boundary | Fixture(s) | Where | Forbidden alternatives |
|---|---|---|---|
| Telegram | `mock_telegram`, `router_bot`, `router_app_context` | `tests/conftest.py:88,462,477` | Local `FakeMessage`/`FakeCallback` classes, `AsyncMock()` used as a `Bot`, `.as_(bot=AsyncMock())` tricks |
| Stellar (Horizon) | `mock_horizon`, `horizon_server_config` (auto-wired in `router_app_context`) | `tests/conftest.py:307` | Direct patching of `stellar_sdk` / horizon client, hand-rolled JSON fakes |
| Grist | `mock_grist`, `grist_server_config` | `tests/conftest.py:393` | Monkeypatching `grist_manager` methods per-test (use the server + `state.add_response` / seeded records) |

If you need to shape a response, call `state.add_response(method, dict)`
on the corresponding mock state object — don't bypass the server.

Service-level fakes (`FakeGristService`, `FakeStellarService`, etc. in
`tests/fakes.py`) are fine for unit-testing higher layers that depend on
the service abstraction, not the raw client.

## Commit Style

Use Conventional Commits:
- `feat(scope): ...`
- `fix(scope): ...`
- `refactor(scope): ...`
- `docs(scope): ...`
- `chore(scope): ...`
