# decode-reply-rich-sources: ссылка из rich-поста и ответ одним rich-сообщением

## Контекст
- Комментарии под постом канала: реплай на пост + `/decode` / `Скайнет декодируй` не находит ссылку.
- Прод-лог: `decode: ... reply_msg=10248 text='/decode' reply_text=''` — у `reply_to_message` нет `text`/`caption`.
- Причина: пост канала приходит как **rich message** (Bot API `Message.rich_message`, содержание в `blocks`), а не в `text`. Пользователь подтвердил: «там 100% Message.rich_message».
- Вторая просьба: длинный декод («моя транза») разваливается на 3 сообщения, потому что `multi_reply` режет по 4096. Rich-сообщение вмещает до 16384 символов.

## План изменений
1. [x] `other/aiogram_tools.py` — `rich_message_text` (обход блоков), `message_full_text`, `extract_message_url` (text/caption/entities/rich/buttons), `extract_reply_url` (реплай + серверный `Message.quote`), `describe_reply_dump` для диагностики.
2. [x] `other/aiogram_tools.py` — `multi_reply`: длинный текст уходит одним `reply_rich(InputRichMessage(html=...))` (лимит 16k, нарезка по переводу строки), при ошибке — фолбэк на прежнюю нарезку по 4000 с логом.
3. [x] `routers/stellar.py`, `routers/talk_handlers.py` — использовать `extract_reply_url`/`message_full_text`; при `source=none` писать в лог дамп реплая (`reply_keys`, `reply_dump`, `quote_text`); снят искусственный срез `msg[:4000]` в `_decode_url`.
4. [x] `tests/conftest.py` — мок-сервер отвечает на `sendRichMessage` (внешние границы только через мок-серверы).
5. [x] Тесты: `tests/other/test_text_tools.py` (rich-блоки, quote, кнопка), `tests/routers/test_stellar.py` и `tests/routers/test_talk_handlers.py` (реплай на rich-пост, один `sendRichMessage` на длинный ответ, фолбэк при отказе).
6. [x] Проверка: `uv run pytest -q` (937 passed), `ruff check`, `ruff format --check`, `uv run pyright` — чисто.

## Риски и открытые вопросы
- Rich HTML может поддерживать не все теги, которые мы шлём (`<a href>`, `<b>`, `<code>`) — поэтому любая ошибка отправки ловится и повторяется обычными сообщениями; в лог пишется `rich reply failed (len=...)` с трейсбеком.
- `reply_rich` подставляет `message_thread_id` только при `is_topic_message`; в тредах комментариев тред тащит `reply_parameters` (как и у обычного `reply`).
- `multi_reply` используется и другими хендлерами (отчёты и т.п.) — они тоже начнут получать длинные ответы одним rich-сообщением; при отказе API поведение прежнее.
- Если ссылка когда-нибудь окажется не в `text`/`rich_message`/`quote`/кнопке, в логе теперь будет полный дамп реплая — доводить диагностику не придётся гаданием.

## Результат
- Оба хендлера («/decode» и «Скайнет декодируй») используют один и тот же набор источников ссылки, поэтому поведение в комментариях под постом совпадает.
- Длинный декод уходит одним сообщением (до ~16k), лишние части не появляются.
