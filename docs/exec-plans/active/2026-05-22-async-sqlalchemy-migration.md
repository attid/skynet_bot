# 2026-05-22-async-sqlalchemy-migration: Migrate Runtime Database Access To Async SQLAlchemy

## Контекст
- Бот несколько раз падал в Docker Swarm из-за `dockerexec: unhealthy container`.
- `docker inspect` показал `Health check exceeded timeout (10s)`: `/health` не отвечал, то есть event loop был заблокирован или перегружен.
- Текущий runtime использует sync SQLAlchemy:
  - `start.py` создает `create_engine(config.postgres_url, ...)` и `sessionmaker(bind=engine)`.
  - `db/session.py` делает то же самое.
  - `middlewares/db.py` открывает sync `Session` внутри async aiogram handlers.
- Под всплеском join/captcha событий sync DB call или `session.commit()` может заблокировать event loop и сорвать healthcheck.
- В `pyproject.toml` уже есть `asyncpg>=0.30.0`, поэтому целевая миграция для PostgreSQL должна использовать SQLAlchemy async engine с `postgresql+asyncpg://`.

## Область изменений
- Изменить:
  - `pyproject.toml` / `uv.lock` — убрать `psycopg2-binary`, если больше не нужен runtime, и закрепить async-драйвер/SQLAlchemy.
  - `other/config_reader.py` — добавить/нормализовать async DB URL, если сейчас хранится только sync `postgres_url`.
  - `db/session.py` — заменить sync engine/session pool на async engine/`async_sessionmaker`.
  - `middlewares/db.py` — перевести middleware на `async with` и `await session.commit()/rollback()`.
  - `start.py` — использовать async session pool, корректно инициализировать `load_globals`, scheduler jobs, app context и shutdown engine.
  - `db/repositories/` — перевести repository methods на `AsyncSession`, `await session.execute()`, `await session.flush()`, убрать internal sync commits или сделать их async.
  - `services/database_service.py`, `services/repositories/`, `services/stellar_notification_service.py`, `services/app_context.py` — перевести service-layer DB access на async.
  - `routers/` — заменить type hints `Session` на `AsyncSession` и добавить `await` на async repository/service calls.
  - `other/stellar/`, `scripts/`, `routers/time_handlers.py` — перевести фоновые задачи и operational scripts на async session access.
  - `tests/` — обновить fakes, middleware tests, repository tests и router/service tests под async session/repository API.
- Вероятно создать:
  - `db/async_session.py` или оставить единый `db/session.py` с async API после миграции.
  - `tests/db/test_async_session_middleware.py` или расширить существующие middleware tests.
  - временные compatibility helpers для поэтапной миграции, если потребуется.
- Не менять:
  - Alembic migrations и SQL models без отдельной причины.
  - Telegram business behavior welcome/captcha/moderation.
  - Healthcheck semantics как часть этой миграции, кроме диагностических логов при необходимости.

## План изменений
1. [x] Шаг 1 — инвентаризация sync DB API.
   - Зафиксировать полный список runtime-файлов с `sqlalchemy.orm.Session`, `SessionPool`, `with session_pool()`, `session.execute`, `session.commit`, `session.rollback`.
   - Отдельно выделить hot path: `middlewares/db.py`, `routers/welcome.py`, `routers/admin_core.py`, `routers/polls.py`, `routers/time_handlers.py`, `services/database_service.py`, `services/repositories/chats_repo_adapter.py`, `services/stellar_notification_service.py`.
   - Проверка: `rg -n "sqlalchemy.orm|SessionPool|session_pool|with .*session|session\\.commit|session\\.execute" . --glob '*.py'`.

2. [x] Шаг 2 — определить целевой async contract.
   - Runtime DB session type: `sqlalchemy.ext.asyncio.AsyncSession`.
   - Session factory: `async_sessionmaker[AsyncSession]`.
   - URL: `postgresql+asyncpg://...`.
   - Unit of work: middleware owns commit/rollback for aiogram updates; repositories do not commit unless explicitly documented as standalone script/service API.
   - Service methods that open their own session become `async def`.
   - Router handlers await repository/service calls.

3. [x] Шаг 3 — подготовить конфиг DB URL.
   - В `other/config_reader.py` добавить helper/property вроде `async_postgres_url`.
   - Конвертировать `postgresql://` и `postgresql+psycopg2://` в `postgresql+asyncpg://`.
   - Сохранить `postgres_url` для Alembic/sync scripts только если они остаются sync на переходный период.
   - Тест: unit test на нормализацию URL без реального подключения к БД.

