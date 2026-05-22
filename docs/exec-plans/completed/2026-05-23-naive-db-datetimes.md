# 2026-05-23-naive-db-datetimes: Normalize Chat Repository Datetimes For PostgreSQL

## Контекст
- Production упал на `asyncpg.exceptions.DataError`: `can't subtract offset-naive and offset-aware datetimes`.
- SQL: `UPDATE chats SET last_updated=$1::TIMESTAMP WITHOUT TIME ZONE`.
- Параметр был timezone-aware: `datetime(..., tzinfo=datetime.timezone.utc)`.
- Модель и Alembic schema используют `DateTime` / `TIMESTAMP WITHOUT TIME ZONE`, поэтому runtime должен писать offset-naive datetimes.

## План изменений
1. [x] Шаг 1 — добавить regression test для `ChatsRepository`, который доказывает, что `created_at`, `last_updated`, `left_at` пишутся без `tzinfo`.
2. [x] Шаг 2 — заменить timezone-aware `datetime.now(UTC)` в `db/repositories/chats.py` на единый helper для naive UTC datetime.
3. [x] Шаг 3 — проверить, нет ли других writes в `ChatsRepository` с aware datetime в naive DB columns.
4. [x] Обновить docs/ — не требуется, внешний контракт не меняется.
5. [x] Проверка: focused DB tests, ruff, pyright, full pytest.

## Риски и открытые вопросы
- Риск: перевод DB columns на `timezone=True` потребовал бы миграции схемы; это шире и рискованнее для горячего фикса.
- Риск: SQLite не воспроизводит asyncpg ошибку, поэтому regression test должен проверять `tzinfo is None` напрямую.

## Верификация
- `uv run pytest tests/db/test_repositories.py::test_chat_repository_writes_naive_datetimes_for_postgres_timestamp_columns -q` — passed.
- `uv run pytest tests/db/test_repositories.py tests/db/test_async_repository_methods.py -q` — 18 passed.
- `uv run ruff format --check .` — passed.
- `just lint` — passed.
- `just types` — passed.
- `just test` — 808 passed.
