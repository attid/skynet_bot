# 2026-10-24: Handle expected Telegram errors in join-request moderation

## Контекст
- GlitchTip/Sentry issue #3127 (`SKYNET-J7`): `TelegramForbiddenError: Forbidden: user is deactivated`
  из `routers/welcome.py::cq_join` в ветке «Отказать» при `decline_chat_join_request` для
  деактивированного заявителя.
- 403 не ретраится `middlewares/retry.py`, уходит в глобальный `dp.errors` →
  `middlewares/sentry_error_handler.py`, при этом callback остаётся без ответа, а клавиатура —
  без обновления.
- Ветка «Принять» подавляет только `TelegramBadRequest`; редактирование клавиатуры в обеих
  ветках не защищено от ожидаемых Telegram-ошибок.
- Диагностика Kuzya №102 / разведка №104, паспорт `projects/skynet/summary.md`.

## План изменений
1. [x] `routers/welcome.py` — в `cq_join` для обеих веток перехватывать только ожидаемые
   `TelegramForbiddenError`/`TelegramBadRequest` вокруг approve/decline, логировать `WARNING`
   с `chat_id`, `user_id`, `action` и `callback_id`, отвечать в callback предупреждением.
2. [x] `routers/welcome.py` — клавиатуру обновлять в обеих ветках: успех — ✅/❌, ожидаемая
   ошибка — ⚠️ (без ложного подтверждения модерации); само обновление выполнять с
   `suppress(TelegramBadRequest, TelegramForbiddenError)`, не расширяя перехват на прочие
   исключения.
3. [x] `tests/routers/test_welcome.py` — регрессионные тесты обеих веток: успешные
   approve/decline, 403 и 400 на approve/decline; проверять ответ callback, статус
   клавиатуры и отсутствие события в `dp.errors` (Sentry-путь).
4. [x] `tests/conftest.py` — `mock_telegram.add_response` принимает HTTP-статус, чтобы
   `403`/`400` приходили в aiogram как `TelegramForbiddenError`/`TelegramBadRequest`.
5. [x] Проверки: `ruff format --check`, `ruff check`, `pyright`, целевые и полные тесты.

## Риски и открытые вопросы
- При ожидаемой ошибке клавиатура получает статус ⚠️, а не ✅/❌: действие не подтверждено как
  успешное. Повторное нажатие из этой клавиатуры недоступно; администратор может инициировать
  повторную модерацию из нового уведомления.
- `query.answer` и `edit_reply_markup` тоже могут завершиться ожидаемой Telegram-ошибкой
  (устаревший callback/сообщение) — подавляются только на этих вызовах.
- Глобальный Sentry handler, рассылки, конфигурация, CI и миграции не меняются.

## Верификация
- Тесты `tests/routers/test_welcome.py` на `JoinCallbackData(can_join=True/False)` с ответами
  mock Telegram `403 Forbidden: user is deactivated` и `400 Bad Request`.
- В тестах ошибок: `approveChatJoinRequest`/`declineChatJoinRequest` вызван, callback отвечен
  предупреждением, `editMessageReplyMarkup` показывает ⚠️, observer `dp.errors` пуст.
- Выполнено: `pytest tests/routers/test_welcome.py` — 26 passed; полный `pytest` — 963 passed;
  `ruff check .` и `ruff format --check .` — чисто; `pyright --pythonpath .venv/bin/python` —
  0 errors.
- Ограничение окружения: штатный `pyright` без `--pythonpath` не видел пакеты из-за
  унаследованного `.venv`; проверка выполнена с явным интерпретатором.