4. [x] Шаг 4 — подготовить async session factory рядом с legacy sync factory.
   - В `db/session.py` создать `async_engine = create_async_engine(...)`.
   - Создать `AsyncSessionPool = async_sessionmaker(async_engine, expire_on_commit=False)`.
   - На первом этапе оставить legacy `engine`/`SessionPool`, чтобы не переключать runtime до миграции repositories/call sites.
   - Предоставить `create_async_session()` для standalone async code.
   - Временно оставить sync aliases только если не вся миграция делается одним PR; иначе удалить sync `SessionPool`.
   - Тест: импорт `db.session` и проверка типа factory без подключения.

5. [x] Шаг 5 — подготовить `DbSessionMiddleware` к async sessions.
   - Добавить async path: `async with self.session_pool() as session:`.
   - На успешном async handler: `await session.commit()`.
   - На exception: `await session.rollback()` и повторно поднять ошибку.
   - Временно сохранить sync path для legacy `start.py` до runtime cutover.
   - Тест: fake async session проверяет commit on success, rollback on exception, session passed into data.
   - Тест: fake sync session подтверждает, что текущий runtime не сломан до полного переключения.
   - Добавлен lazy sync mode для update types, где часть handlers не использует DB session.
   - `callback_query` middleware переведен на lazy sync mode: captcha callbacks больше не открывают и не commit-ят DB session, если handler не обращается к `session`.

6. [x] Шаг 6 — частично переключить `start.py` на async pool для hot path.
   - `dp.chat_member.middleware(...)` переключен на `AsyncSessionPool`.
   - Остальные update types, scheduler jobs и `dp["dbsession_pool"]` временно остаются на sync pool до миграции соответствующих routers/services.
   - `load_globals` переведен на `AsyncSessionPool` и `ChatsRepository.async_load_bot_users`.
   - `on_shutdown` закрывает `async_engine`.
   - Проверка: `uv run python -m py_compile start.py db/session.py middlewares/db.py routers/welcome.py`.

7. [ ] Шаг 7 — перевести базовые repositories.
   - `db/repositories/base.py`: заменить `Session` на `AsyncSession`.
   - `db/repositories/chats.py`, `config.py`, `messages.py`, `payments.py`, `wallets.py` и остальные repository modules:
     - `result = await self.session.execute(...)`.
     - `await self.session.flush()`.
     - `await self.session.commit()` только там, где repository deliberately owns transaction.
   - Сделано частично для hot path:
     - `ConfigRepository.async_load_bot_value`, `ConfigRepository.async_save_bot_value`.
     - `ChatsRepository.async_add_user_to_chat`, `async_remove_user_from_chat`, `async_get_user_by_id`, `async_save_bot_user`.
     - `ChatsRepository.async_load_bot_users`.
     - `MessageRepository.async_send_admin_message`.
   - Сохранить имена методов только если все call sites переводятся на `await` одновременно; иначе добавить временные async-suffixed методы и мигрировать по слоям.
   - Тест: async repository tests на SQLite async или mocked AsyncSession.

8. [x] Шаг 8 — перевести service-layer wrappers.
   - `services/database_service.py`: все методы с DB access используют `AsyncSessionPool` и `async with`.
   - `services/repositories/chats_repo_adapter.py`: methods become async, use `async with`, `await commit`.
   - `services/spam_status_service.py`: repository is optional; runtime uses preloaded in-memory cache instead of sync fallback DB access.
   - `services/app_context.py`: no longer wires sync `ChatsRepositoryAdapter(ctx.db_service.session_pool)`.
   - `services/stellar_notification_service.py`: notification queue writes use async session and async `MessageRepository`.
   - Тест: обновлены `tests/db/test_database_service.py` и service tests.

9. [x] Шаг 9 — перевести hot path `routers/welcome.py`.
   - Type hints: `Session | AsyncSession`.
   - `new_chat_member`, `left_chat_member`, `cmd_update_admin` поддерживают async session.
   - `await ChatsRepository(session).async_add_user_to_chat(...)`.
   - `await ChatsRepository(session).async_get_user_by_id(...)`.
   - `await ConfigRepository(session).async_load_bot_value(...)` и `async_save_bot_value(...)`.
   - `await MessageRepository(session).async_send_admin_message(...)`.
   - `start.async_add_bot_users(...)` добавлен для async chat-member path.
   - `routers.admin_panel.async_unmark_chat_accessible(...)` добавлен для async admin update path.
   - Добавить краткие timing logs вокруг DB/restrict/send_message только если они остаются нужны для incident follow-up.
   - Тест: unit-level tests для join/captcha helper path с async fakes; без реального Telegram/DB.

