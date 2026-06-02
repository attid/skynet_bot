# 2026-06-02-scheduled-message-forbidden: не отправлять ожидаемый forbidden в Sentry

## Контекст
- `cmd_send_message_1m` пишет `logger.error` при Telegram `Forbidden: bot was kicked from the supergroup chat`.
- Контейнер не падает, но Sentry получает error-level событие для ожидаемой delivery failure.
- Запись `t_message` уже помечается как failed (`was_send=2`), поэтому нужно снизить уровень логирования и добавить полезные поля.

## План изменений
1. [x] Добавить тест на `TelegramForbiddenError` в scheduled message delivery.
2. [x] В `routers/time_handlers.py` обработать `TelegramForbiddenError` отдельно как warning без проброса.
3. [x] Сохранить текущее поведение для неожиданных исключений.
4. [x] Обновить/добавить тесты.
5. [x] Проверка: targeted pytest, format/lint/types, полный pytest при необходимости.

## Риски и открытые вопросы
- Sentry может собирать warning logs, если настроен очень широко, но стандартно шум создается error-level логом.
- Нельзя скрывать неожиданные ошибки Telegram/API: отдельный handler должен касаться только forbidden delivery failure.

## Верификация
- Тест на forbidden должен сначала падать из-за `logger.error`, затем проходить после перехода на warning.
- Существующий успешный тест отправки scheduled message должен остаться зеленым.
- `uv run pytest tests/routers/test_time_handlers.py::test_cmd_send_message_1m_handles_forbidden_as_delivery_failure -q`
- `uv run pytest tests/routers/test_time_handlers.py -q`
- `uv run ruff format --check .`
- `just lint`
- `just types`
- `just test`
