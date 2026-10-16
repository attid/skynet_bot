# 2026-10-16: Fix MONITORING sheet growth in update_main_report_additional

## Контекст
- С 13.10.2026 ежедневный `lite_report` падал в `update_main_report_additional`:
  `gspread.exceptions.APIError: 400 Range (MONITORING!A969) exceeds grid limits. Max rows: 968, max columns: 41`.
- Причина: Sheets API `values.update` не расширяет сетку, а код писал в
  `A{len(col_values(1))+1}` без `add_rows`. Падение прерывало `lite_report` до
  `update_top_holders_report`, поэтому не уходило уведомление «You need update votes».
- Согласованный объём: минимальный фикс только в `update_main_report_additional` + тесты.
  Остальные найденные точки — отдельная будущая задача (см. ниже), в этом изменении не тронуты.

## План изменений
1. [x] `scripts/update_report.py` — в `update_main_report_additional` перед `update`
   проверяется `wks_monitoring.row_count`, при нехватке вызывается `add_rows` с запасом
   (`MONITORING_GRID_EXPANSION_ROWS = 100`, не меньше дефицита) и пишется `logger.info`.
2. [x] `tests/fakes.py` — `FakeGSpreadWorksheet` расширен: `acell`, `col_values`,
   `row_count`, `add_rows`, `update` с проверкой границ сетки (`APIError`), записью kwargs
   и поддержкой старого порядка аргументов gspread.
3. [x] `tests/scripts/test_update_report.py` — тесты: воспроизведение прод-инцидента
   (`row_count=968`, запись в `A969`), отсутствие resize при наличии места (включая retry
   после расширения и пустой лист), защитная ветка большого дефицита, неверная структура
   `IND_ALL`, детерминированное время через `FrozenDatetime`.
4. [x] `tests/test_gspread_fakes.py` — self-тесты фейка: границы `update`, legacy-порядок,
   `acell`/`col_values`/`add_rows`.
5. [x] Локальные проверки: `uv run ruff format --check .`, `just lint`, `just types`,
   `just test` — 907 passed, ruff/pyright чисто.
6. [x] Ревью через `agy-review` (read-only, 8 кругов), отчёт:
   `docs/drafts/agy_monitoring_sheet_growth_review.md`.
7. [x] Перенести план в `completed/` с отмеченными пунктами.

## Риски и открытые вопросы
- `add_rows` — дополнительный API-вызов только когда сетка заполнена; `row_count` читается
  из свежих метаданных worksheet, полученных в начале функции.
- Ширина `MONITORING` (41 колонка) остаётся незащищённой: если в `IND_ALL!D` появится
  больше значений, `update` упрётся в лимит колонок — вынесено в будущую задачу.
- Ветка `last_row - row_count > 100` для живого листа недостижима (`len(col_values) <= row_count`,
  дефицит всегда ровно 1 строка); `max(...)` оставлен как дешёвая защита и покрыт тестом.

## Верификация
- Тест `test_update_main_report_additional_resizes_full_monitoring_sheet` воспроизводит
  конфигурацию инцидента: 968 строк данных при `row_count=968` → `add_rows(100)` → запись
  в `A969` с `value_input_option="USER_ENTERED"`.
- `test_update_main_report_additional_does_not_resize_when_grid_has_room` подтверждает
  идемпотентность (в т.ч. повторный запуск при `row_count=102`).
- `just lint`, `just types`, `just test` — зелёные.
- Ретроспектива 8 кругов ревью:
  `docs/drafts/agy_review_retrospective_monitoring_sheet_growth.md`.

## Будущие задачи (вне scope этого фикса)
Одинаковый паттерн «вычисленная последняя строка + `update` без расширения сетки» либо
риск перерастания листа. Эти места намеренно не менялись:
- `other/gspread_tools.py` `gs_save_new_task` (`MTL_TASKS_register` / `Term`);
- `other/gspread_tools.py` `gs_save_new_support` (`MTL_support_register` / `ALL`);
- `other/gspread_tools.py` `_gs_update_a_table_vote_internal` (голосовательные таблицы / `Log`);
- `scripts/update_report.py` `update_export` (`test export 4` / `2023`, сейчас выключен в шедулере);
- `scripts/update_report.py` `update_airdrop` (`MTL_Airdrop_register` / `EUR_GNRL`, ручной
  `/update_airdrops`);
- `other/gspread_tools.py` `gs_copy_sheets_with_style` — копирует ячейки через `updateCells`
  по индексам источника и не ресайзит целевой лист; при росте исходного `report` упадёт
  целевой `B_TBL` (вероятный следующий инцидент в том же ежедневном пайплайне);
- ширина `MONITORING`: строка собирается из `IND_ALL!D`, при новых значениях в этой колонке
  запись упрётся в лимит 41 колонки.