10. [ ] Шаг 10 — перевести остальные routers.
    - Batch 1: moderation/admin core: `routers/moderation.py`, `routers/admin_core.py`, `routers/admin_system.py`, `routers/admin_panel.py`.
    - Batch 2: poll/talk/last/start/inline/selfmod: `routers/polls.py`, `routers/talk_handlers.py`, `routers/last_handler.py`, `routers/start_router.py`, `routers/inline.py`, `routers/selfmod.py`.
      - Частично сделано:
        - `routers/start_router.py`: `/start` сохраняет bot user через `ChatsRepository.async_save_bot_user`.
        - `routers/talk_handlers.py`: pinned URL для decode загружается через `ConfigRepository.async_load_bot_value`.
        - `routers/polls.py`: message/channel/poll-answer handlers используют async `PollService`/`ConfigRepository`; poll callback больше не требует injected sync session и открывает async session через service.
        - `services/external_services.py`: `PollService` стал async; при `session=None` открывает `AsyncSessionPool` сам и коммитит standalone writes.
        - `start.py`: `message`, `callback_query`, `inline_query`, `chat_member`, `channel_post`, `edited_channel_post`, `poll_answer`, `message_reaction` middleware use `AsyncSessionPool`; legacy sync pool remains only for not-yet-migrated scheduled/script paths.
        - `services/database_service.py`: добавлен async `save_bot_user`; `/start` пишет через `app_context.db_service`, без injected sync session.
        - `services/config_service.py`: добавлены async persistence methods для welcome/delete-income cache paths.
        - `other/antispam_logic.py`: spam fallback bot-user writes use async DB service/session helper.
        - `routers/multi_handler.py`: startup config loader и команды настроек переведены с `create_session`/`ConfigRepository(session)` на async `app_context.db_service`; `on_startup` await-ит loader.
        - `routers/welcome.py`: `/set_welcome`, `/delete_welcome`, `/set_welcome_button`, `/stop_exchange`, `/start_exchange` больше не требуют injected sync session и пишут через async `app_context.db_service`.
        - `routers/welcome.py`: left/admin chat-member persistence no longer falls back to sync `start.add_bot_users`; `start.add_bot_users` sync helper removed.
        - `routers/admin_panel.py`: feature toggle, admin reload, welcome delete/edit FSM handlers and inaccessible-chat persistence write through async `app_context.db_service` instead of `ConfigRepository(session)`.
        - `routers/admin_core.py`: topic mute/unmute/show expired mute cleanup, message-reaction mute and `/alert_me` persist through async `app_context.db_service`; mention target lookup uses async `db_service.get_user_id`.
        - `routers/admin_system.py`: `/summary`, `/sync`, `/resync`, edited channel stale sync cleanup and `/update_chats_info` persist through async `app_context.db_service`.
        - `routers/moderation.py` / `services/external_services.ModerationService`: ban/unban/test_id username/status paths use awaited async DB access and async bot-user persistence.
        - `services/external_services.AIService.remind`: pinned message fallback reads use async `ConfigRepository` calls.
        - `services/database_service.py`: добавлен async transactional summary builder для saved messages.
        - `routers/last_handler.py`: saved messages, pinned URL/id, last-message dates, topic mutes and bot-user status writes go through async `app_context.db_service`; mention lookup uses async `db_service.get_user_id`.
        - `routers/selfmod.py`: mute approval persists TopicMutes through async `app_context.db_service`.
        - `services/database_service.py`: добавлены async wrappers для `update_user_chat_date` и `save_message`.
        - `tests/fakes.py`: `FakeSession` поддерживает awaited `execute/commit/rollback/flush` для async repository/router tests.
    - Batch 3: stellar/time: `routers/stellar.py`, `routers/time_handlers.py`.
      - Частично сделано:
        - `routers/time_handlers.py`: frequent `cmd_send_message_1m` scheduler job uses async session pool and `MessageRepository.async_load_new_messages`; scheduler wiring passes `AsyncSessionPool` for this job.
    - После каждого batch запускать focused tests и `just types` если объем ошибок контролируем.

11. [ ] Шаг 11 — перевести фоновые сервисы и scripts.
    - `services/stellar_notification_service.py`: `async with self.session_pool()`.
    - `scripts/check_stellar.py`, `scripts/update_report.py`: использовать async session pool или явно оставить sync operational path с отдельным sync engine, если миграция runtime-only.
    - `other/stellar/*.py`: заменить `Session` hints и async DB calls.
    - Решение по scripts зафиксировать в плане выполнения: full async предпочтительнее, runtime-only быстрее и безопаснее.

12. [ ] Шаг 12 — обновить тестовые fakes.
    - `tests/fakes.py`: добавить `FakeAsyncSession` или сделать существующий `FakeSession` async-compatible.
    - Поддержать `async with`, `await commit`, `await rollback`, `await execute`, `await flush`.
      - Частично сделано: `FakeResult` awaitable, `FakeSession.commit/rollback/flush` возвращают awaitable sentinel, добавлен `tests/test_fakes_async_session.py`.
    - Обновить `tests/conftest.py` middleware/session injection.
    - Обновить tests that assert sync fake behavior.

