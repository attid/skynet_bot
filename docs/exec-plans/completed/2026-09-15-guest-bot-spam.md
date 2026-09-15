# Guest Bot Spam: гостевые вызовы ботов — GOOD-юзерам можно, остальным бан

## Контекст

Bot API 10.0 (май 2026) ввёл Guest Mode: бот может ответить в чате, где он НЕ
состоит, по @-упоминанию/вызову от пользователя. Такие сообщения в чате
помечаются «{бот} for {юзер}», и в Bot API несут новое поле
`Message.guest_bot_caller_user` — юзер, который вызвал бота. Тогда же боты стали
видеть «certain messages sent by other bots in groups» — раньше сообщения других
ботов вообще не доставались боту, поэтому в коде их обработки нет.

Спам на скрине: гостевой бот «82mzow9w for Niko» постит видео с кнопками
«ОТКРЫТЬ НАШЕГО БОТА». Раньше SkyNet такое пропускал.

Правило: сообщения от гостевых ботов приравнены к нетекстовым (медиа-пути):
вызывающий со статусом GOOD → разрешить, остальные → спам-флоу (мьют +
форвард в спам-группу с Restore/Kick + удаление).

## План изменений

1. [x] Обновить aiogram 3.24.0 → 3.31.0 (`uv lock --upgrade-package aiogram`,
   constraint `aiogram>=3.20.0` не менялся). Поля
   `guest_bot_caller_user`/`guest_bot_caller_chat`/`guest_query_id` и апдейт
   `guest_message` подтверждены в aiogram.types. Попутно обновлены моки в
   тестах под новые обязательные поля Bot API 9.x/10.x:
   `ChatMemberAdministrator.can_send_welcome_messages`,
   `ChatMemberRestricted.can_react_to_messages`/`can_edit_tag`,
   `Poll.allows_revoting`/`members_only`,
   `PollOption.persistent_id`, `PollAnswer.option_persistent_ids`
   (tests/conftest.py, test_admin_system, test_admin_panel, test_admin_core,
   test_polls, test_mtl_admins_sync_service).
2. [x] `routers/last_handler.py` — `_get_bot_origin(message)`:
   возвращает `(bot_user, guest_caller)`; сообщения с `sender_chat`
   (анонимные админы, каналы) исключены — у них своя давняя обработка.
3. [x] `routers/last_handler.py` — `_check_bot_message` вызывается первым делом
   в `cmd_last_check` (текст) и `cmd_last_check_other` (медиа):
   - гость-вызов, вызывающий GOOD → пропустить (старым можно);
   - гость-вызов, вызывающий NEW/BAD → спам-флоу против ВЫЗЫВАЮЩЕГО
     (общий хелпер `_restrict_forward_and_delete`: restrict caller → форвард
     в `MTLChats.SpamGroup` с кнопками Restore/Kick → удаление →
     `save_bot_user(caller, None, 2)` + `_log_moderation_action`);
   - сообщение бота без гостевой привязки → структурный лог
     (`bot_message (no guest binding) ...`) и пропуск дальнейших проверок —
     полезные боты, добавленные админами, не трогаются.
   `_handle_burst_spam` переведён на общий хелпер (без изменения поведения).
4. [x] Тесты: `tests/test_guest_bot_spam.py` — NEW-вызывающий текст/медиа:
   удаление + мьют вызывающего + BAD; GOOD-вызывающий: ничего; обычный бот
   без привязки: ничего; анонимный админ (GroupAnonymousBot + sender_chat):
   старый путь. Полный прогон: 870 passed.
5. [x] Проверка: `ruff check`, `ruff format --check`, `pyright`, `pytest` — чисто.

## Открытые вопросы (закрываются логами после деплоя)

- Приходят ли гостевые сообщения как обычный `message`-апдейт с полем
  `guest_bot_caller_user` (по докам — да). Если поле придёт, но aiogram его
  потерял бы, сообщение попало бы в лог `bot_message (no guest binding)` —
  это диагностический сигнал.
- Какие именно «certain messages sent by other bots» теперь доставляются —
  по логам `bot_message` увидим.

## Риски

- Ложный мьют GOOD-юзера маловероятен: пропуск по статусу вызывающего.
- Полезные гостевые боты, вызываемые NEW-юзером, будут зэмьючены вместе с
  вызывающим — это и есть запрошенное правило.
- Апдейт aiogram 3.24→3.31: полный прогон 870 тестов + pyright зелёные;
  правки только в тестовых моках, продового кода касаться не пришлось.

## Верификация

- Тесты tests/test_guest_bot_spam.py (5 сценариев).
- После деплоя: логи `guest_bot_spam`/`guest_bot_call_allowed`/`bot_message`
  в чатах; повтор сценария со скрина — сообщение гостевого бота от
  NEW-вызывающего удаляется, вызывающий мьютится.
