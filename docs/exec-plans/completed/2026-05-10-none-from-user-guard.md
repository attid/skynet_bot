# 2026-05-10: Guard missing from_user in reply/antispam paths

## Контекст
- В production-логе поймана ошибка `'NoneType' object has no attribute 'id'` на Telegram update с reply-сообщением.
- Верхнее сообщение имеет `from_user`, поэтому наиболее вероятные источники — вложенные сообщения (`reply_to_message.from_user`) или Telegram-сообщения от `sender_chat`, где `from_user` может быть `None`.
- Нужно убрать падения, не меняя поведение обычных пользовательских сообщений.

## План изменений
1. [x] Добавить тест для `TalkService.answer_notify_message`: reply на сообщение без `from_user` не должен падать и должен ничего не отправлять.
2. [x] Добавить guard в `services/external_services.py` для `reply_to_message`, `reply_to_message.from_user` и `external_reply`.
3. [x] Добавить тесты для `other/antispam_logic.py`: `check_spam` не падает на сообщении без `from_user`, а `sender_chat` корректно используется в `set_vote`.
4. [x] Обновить `other/antispam_logic.py`: безопасно вычислять actor id/username, пропускать антиспам без идентифицируемого отправителя.
5. [x] Проверка: точечные pytest для измененных тестов, затем ближайший общий набор по затронутым файлам.

## Риски и открытые вопросы
- Без stack trace исходная строка падения не доказана, поэтому фикс закрывает два наиболее вероятных пути.
- Telegram `restrict` работает по user id; для `sender_chat` бан канала может требовать отдельный API, поэтому текущая правка не должна расширять модерационное поведение.

## Верификация
- Красная фаза: новые тесты падали на текущем коде с `AttributeError`.
- Зеленая фаза: тесты проходят после guards.
- Регрессия: `uv run pytest tests/services/test_ai_service_talk.py -q` и `uv run pytest tests/other/test_antispam_logic.py -q` проходят.
