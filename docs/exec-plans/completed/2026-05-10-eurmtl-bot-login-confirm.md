# 2026-05-10: EURMTL bot login confirm

## Контекст
- Сайт `eurmtl.me` добавляет fallback-login через внешний `myMTLBot`.
- Сайт создает одноразовый token и deep-link `https://t.me/myMTLBot?start=eurmtl_<token>`.
- Бот должен подтвердить Telegram-пользователя на сайте server-to-server запросом с `EURMTL_KEY`.
- Старый `/start eurmtl` и `/eurmtl` пока не удаляем: это отдельная последующая задача.

## План изменений
1. [x] Добавить тесты в `tests/routers/test_admin_system.py`:
   - успешный `/start eurmtl_<token>` отправляет confirm payload и пишет пользователю об успехе;
   - ошибка/expired от сайта пишет пользователю, что ссылка устарела;
   - отсутствие `from_user` не делает confirm и пишет ошибку;
   - старый `/start eurmtl` продолжает работать как раньше до отдельного удаления.
2. [x] Добавить сервис `services/eurmtl_bot_login_service.py`:
   - собрать JSON payload из `aiogram.types.User`;
   - отправить `POST /login/bot/confirm` через `aiohttp`;
   - использовать `Authorization: Bearer <EURMTL_KEY>`;
   - вернуть простой success/error результат без исключений наружу.
3. [x] Обновить `routers/admin_system.py`:
   - добавить обработчик `CommandStart(deep_link=True, magic=F.args.regexp(r"^eurmtl_.+"))` только для private-чата;
   - отрезать prefix `eurmtl_`;
   - вызвать сервис confirm;
   - ответить `Вход подтвержден, вернитесь на сайт.` при успехе;
   - ответить `Ссылка устарела, начните вход заново на сайте.` при ошибке.
4. [x] Проверить focused tests:
   - `uv run pytest tests/routers/test_admin_system.py -q`
5. [x] При необходимости проверить стиль:
   - `just lint`

## Риски и открытые вопросы
- Хендлер `/start eurmtl_<token>` должен зарегистрироваться раньше старого `/start eurmtl`, иначе старый exact-match не конфликтует, но порядок все равно стоит держать очевидным.
- `photo_url` в v1 всегда отправляем `None`, чтобы не класть Telegram file URL с bot token в публичный web-session.
- Сайт должен возвращать HTTP 2xx на успешный confirm; все остальное для бота считается ошибкой/expired.

## Верификация
- Для success mock endpoint получает `Authorization: Bearer test-eurmtl-key` и payload с `token`, `id`, `first_name`, `last_name`, `username`, `photo_url`, `auth_date`.
- Для ошибки mock endpoint возвращает non-2xx, бот отвечает текстом про устаревшую ссылку.
- Для отсутствующего `from_user` endpoint не вызывается.
