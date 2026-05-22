# stellar-refactor-facade: Избавление роутеров от прямых импортов other.stellar

## Контекст
- В соответствии с Clean Architecture и правилами проекта (`AGENTS.md`, `AI_FIRST.md`), слой доставки (`routers/`) должен взаимодействовать со внешними сервисами и интеграциями исключительно через слой приложения (`services/`).
- В текущей реализации роутеры напрямую импортируют и используют функции и константы из `other.stellar` (который является инфраструктурным адаптером). Это нарушает направление зависимостей: `interface (routers) -> application (services) -> domain`.
- Задача: Убрать прямые импорты из `other.stellar` во всех роутерах, переведя их на использование `StellarService` в качестве фасада и вынеся доменные константы `MTLAddresses` в слой домена `shared/domain/stellar_addresses.py`.

## План изменений

### 1. Домен и Инфраструктурные константы
- [x] Создать новый доменный файл [stellar_addresses.py](file:///home/itolstov/Projects/mtl/skynet_bot/shared/domain/stellar_addresses.py). Перенести туда класс `MTLAddresses` со строковыми адресами из [constants.py](file:///home/itolstov/Projects/mtl/skynet_bot/other/stellar/constants.py).
- [x] В [constants.py](file:///home/itolstov/Projects/mtl/skynet_bot/other/stellar/constants.py) импортировать `MTLAddresses` из `shared.domain.stellar_addresses`.
- [x] Экспортировать `MTLAddresses` из [shared/domain/stellar_addresses.py](file:///home/itolstov/Projects/mtl/skynet_bot/shared/domain/stellar_addresses.py).

### 2. Расширение фасада StellarService
- [x] В [services/external_services.py](file:///home/itolstov/Projects/mtl/skynet_bot/services/external_services.py) добавить в класс `StellarService` методы/свойства:
  - Свойство `addresses`, возвращающее `MTLAddresses`.
  - Свойство `assets`, возвращающее `MTLAssets`.
  - Метод `send_by_list(self, bot, all_users, message, url=None, session=None)` (вызывает `send_by_list` из `other.stellar.utils`).

### 3. Перенос вызова резервного копирования ассетов в ReportService
- [x] В [services/external_services.py](file:///home/itolstov/Projects/mtl/skynet_bot/services/external_services.py) в метод `ReportService.update_main_report` перенести импорт и вызов `save_assets(...)` перед вызовом основного отчета, убирая эту логику из роутера.

### 4. Рефакторинг роутеров
- [x] **[routers/admin_system.py](file:///home/itolstov/Projects/mtl/skynet_bot/routers/admin_system.py)**:
  - Убрать `from other.stellar import send_by_list`.
  - Заменить вызов `send_by_list(...)` на `ctx.stellar_service.send_by_list(...)`.
- [x] **[routers/airdrops.py](file:///home/itolstov/Projects/mtl/skynet_bot/routers/airdrops.py)**:
  - Убрать `from other.stellar import get_balances, send_payment_async`.
  - В `build_trustline_checks` сделать аргумент `stellar_service` обязательным (или получать его из `app_context`). Убрать fallback на прямой вызов `get_balances`.
  - В `check_source_balance` убрать fallback на прямой вызов `get_balances`.
  - В `execute_airdrop_payout` сделать `app_context` обязательным, вызывать `stellar_service.send_payment_async`.
- [x] **[routers/polls.py](file:///home/itolstov/Projects/mtl/skynet_bot/routers/polls.py)**:
  - Заменить импорт `from other.stellar import MTLAddresses` на `from shared.domain.stellar_addresses import MTLAddresses`.
- [x] **[routers/start_router.py](file:///home/itolstov/Projects/mtl/skynet_bot/routers/start_router.py)**:
  - Заменить импорт `from other.stellar import MTLAddresses` на `from shared.domain.stellar_addresses import MTLAddresses`.
- [x] **[routers/stellar.py](file:///home/itolstov/Projects/mtl/skynet_bot/routers/stellar.py)**:
  - Убрать `from other.stellar import MTLAddresses, MTLAssets`.
  - Заменить использование `MTLAddresses` на `ctx.stellar_service.addresses`.
  - Заменить использование `MTLAssets` на `ctx.stellar_service.assets`.
- [x] **[routers/talk_handlers.py](file:///home/itolstov/Projects/mtl/skynet_bot/routers/talk_handlers.py)**:
  - Убрать импорты `scripts.mtl_backup` и `other.stellar`.
  - Вызывать просто `await report_service.update_main_report(session)`.
- [x] **[routers/time_handlers.py](file:///home/itolstov/Projects/mtl/skynet_bot/routers/time_handlers.py)**:
  - Убрать импорт функций и констант из `other.stellar`.
  - Импортировать `app_context` из `services.app_context`.
  - Заменить все вызовы `cmd_*`, `get_balances` и использование `MTLAddresses` на вызовы через `app_context.stellar_service`.

### 5. Обновить/добавить тесты
- [x] Запустить тесты и убедиться, что они проходят после изменений в импортах. При необходимости обновить фикстуры и моки в тестах.

### 6. Проверка
- [x] `just lint` проходит.
- [x] `uv run ruff format --check <changed files>` проходит.
- [x] `uv run pyright <changed files>` проходит.
- [x] `uv run pytest <focused suites>` проходит успешно.
- [ ] `just types` по всему репозиторию падает на существующих ошибках вне этого среза: `routers/inline.py`, `services/skyuser.py`.

## Риски и открытые вопросы
- *Риск:* Использование `app_context` в фоновых задачах планировщика `time_handlers.py` может наткнуться на неинициализированный контекст, если планировщик стартует раньше полной инициализации.
  *Решение:* Инициализация планировщика происходит в `register_handlers` во время загрузки роутеров, когда `dp` и `app_context` уже полностью созданы in `start.py`. Будем использовать глобальный синглтон `services.app_context.app_context`, который перезаписывается в `start.py`.

## Верификация
- `just test`: 781 passed.
- `just lint`: passed.
- `uv run ruff format --check <changed files>`: passed.
- `uv run pyright <changed files>`: passed.
- `just types`: blocked by pre-existing unrelated errors in `routers/inline.py` and `services/skyuser.py`.
