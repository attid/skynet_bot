# 2026-05-22-startup-cache-restore-audit: Fix Startup Cache Restoration Mismatches

## Контекст
- После миграции DB runtime на async часть настроек хранится в БД, а используется через in-memory сервисы.
- Найден баг: `BotValueTypes.Votes` после рестарта загружался в обычные poll votes, а weighted polls читали `vote_weights`.
- При аудите найден похожий риск для `BotValueTypes.EntryChannel`: startup выставляет feature flag, но runtime читает значение канала из `ConfigService`.

## План изменений
1. [x] Шаг 1 — добавить regression tests для восстановления `Votes` и `EntryChannel` после `command_config_loads`.
2. [x] Шаг 2 — добавить cache API для `entry_channel` в `ConfigService` и fake service.
3. [x] Шаг 3 — загрузить `EntryChannel` в startup cache и синхронизировать toggle add/remove.
4. [x] Шаг 4 — заменить runtime чтение `entry_channel` на cache API.
5. [x] Обновить docs/ — не требуется, контракт пользовательски не меняется.
6. [x] Проверка: focused tests, ruff, pyright, full pytest.

## Риски и открытые вопросы
- Риск: `ConfigService.load_value()` используется для legacy sync repo paths; менять его поведение широко нельзя.
- Риск: `entry_channel` значение может быть строкой (`@channel`) или числом (`-100...`); cache должен сохранять тип без преобразования.

## Верификация
- Regression test падал до фикса и проходит после.
- `run_entry_channel_check` и join path видят сохраненный channel после startup.
- Проверено:
  - `uv run pytest tests/routers/test_multi_handler.py::test_command_config_loads_restores_entry_channel_value -q`
  - `uv run pytest tests/services/test_config_service.py::TestEntryChannel -q`
  - `uv run pytest tests/routers/test_multi_handler.py tests/routers/test_welcome.py tests/services/test_config_service.py -q`
  - `uv run ruff format --check ...`
  - `uv run ruff check ...`
  - `just types`
  - `just lint`
  - `just test` — 807 passed.
