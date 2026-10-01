# ephemeral-topic-passing: передача message_thread_id во всех топик-чувствительных отправках

## Контекст
- `/show_mute` (и любые эфемерки/ответы в форум-чатах) прилетает в «Общий», а не в топик команды.
- Причина: `UtilsService.reply_ephemeral` (`services/external_services.py:716-733`) вызывает `bot.send_message` без `message_thread_id`.
- User: «проебали в прошлом заходе, надо передавать конечно. ГО и проверь ВСЕ вызовы чтоб где надо добавить передачу топика».

## План изменений
1. [x] `services/external_services.py` — `reply_ephemeral`: передавать `message_thread_id=message.message_thread_id` в `send_message` (эфемерная ветка).
2. [x] Аудит ВСЕХ вызовов отправок (routers/, services/, other/, middlewares/, start.py, scout-агент): разметка NEEDS_TOPIC / NO / AMBIGUOUS.
3. [x] Добавить передачу топика туда, где NEEDS_TOPIC (прямые send_message и хелперы).
4. [x] Обновить/добавить тесты: эфемерка в форуме несёт `message_thread_id`; личка — не несёт.
5. [x] Проверка: `uv run pytest` (затронутые файлы) + `uv run ruff check` / `ruff format --check`.

## Риски и открытые вопросы
- Часть чатов-констант (SpamGroup и т.п.) может быть форумом — определить по коду (если туда шлют без topic и это форум, ответ уедет в General).
- Fallback-ветка `message.reply` топик наследует сама — не трогать лишний раз.
- `AMBIGUOUS` кейсы (форум «иногда») — покрыть передачей `message_thread_id` опционально, это безопасно для не-форумов (Bot API игнорирует None).

## Верификация
- Юнит: мок-сообщение в форуме (`is_forum=True`, `message_thread_id=42`) → в `bot.sent[0]` есть `message_thread_id=42` и `ephemeral_message_parameters.receiver_user_id`; личка → `message_thread_id is None` (не в payload).
- Интеграционно: существующие тесты `tests/routers/test_admin_core.py` (show_mute и соседи) зелёные.
- `uv run ruff check`, `uv run ruff format --check`.