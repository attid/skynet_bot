# selfmod-voting: Self-moderation via community votes

## Контекст

Цель — управление чатом без активных модераторов через голосования участников.

- **Приём в чат:** при вступлении нового участника появляются кнопки Accept/Reject. Любой участник чата может проголосовать. Approve — `yes ≥ max(3, 3 × no)`. Reject — `no ≥ max(3, 3 × yes)`.
- **Мьют:** реакция 👾 на любое сообщение запускает голосование за мьют автора. Та же формула. Эскалация: 1-й мьют — 1 день, 2-й — 1 неделя, 3-й запускает голосование за бан. История мьютов сбрасывается через 90 дней (rolling).
- **Логирование:** все события (старт/исход голосования, ручной reset) — в `MTLChats.SpamGroup` (`-1002007280572`). В Grist не пишем.
- **Включение:** новый feature-flag `selfmod` per-chat через `/admin`. Когда включён — заменяет captcha (CAS/LOLS-чек остаётся). Голосования без таймаута.

## План изменений

1. [x] `other/constants.py` — добавить `BotValueTypes.Selfmod`, `SelfmodActiveVotes`, `SelfmodWarnings`.
2. [x] `services/feature_flags.py` — `ChatFeatures.selfmod` + `FEATURE_TO_ENUM["selfmod"]`.
3. [x] `services/selfmod_service.py` (новый) — `SelfmodService`: `VoteState`, `threshold_passed()`, `start_vote`, `cast`, `add_warning/get_warnings/reset_warnings` (90-дневное окно), persistence через `DatabaseService`.
4. [x] `services/app_context.py` — регистрация `selfmod_service`.
5. [x] `routers/selfmod.py` (новый) — `SelfmodVoteCallback`, callback-handler, `message_reaction` на 👾, log-helper в SpamGroup, `begin_join_vote`/`begin_mute_vote` для других роутеров.
6. [x] `routers/welcome.py` — ветка при `selfmod=on`: skip captcha → `begin_join_vote` (restrict + post vote msg + log).
7. [x] `routers/admin_panel.py` — `FEATURE_LABELS["selfmod"]` + sub-page «Selfmod stats» (список warnings, кнопка reset).
8. [x] `tests/fakes.py` — `FakeSelfmodService` + регистрация в `TestAppContext`. Расширен `FakeDatabaseService` (`save_bot_value`/`load_bot_value`).
9. [x] `tests/services/test_selfmod_service.py` (новый) — 32 unit-теста: threshold table, warnings window, persistence round-trip.
10. [x] `tests/routers/test_selfmod.py` (новый) — 12 integration-тестов через `mock_telegram` + `dp.feed_update` + direct reaction handler.
11. [x] `tests/routers/test_welcome.py` — тест `test_new_chat_member_with_selfmod_skips_captcha`.
12. [x] `tests/routers/test_admin_panel.py` — тесты toggle/stats/reset + обновлены счётчики в `TestFeatureFlagsKb` (после добавления флага).
13. [x] `docs/glossary.md` — термины Selfmod, Join vote, Mute vote, Warning window.
14. [x] `just check` — ruff format, ruff check, pyright (0 errors), pytest (755 passed).

## Риски и открытые вопросы

- **Коллизия 👾**: `routers/polls.py:371` ставит 👾 от лица бота. Защита — фильтр `event.user.id != bot.id`.
- **Race conditions**: in-memory cache голосований + БД. Используем lock в `SelfmodService` и атомарный re-save после каждого vote.
- **`message_reaction` allowed_updates**: уже включён через `dp.resolve_used_update_types()` (start.py:264) — наличие `@router.message_reaction` хендлера достаточно.
- **Permissions при lift restrict**: при approve голосования за приём нужно вернуть полные ChatPermissions; формат должен совпадать с дефолтом чата (иначе лимиты ниже исходных).
- **Warnings — per-chat** (не глобально): один и тот же юзер в разных чатах получает мьюты независимо.

## Верификация

### Автоматические тесты (все через mock-сервера)

- `tests/services/test_selfmod_service.py`:
  - `threshold_passed` — табличные параметры: `(3,0)→approve`, `(2,0)→None`, `(3,1)→None`, `(6,2)→approve`, `(0,3)→reject`, `(1,3)→None`, `(3,1)→None` (нужно 6).
  - Warnings window: timestamps на 89 / 91 день старше `now` → 89 учитывается, 91 отброшен.
  - Persistence round-trip: запись → новый инстанс → загрузка состояния голосований и warnings.
- `tests/routers/test_selfmod.py`:
  - Approve join → `restrictChatMember` (lift) + `deleteMessage` voting-msg + `sendMessage` в SpamGroup `join_vote_approved`.
  - Reject join → `banChatMember`, лог `join_vote_rejected`.
  - Scaled threshold: 2 no + 5 yes → не закрыто; +1 yes → approve.
  - Double-vote блок: alert.
  - Self-vote блок: target не может голосовать.
  - 👾 от пользователя → mute-vote стартует; 👾 от бота → ничего.
  - Эскалация: warnings 0/1/2 → 1d/7d/kick-vote.
  - Kick-vote approve → ban.
- `tests/routers/test_welcome.py`:
  - При `selfmod=on` — нет captcha-сообщения; есть `restrictChatMember` + voting-msg.
- `tests/routers/test_admin_panel.py`:
  - Toggle `selfmod` через `AdminCallback(action="toggle", param="selfmod")`.
  - Sub-page отображает warnings.
  - Reset через `action="selfmod_reset"` → warnings очищены, лог в SpamGroup.

### Команды

```bash
just check
# или гранулярно:
uv run ruff format && uv run ruff check . && uv run pyright && uv run pytest -xvs
uv run pytest tests/services/test_selfmod_service.py tests/routers/test_selfmod.py -xvs
```

### Ручная проверка (на dev-чате после merge)

1. `/admin` → toggle `Self-Moderation` → captcha отключилась.
2. Зайти под тестовым юзером → 3 «Accept» → restrict снят, лог в SpamGroup.
3. Реакция 👾 на сообщение тестового юзера → 3 «Accept» → mute 1 день.
4. Повторить → mute 7 дней.
5. Третий раз → запуск kick-vote → 3 «Accept» → ban.
6. `/admin` → Selfmod stats → Reset @user → счётчик 0, лог.
7. Перезапуск бота посреди голосования → voting-msg продолжает работать.
