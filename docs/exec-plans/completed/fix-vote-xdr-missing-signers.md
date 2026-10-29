# fix-vote-xdr-missing-signers: не терять подписантов, которых нет на аккаунте

## Контекст
- `/get_vote_fund_xdr` отвечает «Изменений нет: все 11 аккаунтов уже в нужном состоянии»,
  хотя мультисп-аккаунт `GCI7RSQNA7EFXLSCN64AHHBZPRPM6CHEN7ANMD4RAIDUFLNWO4L7MTLD` — не полная
  копия фондового набора подписантов.
- Факты по Horizon (public):
  - issuer `GACKTN5DAZGWXRWB2WLM6OPBDHAMT6SJNGLJZPQMEZBUR4JUGBX2UK7V`: 14 подписантов,
    `thresholds = 54/54/54`, master weight 0;
  - `GCI7RSQ…MTLD`: те же `54/54/54`, master weight 0, но только 11 подписантов.
    Отсутствуют `GBEW6QTULYON3KOXR2NQMCB5RN2SWMKF5KTO26KICAOY6A64XRINDSTL` (6),
    `GC6CMCHNOVQGX4STELR7W2HN5H6EGY7LG2ED27DJAFYVFR3PTCG47CWP` (2),
    `GDSQXAXL73522TU4AUQJ2JLW4BJKLAKLPTIKXWSSFDGTHUK5Y5WCMIDV` (2).
- Причина — в `plan_account_vote_ops` (`other/stellar/voting_utils.py`): `arr.votes`
  перезаписывается фактическим весом аккаунта **только для тех подписантов, которые на аккаунте
  уже есть**. Для отсутствующего подписанта `votes` остаётся эталонным значением из
  `cmd_gen_mtl_vote_list` (вес с аккаунта issuer), поэтому `calculated_votes == votes` и diff
  не срабатывает — подписант никогда не добавляется. Итог: сумма порогов и так даёт 54,
  master уже 0, а отсутствующие 3 подписанта «невидимы» → план `None`.
- Диагностика на реальных данных (локально, Horizon public): если считать `votes` как
  фактический вес аккаунта (0 для отсутствующих), план для `GCI7RSQ…MTLD` даёт ровно три
  добавления с весами 6/2/2 и не меняет пороги (54).

## План изменений
1. [x] `other/stellar/voting_utils.py` — `plan_account_vote_ops`: перед разбором списка
   проставлять `votes` из `current_weights` **для всех** элементов `vote_list`
   (`current_weights.get(account_id, 0)`), а не только для найденных на аккаунте; затем, как и
   раньше, добавлять в `vote_list` подписантов аккаунта, которых в списке нет (они попадут в
   удаление через `calculated_votes == 0 & votes > 0`).
2. [x] `tests/other/stellar/test_voting_utils.py` — regression-тест: подписант есть в эталонном
   `vote_list` с весом > 0, но отсутствует на аккаунте → в плане есть `(signer, вес)`;
   плюс кейс «полная копия уже на аккаунте» → `None` (пороги не меняются).
3. [x] Проверка: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run pyright`.

## Риски и открытые вопросы
- `votes` в `plan_account_vote_ops` теперь всегда означает «фактический вес на проверяемом
  аккаунте». `cmd_gen_mtl_vote_list` не меняется, поэтому `scripts/update_report.py`
  (использует эталонные веса issuer) не затронут.
- Аккаунты, у которых не хватало тех же подписантов, начнут попадать в XDR — это ожидаемое
  поведение «полной копии», но в первый прогон XDR может стать заметно больше.
- Лимит `max_count=20` и правило «не разрывать аккаунт между транзакциями» не меняются.

## Верификация
- Прод/локально: `/get_vote_fund_xdr` — вместо «Изменений нет» приходит XDR, где для
  `GCI7RSQ…MTLD` ровно три `SetOptions`/signer-операции (веса 6/2/2), пороги остаются 54/54/54.
- Выполнено: `uv run pytest -q` (976 passed), `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run pyright` (0 errors) — чисто.
- Живая проверка (Horizon public, локальный прогон): `plan_account_vote_ops` для
  `GCI7RSQ…MTLD` возвращает ровно три добавления (`GBEW6Q…DSTL` 6, `GC6CMC…47CWP` 2,
  `GDSQXA…MIDV` 2), `thresholds=None`, `master_weight=None` — пороги 54 остаются как есть.