13. [ ] Шаг 13 — обновить repository integration tests.
    - Перевести `tests/db/test_repositories.py` на `pytest.mark.asyncio`.
    - Использовать `sqlite+aiosqlite:///:memory:` только если добавить dev dependency `aiosqlite`; иначе mock AsyncSession или PostgreSQL test fixture.
    - Не использовать реальные внешние DB.
    - Проверка: `uv run pytest tests/db -q`.

14. [ ] Шаг 14 — обновить зависимости.
    - Убедиться, что `asyncpg` остается в dependencies.
    - Если sync PostgreSQL runtime больше не нужен, удалить `psycopg2-binary`.
    - Если async SQLite tests выбраны, добавить `aiosqlite` в dev dependencies.
    - Выполнить `uv lock`.

15. [ ] Шаг 15 — статическая проверка call sites.
    - `rg -n "from sqlalchemy.orm import Session|SessionPool|create_engine\\(|sessionmaker\\(|with .*session_pool\\(|with create_session\\(|session\\.commit\\(|session\\.rollback\\(" . --glob '*.py'`.
    - Для каждого оставшегося совпадения явно классифицировать:
      - legacy sync script intentionally left;
      - Alembic-only;
      - missed runtime path that must be fixed.

16. [ ] Шаг 16 — верификация event-loop nonblocking behavior.
    - Добавить временный или тестовый probe, который вызывает DB-heavy path параллельно с `/health` handler.
    - Проверить, что health handler отвечает во время DB operations.
    - Минимум: тест middleware/repository не должен использовать sync `time.sleep`/blocking DB.

17. [ ] Шаг 17 — полная локальная проверка.
    - `uv run ruff format --check .`
    - `just lint`
    - `just types`
    - `just test`
    - Если тесты слишком широкие для одного прохода, сначала focused suites, затем полный прогон перед merge.

18. [ ] Шаг 18 — staging/prod rollout.
    - Собрать Docker image локально или в CI.
    - На staging проверить startup, migrations, `/health`, basic Telegram polling.
    - Проверить logs на отсутствие `greenlet_spawn has not been called`, `MissingGreenlet`, `coroutine was never awaited`.
    - Проверить `docker inspect <container> --format '{{range .State.Health.Log}}{{println .Start .ExitCode .Output}}{{end}}'`.
    - После merge/push to main выполнить обязательный `just push-gitdocker latest`.

19. [ ] Обновить docs/.
    - Добавить короткую заметку в `docs/` или существующий conventions doc: runtime DB access is async SQLAlchemy, repositories are async, middleware owns transaction.
    - Обновить AGENTS/README не нужно, если правило уже покрыто repo guidelines.

20. [ ] Завершение плана.
    - После реализации отметить все пункты.
    - Переместить этот файл в `docs/exec-plans/completed/`.

## Риски и открытые вопросы
- Риск: миграция широкая; почти все repository call sites станут `await`, поэтому возможны пропущенные coroutine calls.
- Риск: SQLAlchemy async ORM может выбросить `MissingGreenlet`, если где-то используется lazy relationship loading после session boundary.
- Риск: тесты на SQLite могут отличаться от PostgreSQL JSON/ARRAY behavior; для repository tests лучше использовать mock servers/fixtures или PostgreSQL test container, если он уже есть.
- Риск: `scripts/` могут использовать DB вне bot runtime. Нужно решить, мигрируем их сразу или оставляем отдельный sync engine на переходный период.
- Риск: некоторые repository methods сейчас сами делают `commit()`. Нужно унифицировать transaction ownership, иначе появятся двойные/ранние commits.
- Открытый вопрос: делать миграцию одним большим PR или сначала перевести только runtime hot path, оставив scripts sync до следующего PR.
- Открытый вопрос: нужно ли сохранять `postgres_url` sync-compatible для Alembic и operational scripts.

## Верификация
- Reproduce исходный риск:
  - Запустить бот локально/staging.
  - Сымитировать поток join/captcha updates или targeted unit/integration path.
  - Параллельно опрашивать `/health` каждые 1-2 секунды.
- Ожидаемое поведение:
  - `/health` отвечает быстро и не timeout-ится во время DB operations.
  - Aiogram handlers получают `AsyncSession`.
  - Repository/service tests проходят с async session fakes или async test DB.
  - В логах нет `Health check exceeded timeout`, `MissingGreenlet`, `coroutine was never awaited`.
- Команды:
  - `uv run ruff format --check .`
  - `just lint`
  - `just types`
  - `just test`
  - `docker service ps skynet_bot --no-trunc`
  - `docker inspect <container_id> --format '{{range .State.Health.Log}}{{println .Start .ExitCode .Output}}{{end}}'`
