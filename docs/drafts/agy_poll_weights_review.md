## Ревью незакоммиченных изменений (авто-пересчёт весов и `/poll_recount`)

Были исследованы изменения в [`routers/polls.py`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py), [`tests/fakes.py`](file:///home/itolstov/Projects/mtl/skynet_bot/tests/fakes.py), [`tests/routers/test_polls.py`](file:///home/itolstov/Projects/mtl/skynet_bot/tests/routers/test_polls.py) и план задачи [`docs/exec-plans/completed/2026-11-04-poll-weights-autorefresh-and-recount.md`](file:///home/itolstov/Projects/mtl/skynet_bot/docs/exec-plans/completed/2026-11-04-poll-weights-autorefresh-and-recount.md). Кодовая база протестирована (`pytest`, `ruff`, `pyright` — все 1052 теста проходят успешно).

Ниже представлены результаты детального анализа.

---

### Находки по приоритетам

#### **P1 (критичные баги — чинить до коммита)**
*Блокирующих багов уровня P1 (приводящих к падению сервиса, потере данных или открывающим уязвимости безопасности) не обнаружено.*

---

#### **P2 (важные дефекты и риски — стоит поправить)**

1. [`routers/polls.py:698`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L698)
   - **Суть:** Перезапись веса пользователя при наличии нескольких ключей-подписантов в [`_recalculate_votes`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L675).
   - **Почему это проблема:** В цикле по `signers` общий вес аккумулируется корректно (`total += signer["weight"]`), однако присвоение в словарь выполняется прямой перезаписью:
     ```python
     key_ = _normalize_user_key(username)
     vote_list[address][key_] = signer["weight"]
     ```
     Если у одного пользователя в multisig-аккаунте привязано более одного ключа (например, холодный и мобильный кошелёк, либо смена ключа в Grist на одного `@username`), вес первого ключа затирается вторым. В результате:
     - реальный вес голоса пользователя занижается;
     - пороги кворума `NEED["50"]` и `NEED["75"]` рассчитываются из полного `total`, из-за чего опрос может стать математически не закрываемым даже при участии всех участников.
   - **Как чинить:** Аккумулировать веса по нормализованному ключу:
     ```python
     vote_list[address][key_] = vote_list[address].get(key_, 0) + signer["weight"]
     ```

2. [`routers/polls.py:183-186`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L183-L186)
   - **Суть:** Таймаут `asyncio.timeout(VOTE_RECALC_TIMEOUT)` (30 с) в [`_recount_vote_weights`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L176) включает время ожидания блокировки [`_recount_lock`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L71).
   - **Почему это проблема:** Если первый пересчёт (например, вызванный `/poll_reload_vote` или созданием другого опроса) длится 20–25 секунд из-за нагрузки на Horizon/Grist, создание второго опроса встает в очередь на `_get_recount_lock()`. Захватив лок через 25 секунд, у второй корутины остаётся всего 5 секунд до срабатывания 30-секундного таймаута. Она падает по `TimeoutError` и прерывает запрос.
     При этом:
     - первый пересчёт **уже** успешно обновил веса в `voting_service` и в базе миллисекунду назад;
     - опрос создаётся на этих актуальных весах;
     - однако бот ставит на опрос реакцию `⚠️` и отправляет в личку админу ложную тревогу о сбое пересчёта ("Пересчёт весов не удался...").
   - **Как чинить:** Ограничивать таймаутом только саму фазу сетевых вызовов внутри лока, либо внутри функции проверять: если пока задача ждала лок, другой процесс только что успешно закончил пересчёт — повторный пересчёт можно пропустить и вернуть текущий `voting_service.get_vote_weights(...)`.

3. [`routers/polls.py:341-343`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L341-L343)
   - **Суть:** В группах/супергруппах ответ командой `/poll_recount` на пересланное сообщение не из канала трактуется как локальный опрос.
   - **Почему это проблема:** В [`_resolve_poll_key`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L315):
     ```python
     if reply is not None:
         forward_origin = reply.forward_origin
         if isinstance(forward_origin, MessageOriginChannel):
             return forward_origin.chat.id, forward_origin.message_id
         if message.chat.type != "private":
             return message.chat.id, reply.message_id
     ```
     Если админ в рабочей группе отвечает на сообщение, пересланное от пользователя (`MessageOriginUser`) или из другой группы (`MessageOriginChat`), `isinstance(..., MessageOriginChannel)` возвращает `False`, и функция возвращает `(message.chat.id, reply.message_id)`.
     Идентификатор `reply.message_id` — это id пересланного сообщения в текущей группе, а не самого опроса. Хотя `load_poll` чаще всего вернёт "Опрос не найден", логика не должна трактовать пересланные сообщения с `reply.forward_origin is not None` как локальный опрос.
   - **Как чинить:** Ограничить ветку прямыми (непересланными) сообщениями группы:
     ```python
     if message.chat.type != "private" and reply.forward_origin is None:
         return message.chat.id, reply.message_id
     ```
     В таком случае админ сразу получит корректную подсказку ("Для опросов из групп/супергрупп пересылка не сохраняет исходный id — используйте ссылку").

---

#### **P3 (минорные замечания и вкусовщина)**

1. [`routers/polls.py:346-354`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L346-L354) vs [`routers/polls.py:235-270`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L235-L270)
   - **Суть:** Неконсистентный формат сообщения до первого голоса и после вызова `/poll_recount`.
   - **Контекст:** При создании опроса (`_publish_weighted_poll`) отправляется только вопрос и строка `Need ...` (без строк вариантов). Если сразу после создания вызвать `/poll_recount`, [`_render_poll_view`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L235) перерендерит сообщение со строками `Opt (0) : \n`. Это не ломает функционал, но приводит к визуальному изменению структуры сообщения при ручном пересчёте нулевого опроса.
   - **Как чинить:** Можно унифицировать и сразу публиковать опрос через `_render_poll_view`, либо оставить как есть (сохранение исторического формата).

2. [`routers/polls.py:135`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L135)
   - **Суть:** Эвристика поиска ненайденных адресов по условию `if isinstance(sub_key, str) and ".." in sub_key:`.
   - **Контекст:** Проверка предполагает, что две точки встречаются исключительно в сокращённых адресах Stellar вида `GABC..WXYZ`. Если в реестре Grist в описании счета (`EURMTL_accounts.description`) случайно встретится двоеточие или многоточие `..`, запись будет ложно определена как ненайденный адрес.
   - **Как чинить:** Сделать проверку строже: `".." in sub_key and "не найден" in sub_key`.

3. [`routers/polls.py:706`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L706)
   - **Суть:** Локальный импорт `from db.session import AsyncSessionPool` внутри [`_recalculate_votes`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L675).
   - **Контекст:** В верхней части файла уже импортируются модели БД и репозитории.
   - **Как чинить:** Перенести импорт на уровень модуля (если нет циклических зависимостей).

---

### Что упростить

1. **Извлечение ссылок в [`_link_candidates`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L292):**
   Сейчас функция сканирует `entities`, `caption_entities`, а затем делает `split()` по тексту и парсит токены со стрипом скобок и кавычек. Если в сообщении уже найдена валидная сущность типа `url` или `text_link`, токенный fallback-парсинг текста можно пропускать, снижая сложность функции.
2. **Дублирование `asyncio.timeout`:**
   Конструкция `async with asyncio.timeout(VOTE_RECALC_TIMEOUT):` продублирована в `_recount_vote_weights` и в `cmd_poll_reload_vote_handler`. Имеет смысл перенести таймаут непосредственно в [`cmd_save_votes`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L663).
3. **Глобальный трекинг loop в [`_get_recount_lock`](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py#L75):**
   Сложная логика `_recount_lock_loop is not loop` написана ради изоляции event loop в тестах `pytest`. В продакшене event loop всегда один. В тестах лок и так очищается фикстурой `cleanup_router`. Лок можно хранить как поле сервиса (например, в `voting_service`), избегая глобальных переменных на уровне модуля.

---

### Чего не хватает в тестах

1. **Тест на мульти-ключи одного пользователя:**
   Случай, когда `stellar_service.get_balances` возвращает двух signers с разными публичными ключами, но оба резолвятся в один и тот же username в Grist. Проверить суммирование их весов, а не затирание.
2. **Тест на конкурентный вызов пересчёта (Lock Contention):**
   Одновременный запуск двух корутин создания опроса через `asyncio.gather`, где первая удерживает лок (например, через `asyncio.sleep` в моке `get_balances`). Проверить, что вторая корутина не падает с ложной ошибкой `⚠️`.
3. **Тест на пересчёт голосов с числовым Telegram ID (пользователи без username):**
   В `cq_join_list` пользователь без username сохраняется как строковый ID (`str(query.from_user.id)`). Проверить, что `/poll_recount` корректно сопоставляет такие ID с реестром и не обнуляет их вес.
4. **Тест на ответ командой `/poll_recount` на пересланное сообщение пользователя в группе:**
   Проверить, что при ответе в супергруппе на сообщение с `forward_origin = MessageOriginUser` бот выдаёт сообщение с требованием ссылки, а не пытается пересчитать несуществующий опрос.
5. **Тест на `/poll_recount` свежесозданного пустого опроса:**
   Проверить, что пересчёт только что опубликованного опроса с 0 голосов не ломает клавиатуру и сохраняет корректный вид сообщения.

---

### Финальный вердикт
**Чинить и коммитить** (критичных P1 нет, но есть дефекты P2 с потенциальной потерей весов при мульти-ключах и ложными таймаутами при очереди к локу).
