"""Tests for the FakeGSpreadWorksheet test double."""

import pytest
from gspread.exceptions import APIError

from tests.fakes import FakeGSpreadWorksheet


@pytest.mark.parametrize(
    ("range_name", "values", "row_count"),
    [
        ("A2", [["01.01.2026"]], 1),  # start beyond the grid
        ("A1", [[1], [2]], 1),  # values cross the grid boundary
        ("A1:A3", [[1]], 1),  # explicit range end beyond the grid
    ],
)
@pytest.mark.asyncio
async def test_fake_gspread_worksheet_rejects_update_outside_grid(range_name, values, row_count):
    monitoring = FakeGSpreadWorksheet(row_count=row_count)

    with pytest.raises(APIError):
        await monitoring.update(values=values, range_name=range_name)


@pytest.mark.asyncio
async def test_fake_gspread_worksheet_accepts_legacy_positional_order():
    monitoring = FakeGSpreadWorksheet(row_count=10)

    await monitoring.update("A2", [["01.01.2026"]])

    assert monitoring._updated_ranges[-1][0] == "A2"


@pytest.mark.asyncio
async def test_fake_gspread_worksheet_reads_cells_and_columns():
    worksheet = FakeGSpreadWorksheet(data=[["a", "", "c"], ["d", None, "f"]], row_count=5)

    assert (await worksheet.acell("A1")).value == "a"
    assert (await worksheet.acell("B1")).value == ""
    assert (await worksheet.acell("C2")).value == "f"
    assert (await worksheet.acell("invalid")).value is None
    assert (await worksheet.acell("A10")).value is None
    assert await worksheet.col_values(1) == ["a", "d"]
    assert await worksheet.col_values(2) == []
    assert await worksheet.col_values(3) == ["c", "f"]


@pytest.mark.asyncio
async def test_fake_gspread_worksheet_add_rows_grows_grid():
    worksheet = FakeGSpreadWorksheet(row_count=3)

    await worksheet.add_rows(100)

    assert worksheet.added_rows == [100]
    assert worksheet.row_count == 103
