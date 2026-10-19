# decode-full-data-regression: починить /decode и «Скайнет декодируй» + усиленное логирование

## Контекст
- В комментариях под постом (linked discussion, чат `-1001784614029`) оба способа декодирования сломаны:
  - `/decode` → «Параметр не распознан. Надо xdr или ссылку на тулзу»;
  - `/decode <https://eurmtl.me/sign_tools/...>` → тот же текст;
  - `Скайнет декодируй` реплаем на сообщение со ссылкой → «Ссылка не найдена» (проверить отдельно, см. логи ниже).
- Прод-лог 2026-10-19 13:51 показал настоящие причины (роутер их прячет в общий текст, поэтому в чате не видно):
  - `13:51:08 | ERROR | routers.stellar:cmd_decode:51 - list index out of range` — `/decode` без аргумента: `parts[1]` в `routers/stellar.py:40`.
  - `13:51:19 | ERROR | routers.stellar:cmd_decode:51 - 'ConfigService' object has no attribute 'is_full_data'` — `/decode <url>`: `routers/stellar.py:41` вызывает метод, которого после разделения `ConfigService` / `FeatureFlagsService` больше нет.
- Регрессия: `is_full_data` живёт в `services/feature_flags.py:170` (`FeatureFlagsService.is_full_data`), в `services/config_service.py` остался только `is_feature_enabled`. Никто кроме `routers/stellar.py` его не зовёт.
- Почему не поймали тестами: `FakeConfigService` (`tests/fakes.py:565`) до сих пор имеет `is_full_data` (`tests/fakes.py:628`), т.е. фейк врёт про реальный контракт.
- Дополнительно: логирование неинформативно — в логе видно только `skyuser.resolve` и голое `logger.error(e)` без чата/топика/текста/трейсбека, воспроизвести и понять причину с первого раза нельзя. User: «можем сделать версию с усиленным логированием, я повторю обе команды».

## План изменений
1. [ ] `routers/stellar.py` — `cmd_decode`:
   - `full_data` брать из `ctx.feature_flags.is_full_data(message.chat.id)` (fallback `False`, если сервис не передан).
   - Не падать на `/decode` без аргументов: разбирать аргументы безопасно; если аргумента нет — брать XDR/ссылку из `reply_to_message.text` и его `entities`, иначе отвечать подсказкой (`/decode xdr` или `/decode <ссылка на тулзу>`).
   - Убрать «слепой» `except Exception` с фиксированным текстом: логировать `logger.exception` с контекстом (chat_id, message_thread_id, is_topic_message, message_id, текст) и отдавать в чат реальную причину (`тип ошибки: str(e)`), чтобы не гадать по скриншотам.
   - DEBUG-лог входа: текст, `parts`, определённый путь (xdr/url), `full_data`, thread id.
2. [ ] `routers/talk_handlers.py` — `cmd_last_check_decode` («Скайнет декодируй»): DEBUG-лог входа (есть ли `reply_to_message`, его текст, найденные `entities`, извлечённый url) и `logger.exception` + причина в ответе при падении `check_url_xdr`; сейчас любая ошибка молча превращается в «Ссылка не найдена».
3. [ ] `other/web_tools.py` — `get_eurmtl_xdr`: логировать запрошенный URL, HTTP-статус и форму ответа; не глотать исключение в `except Exception` (логировать `exception`), ошибку отдавать вызывающему как исключение, чтобы пользователь видел «тулза не отдала XDR», а не «Параметр не распознан».
4. [ ] `tests/fakes.py` — убрать `is_full_data`/`set_full_data`/`_full_data` из `FakeConfigService` (контракт должен совпадать с реальным `ConfigService`).
5. [ ] Тесты `tests/routers/test_stellar.py`: `/decode <eurmtl-ссылка>` использует флаг из `feature_flags` и зовёт `check_url_xdr(full_data=...)`; `/decode` без аргумента отвечает подсказкой и не падает; при исключении в сервисе в ответе есть причина; `/decode` реплаем на сообщение со ссылкой работает.
6. [ ] Тесты `tests/routers/test_talk_handlers.py`: «Скайнет декодируй» реплаем на сообщение с eurmtl-ссылкой → декод; без ссылки → «Ссылка не найдена»; при исключении сервиса — причина в ответе.
7. [x] Проверка: `uv run pytest -q tests/routers/test_stellar.py tests/routers/test_talk_handlers.py`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` (по затронутым файлам).

## Риски и открытые вопросы
- `get_eurmtl_xdr` сейчас возвращает строку `"An error occurred during the request."` вместо исключения — если начнём поднимать исключение, `decode_xdr` перестанет пытаться парсить мусор (сейчас это `BadRequestError`/`ValueError` из stellar-sdk). Нужно проверить всех вызывающих: `other/stellar/xdr_utils.py:69` (единственный прямой вызов через `check_url_xdr`).
- Показ `str(e)` в чат может светить внутренние детали (URL/ответ тулзы) — допустимо в рабочих чатах, но спрячем за коротким префиксом «Не смог декодировать: …»; при желании ограничим до класса ошибки.
- «Ссылка не найдена» на реплай: возможно, url не извлекался из `entities` (ссылка в тексте реплая могла быть частью строки или `text_link`). Логи п.2 это покажут — если подтвердится, добавим fallback на `extract_url` по всему тексту реплая.
- Комментарии под постом — это не форум-топик (`is_topic_message=False`): `message.reply()` работает корректно, но любые `answer()`/`send_message` без `message_thread_id` уедут в «Общий». В рамках этой задачи не трогаем, только логируем `is_topic_message`/thread id для диагностики.

## Верификация
- Прод: задеплоить ветку, повторить в комментариях под постом: `/decode <ссылка eurmtl>`, `/decode` без аргумента, `Скайнет декодируй` реплаем на сообщение со ссылкой.
- В логах ожидаем: `DEBUG routers.stellar:cmd_decode` с chat_id/thread_id/text/`full_data=True|False`, а при сбое — `ERROR ... | <traceback>` с реальной причиной.
- Локально: `uv run pytest -q` зелёный, `uv run ruff check .`, `uv run ruff format --check .`.

## Результат (2026-10-19)
- Причина найдена и закрыта: `full_data` берётся из `app_context.feature_flags.is_full_data`, `parts[1]` больше не роняет `/decode`.
- Дополнительно к плану: `extract_message_url` (`other/aiogram_tools.py`) умеет искать ссылку в caption, `text_link`-энтити, без схемы и в inline-кнопке реплая; `extract_url` (`other/text_tools.py`) снимает хвостовую пунктуацию — это и есть правка «старой беды» со «Ссылка не найдена».
- `get_eurmtl_xdr` поднимает `EurmtlXdrError` с человеческой причиной и поддерживает старый формат `sign_tools?xdr=...`.
- Тесты: 930 passed; `ruff check`/`ruff format --check`/`pyright` чисто. Затронуто 9 файлов + 2 новых тест-файла.
