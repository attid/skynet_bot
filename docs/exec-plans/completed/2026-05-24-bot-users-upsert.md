# 2026-05-24-bot-users-upsert: идемпотентная запись bot_users

## Контекст
- В проде `ChatMemberUpdated` может обрабатываться параллельно для одного пользователя.
- Текущий путь `SELECT bot_users -> session.add(BotUsers)` может проиграть гонку и упасть на `bot_users_pkey`.
- Ошибка проявляется при autoflush перед следующим запросом в `ChatsRepository.async_add_user_to_chat`.

## План изменений
1. [x] Добавить регрессионный тест для повторного добавления существующего `BotUsers` без сброса `user_type`.
2. [x] Заменить `SELECT -> add` для `BotUsers` в chat repository на идемпотентный upsert/helper.
3. [x] Обновить/добавить тесты.
4. [x] Обновить docs/ (если затронуты контракты/поведение).
5. [x] Проверка: targeted pytest, `just lint`, `just types`, `just test`.

## Риски и открытые вопросы
- SQLite в тестах не полностью воспроизводит PostgreSQL concurrency, поэтому тест должен покрыть намерение: не создавать duplicate ORM object и не сбрасывать `user_type`.
- Upsert не должен переводить уже помеченного пользователя обратно в `NEW`.

## Верификация
- Регрессионный тест падает на текущем коде и проходит после фикса.
- Полный набор тестов проходит.
- `uv run pytest tests/db/test_repositories.py tests/db/test_async_repository_methods.py -q`
- `uv run ruff format --check .`
- `just lint`
- `just types`
- `just test`
