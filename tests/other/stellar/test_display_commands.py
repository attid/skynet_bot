import pytest

from other.constants import MTLChats
from other.stellar import display_commands


@pytest.mark.asyncio
async def test_get_cash_balance_clamps_negative_cash(monkeypatch):
    overpaid_account = "G" + "A" * 55
    positive_account = "G" + "B" * 55

    async def fake_load_table_data(table, sort=None):
        return [
            {"account_id": overpaid_account, "enabled": True, "name": "Overpaid"},
            {"account_id": positive_account, "enabled": True, "name": "Positive"},
        ]

    async def fake_get_balances(account_id):
        return {
            overpaid_account: {"EURDEBT": 50, "EURMTL": 80},
            positive_account: {"EURDEBT": 100, "EURMTL": 40},
        }[account_id]

    monkeypatch.setattr(display_commands.grist_manager, "load_table_data", fake_load_table_data)
    monkeypatch.setattr(display_commands, "get_balances", fake_get_balances)

    result = await display_commands.get_cash_balance(MTLChats.GuarantorGroup)

    assert "|Overpaid|      0 |     80 |" in result
    assert "|Positive|     60 |     40 |" in result
    assert "|Итого   |     60 |    120 |" in result
    assert "-30" not in result
