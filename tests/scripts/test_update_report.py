from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.fakes import FakeAsyncMethod, FakeGSpreadSpreadsheet, FakeGSpreadWorksheet, FakeSession
import scripts.update_report as update_report


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 16, 12, 30, 0)


def test_top_holders_update_data_ends_with_four_empty_rows():
    account = SimpleNamespace(
        account_id="GACCOUNT",
        balance_mtl=1,
        balance_rect=2,
        balance_delegated=3,
        balance=4,
        votes=5,
        calculated_votes=6,
    )

    update_data = update_report.build_top_holders_update_data([account])

    assert update_data == [
        ["GACCOUNT", 1, 2, 3, 4, 5, 6],
        ["", "", "", "", "", "", ""],
        ["", "", "", "", "", "", ""],
        ["", "", "", "", "", "", ""],
        ["", "", "", "", "", "", ""],
    ]


def make_async_session_pool(session):
    class Pool:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    return Pool()


@pytest.mark.asyncio
async def test_lite_report_uses_async_session_pool(monkeypatch):
    session = FakeSession()
    pool = make_async_session_pool(session)

    save_assets = FakeAsyncMethod()
    update_main = FakeAsyncMethod()
    update_top = FakeAsyncMethod()
    update_mmwb = FakeAsyncMethod()
    sleep = FakeAsyncMethod()

    monkeypatch.setattr(update_report, "save_assets", save_assets)
    monkeypatch.setattr(update_report, "update_main_report", update_main)
    monkeypatch.setattr(update_report, "update_top_holders_report", update_top)
    monkeypatch.setattr(update_report, "update_mmwb_report", update_mmwb)
    monkeypatch.setattr(update_report.asyncio, "sleep", sleep)

    await update_report.lite_report(pool)

    update_main.assert_awaited_once_with(session)
    update_top.assert_awaited_once_with(session)
    update_mmwb.assert_awaited_once_with(session)
    assert sleep.call_count == 3
    assert session.committed is True


def patch_additional_report_deps(monkeypatch, all_sheet, monitoring):
    spreadsheet = FakeGSpreadSpreadsheet({"IND_ALL": all_sheet, "MONITORING": monitoring})

    class FakeAgc:
        async def open_by_key(self, key):
            return spreadsheet

    class FakeAgcm:
        async def authorize(self):
            return FakeAgc()

    monkeypatch.setattr(update_report, "agcm", FakeAgcm())
    monkeypatch.setattr(update_report, "datetime", FrozenDatetime)
    monkeypatch.setattr(
        update_report,
        "calculate_statistics",
        lambda: {
            "USDM": 1,
            "SATSMTL": 2,
            "EURMTL": 3,
            "MTL_MTLRECT": 4,
            "Median": 5,
            "MTLAP": 6,
            "EURMTL_NONE_ZERO": 7,
        },
    )


@pytest.mark.asyncio
async def test_update_main_report_additional_resizes_full_monitoring_sheet(monkeypatch):
    monitoring_data = [[f"{index}.01.2026"] for index in range(1, 969)]
    all_sheet = FakeGSpreadWorksheet(data=[["", "", "", "Value"], ["", "", "", 1], ["", "", "", 2]])
    monitoring = FakeGSpreadWorksheet(data=monitoring_data, row_count=968)
    patch_additional_report_deps(monkeypatch, all_sheet, monitoring)

    await update_report.update_main_report_additional(FakeSession())

    assert monitoring.added_rows == [100]
    assert monitoring.row_count == 1068
    range_name, values, kwargs = monitoring._updated_ranges[-1]
    assert range_name == "A969"
    assert values[0] == ["16.10.2026", 1, 2]
    assert kwargs["value_input_option"] == "USER_ENTERED"
    assert all_sheet._updated_ranges


@pytest.mark.asyncio
async def test_update_main_report_additional_handles_large_deficit_covering_target_row(monkeypatch):
    monitoring_data = [[f"{index}.01.2026"] for index in range(1, 151)]
    all_sheet = FakeGSpreadWorksheet(data=[["", "", "", "Value"], ["", "", "", 1]])
    monitoring = FakeGSpreadWorksheet(data=monitoring_data, row_count=151)
    monitoring.row_count = 1  # defensive branch: grid metadata lags behind stored data
    patch_additional_report_deps(monkeypatch, all_sheet, monitoring)

    await update_report.update_main_report_additional(FakeSession())

    assert monitoring.added_rows == [150]
    assert monitoring.row_count == 151
    range_name, values, _ = monitoring._updated_ranges[-1]
    assert range_name == "A151"
    assert values[0] == ["16.10.2026", 1]


@pytest.mark.parametrize(
    ("data_rows", "row_count", "expected_range"),
    [
        (2, 3, "A3"),  # the next write fills the last grid row
        (2, 102, "A3"),  # retry after a previous expansion already added rows
        (1, 1000, "A2"),  # plenty of room left
        (0, 1000, "A1"),  # empty sheet
    ],
)
@pytest.mark.asyncio
async def test_update_main_report_additional_does_not_resize_when_grid_has_room(
    monkeypatch, data_rows, row_count, expected_range
):
    monitoring_data = [[f"{index}.01.2026"] for index in range(1, data_rows + 1)]
    all_sheet = FakeGSpreadWorksheet(data=[["", "", "", "Value"], ["", "", "", 1]])
    monitoring = FakeGSpreadWorksheet(data=monitoring_data, row_count=row_count)
    patch_additional_report_deps(monkeypatch, all_sheet, monitoring)

    await update_report.update_main_report_additional(FakeSession())

    assert monitoring.added_rows == []
    range_name, values, kwargs = monitoring._updated_ranges[-1]
    assert range_name == expected_range
    assert values[0] == ["16.10.2026", 1]
    assert kwargs["value_input_option"] == "USER_ENTERED"


@pytest.mark.asyncio
async def test_update_main_report_additional_rejects_wrong_ind_all_structure(monkeypatch):
    all_sheet = FakeGSpreadWorksheet(data=[["", "", "", "NotValue"]])
    monitoring = FakeGSpreadWorksheet(data=[["01.01.2026"]], row_count=1000)
    patch_additional_report_deps(monkeypatch, all_sheet, monitoring)

    with pytest.raises(ValueError, match="Value"):
        await update_report.update_main_report_additional(FakeSession())

    assert monitoring.added_rows == []
