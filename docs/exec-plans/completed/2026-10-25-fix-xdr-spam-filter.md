# 2026-10-25-fix-xdr-spam-filter: фильтр SPAM в decode_xdr не работает

## Контекст
- В чат аккаунт-подписки (`GDCU..YGLW`) пришло уведомление по транзакции
  `b49e3b970118d03f63c65b9f7acc382ef4888d170eaa9b0fe54461970bf2ba9f` (memo `BFAB faucet`,
  26 операций: 13 `Payment` по `1E-7 XLM` + 13 `CreateClaimableBalance`) — это спам/пыль.
- Причина: фильтр `SPAM` в `other/stellar/xdr_utils.py` сравнивает суммы строками:
  `operation.amount < "0.1"`. stellar-sdk отдаёт `amount` строкой в научной нотации,
  поэтому `"1E-7" < "0.1"` → `False` и пыль проходит.
- Дополнительно заголовок `Операция N - <Тип>` печатается до применения `ignore_operation`,
  поэтому игнорируемые операции остаются в сообщении пустыми заголовками.

## План изменений
1. [x] `other/stellar/xdr_utils.py`
   - числовое сравнение сумм через `Decimal` (константа `SPAM_MAX_XLM_PAYMENT = 0.1`,
     helper `is_spam_payment(operation)`);
   - проверки `ignore_operation` и SPAM-пыли переносим до добавления заголовка
     `Операция N - <Тип>`, чтобы игнорируемые операции вообще не попадали в вывод;
   - убрать дублирующую строковую проверку в блоке `Payment`.
2. [x] `tests/other/stellar/test_xdr_utils.py` — регрессии:
   - пылевой платёж (`0.0000001 XLM`, в XDR приходит как `1E-7`) с `ignore_operation=["SPAM"]` → `[]`;
   - смешанная tx (пыль + `CreateClaimableBalance`) → `[]`;
   - игнорируемый тип операции не даёт пустых заголовков;
   - платёж `0.1 XLM` и выше по-прежнему показывается.
3. [x] Проверка: `just lint`, `just types`, `just test`, `uv run ruff format --check .`.

## Риски и открытые вопросы
- Порог 0.1 XLM остаётся хардкодом (категорий в Grist нет — отдельный этап).
- Реальные пылевые платежи (например, от бирж) тоже перестанут отображаться при `SPAM` в фильтрах;
  это ровно то поведение, которое задумывал фильтр.
- Счётчик `Всего N операций` не меняем: при полном отсеве операций `decode_xdr` вернёт `[]`
  и уведомление не отправится.

## Результат
- `other/stellar/xdr_utils.py`: `SPAM_MAX_XLM_PAYMENT = Decimal("0.1")` + `is_spam_payment()`
  (числовое сравнение, работает с `1E-7`); фильтры `ignore_operation`/`SPAM` применяются
  до заголовка `Операция N - <Тип>`; дублирующая строковая проверка удалена.
- `tests/other/stellar/test_xdr_utils.py`: +4 теста (пыль в научной нотации, faucet-tx целиком,
  отсутствие пустых заголовков для игнорируемых типов, порог 0.1 XLM не тронут).
- Проверки: `ruff check .`, `ruff format --check .`, `pyright` (проектный конфиг) — 0 ошибок,
  `pytest` — 974 passed.
- Реальный tx `b49e3b97…` (`BFAB faucet`): `decode_xdr(..., ["CreateClaimableBalance","SPAM","MASS"],
  filter_account=GDCU…)` → `[]`, т.е. уведомление больше не отправится.

## Верификация
- Регрессионный тест на реальный tx: `decode_xdr(xdr, ignore_operation=["CreateClaimableBalance","SPAM","MASS"], filter_account=GDCU…)` → `[]`.
- До фикса тот же прогон даёт 13 `Payment` по `1E-7 XLM`.
