# ephemeral-admin-commands (ВЫПОЛНЕНО): эфемерные подтверждения админ-команд + пасхалка за баны

## Контекст
- Bot API 10.2+ (aiogram 3.31 уже в проекте) умеет эфемерные сообщения: сообщение в
  группе видно только одному получателю (`receiver_user_id`) и боту.
- Сейчас подтверждения админ-команд (`Added`, `User banned`, `was set mute ...`) и отказы
  (`You are not admin`) постятся публично в чат и либо висят вечно, либо удаляются таймером.
- Цель: команду удаляем сразу, подтверждение шлём эфемерно автору и не удаляем — остаётся
  только у него в истории. Для `/set_welcome` вдобавок эфемерная копия сохранённого текста.
- Пасхалка: при успешном `/ban`/`/sban` админ получает эфемерку «Ты молодец, поймал злодея
  @user», при повторных банах за день — «...сегодня уже забанено N злодеев. Последний — @user».
- Задача 2 (приветствия/капчи эфемерно) — отдельный план, здесь не делается.

## План изменений
1. [x] `services/ban_stats_service.py` (новый) — `BanStatsService.record_ban(admin_id, today) -> int`:
       счётчик банов админа за сегодня, в памяти (обнуляется при рестарте — приемлемо для пасхалки).
2. [x] `services/app_context.py` — атрибут `ban_stats_service`, инициализация в `from_bot()`.
3. [x] `services/external_services.py` (`UtilsService`) — `reply_ephemeral(message, text, ...)`
       (sendMessage с `ephemeral_message_parameters`; если отправитель — бот/None, fallback на
       обычный reply) и `delete_now(message)` (немедленное удаление с suppress ошибок).
4. [x] `routers/moderation.py` — `/ban`, `/sban`: все `message.reply` → эфемерка; успех =
       `User (ID: X) has been banned.` + пасхалка через `ban_stats_service`; команда удаляется
       сразу; форварды в спам-чат не трогаем. `/unban`, `/test_id` — эфемерки + удаление команды.
5. [x] `routers/admin_core.py` — `_reply_and_cleanup` → эфемерка + немедленное удаление команды;
       `!ro`, `/mute`, `/unmute`, `/show_mute`, `/check_entry_channel`, `/topic` — то же.
       `/all` остаётся публичным (контент по дизайну).
6. [x] `routers/multi_handler.py` — отказы в `universal_command_handler` и подтверждения
       `Removed`/`Added` в `handle_command` → эфемерки; вывод списков (`/list*`) не трогаем.
7. [x] `routers/welcome.py` — `/set_welcome`, `/set_welcome_button`, `/delete_welcome`:
       эфемерки + удаление команды; `/set_welcome` шлёт эфемерную копию сохранённого текста.
8. [x] `tests/fakes.py` — `TestUtilsService.reply_ephemeral`/`delete_now` с записью вызовов;
       `TestAppContext.ban_stats_service = BanStatsService()`.
9. [x] Тесты: unit на `BanStatsService` (дни, изоляция админов); интеграционные — пасхалка
       при втором бане, `ephemeral_message_parameters` в sendMessage, fallback для бота-отправителя;
       правки существующих тестов, которые assert'ят публичные реплаи/удаления.
10. [x] Проверка: `uv run ruff check . && uv run ruff format --check . && pyright && uv run pytest -q`.

## Риски и открытые вопросы
- Эфемерные сообщения не гарантированно доставляются (оффлайн-получатель может не получить).
  Для подтверждений это ок; критичные уведомления (спам-чат) остаются обычными.
- `message_id = 0` у эфемерных: нигде не сохраняем их id, удалять их не нужно по дизайну.
- Счётчик в памяти обнуляется при рестарте процесса — осознанно.
- Команды, присланные через Channel_Bot (sender_chat), сохраняют прежнее публичное поведение
  (fallback в `reply_ephemeral`).

## Верификация
- `uv run pytest tests/test_ban_stats.py tests/routers/test_moderation.py tests/routers/test_admin_core.py tests/routers/test_multi_handler.py tests/routers/test_welcome.py -q`
- В логах/запросах mock_telegram: sendMessage содержит `ephemeral_message_parameters.receiver_user_id`;
  deleteMessage для команды приходит сразу после успешного ответа.
- Ручная проверка в тестовом чате: `/set_captcha on` → 👀 + команда исчезает, «Added» видит
  только админ; второй `/ban` за день → текст с «уже забанено 2 злодеев».
