# other/stellar/display_commands.py
"""Display and show commands for Stellar data presentation."""

from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from other.config_reader import config
from other.constants import MTLChats
from other.utils import float2str
from other.grist_tools import MTLGrist, grist_manager
from other.gspread_tools import agcm
from db.repositories import FinanceRepository
from other.web_tools import http_session_manager
from .constants import MTLAddresses
from .balance_utils import get_balances, stellar_get_account, stellar_get_all_mtl_holders
from .xdr_utils import decode_data_value


def isfloat(value) -> bool:
    """Check if value can be converted to float."""
    try:
        float(value)
        return True
    except ValueError:
        return False


async def get_bim_list() -> list:
    """
    Get list of BIM participants from Google Sheet.

    Returns:
        List of [address, has_eurmtl] pairs
    """
    agc = await agcm.authorize()
    ss = await agc.open("MTL_BIM_register")
    wks = await ss.worksheet("List")

    addresses = []
    data = await wks.get_all_values()
    for record in data[2:]:
        if record[20] and len(record[4]) == 56 and record[10] == "TRUE" and float(float2str(record[17])) > 0.5:
            addresses.append(record[4])

    # check eurmtl
    result = []
    for address in addresses:
        # get balance
        balances = {}
        response = await http_session_manager.get_web_request(
            "GET", url=f"{config.horizon_url}/accounts/{address}", return_type="json"
        )
        rq = response.data if isinstance(response.data, dict) else {}
        if rq.get("balances"):
            for balance in rq["balances"]:
                if balance["asset_type"] == "credit_alphanum12":
                    balances[balance["asset_code"]] = balance["balance"]
            has_eurmtl = "EURMTL" in balances
            result.append([address, has_eurmtl])
    return result


async def cmd_show_bim(session: AsyncSession) -> str:
    """
    Show BIM participant statistics.

    Args:
        session: Database session

    Returns:
        Formatted string with BIM statistics
    """
    result = ""
    bod_list = await get_bim_list()
    good = list(filter(lambda x: x[1], bod_list))

    total_sum = await FinanceRepository(session).async_get_total_user_div()

    result += f"Всего {len(bod_list)} участников"
    result += f"\n{len(good)} участников c доступом к EURMTL"
    result += f"\nЧерез систему за всю историю выплачено {round(total_sum, 2)} EURMTL"

    balances = {}
    response = await http_session_manager.get_web_request(
        "GET", url=f"{config.horizon_url}/accounts/{MTLAddresses.public_bod_eur}", return_type="json"
    )
    rq = response.data if isinstance(response.data, dict) else {}
    for balance in rq.get("balances", []):
        if balance["asset_type"] == "credit_alphanum12":
            balances[balance["asset_code"]] = balance["balance"]

    result += f"\n\nСейчас к распределению {balances['EURMTL']} EURMTL или по {int(float(balances['EURMTL']) / len(good) * 100) / 100} на участника"
    return result


async def get_cash_balance(chat_id: int) -> str:
    """
    Get treasury balances with formatting.

    Args:
        chat_id: Telegram chat ID for access control

    Returns:
        Formatted table of treasury balances
    """
    total_cash = 0
    total_eurmtl = 0
    line = "============================\n"
    result = line
    result += "|Кубышка |Наличных| EURMTL |\n"

    treasure_list = await grist_manager.load_table_data(MTLGrist.NOTIFY_TREASURY, sort="order")

    section_cash = 0
    section_eurmtl = 0

    for treasure in treasure_list:
        if len(treasure["account_id"]) == 56:
            if not treasure["enabled"]:
                continue
            assets = cast(dict[str, Any], await get_balances(treasure["account_id"]))
            eurdebt = int(assets.get("EURDEBT", 0))
            eurmtl_amount = int(assets.get("EURMTL", 0))
            diff = eurdebt - eurmtl_amount
            name = treasure["name"] if chat_id == MTLChats.GuarantorGroup else treasure["name"][0]
            s_cash = f"{diff} ".rjust(8)
            s_eurmtl = f"{eurmtl_amount} ".rjust(8)
            result += f"|{name.ljust(8)}|{s_cash}|{s_eurmtl}|\n"
            total_cash += diff
            total_eurmtl += eurmtl_amount
            section_cash += diff
            section_eurmtl += eurmtl_amount
        else:
            # Add section subtotal before separator
            if section_cash > 0 or section_eurmtl > 0:
                s_section_cash = f"{section_cash} ".rjust(8)
                s_section_eurmtl = f"{section_eurmtl} ".rjust(8)
                result += f"=========={s_section_cash}={s_section_eurmtl}=\n"
            section_cash = 0
            section_eurmtl = 0

    # Add subtotal for last section
    if section_cash > 0 or section_eurmtl > 0:
        s_section_cash = f"{section_cash} ".rjust(8)
        s_section_eurmtl = f"{section_eurmtl} ".rjust(8)
        result += f"=========={s_section_cash}={s_section_eurmtl}=\n"

    s_cash = f"{total_cash} ".rjust(8)
    s_eurmtl = f"{total_eurmtl} ".rjust(8)
    result += f"|{'Итого'.ljust(8)}|{s_cash}|{s_eurmtl}|\n"

    result += line

    return result


def get_donate_list(account: dict) -> list:
    """
    Extract donation list from account data.

    Args:
        account: Account data dict from Horizon API

    Returns:
        List of [account_id, recipient, percent] entries
    """
    donate_list = []
    if "data" in account:
        data = account.get("data")
        account_id = account.get("account_id")
        if not isinstance(data, dict) or not isinstance(account_id, str):
            return donate_list
        for data_name in list(data):
            data_value = data[data_name]
            if data_name[:10] == "mtl_donate":
                if data_name.find("=") > 6:
                    persent: str
                    persent = data_name[data_name.find("=") + 1 :]
                    if isfloat(persent):
                        donate_data_value = decode_data_value(data_value)
                        donate_list.append([account_id, donate_data_value, persent])
    return donate_list


async def cmd_show_data(account_id: str, filter_by: str | None = None, only_data: bool = False) -> list:
    """
    Show account data entries.

    Args:
        account_id: Stellar account ID or special keyword ('delegate', 'donate')
        filter_by: Optional prefix filter for data keys
        only_data: If True, return only values; otherwise return 'key => value' pairs

    Returns:
        List of data entries
    """
    result_data = []
    if account_id == "delegate":  # not used, doesn't work
        pass
    elif account_id == "donate":
        # get all donations
        result_data = cast(list, await cmd_show_donates())
    else:
        response = await http_session_manager.get_web_request(
            "GET", url=f"{config.horizon_url}/accounts/{account_id}", return_type="json"
        )
        account_json = response.data if isinstance(response.data, dict) else {}
        if "data" in account_json:
            data = account_json["data"]
            for data_name in list(data):
                data_value = data[data_name]
                if not filter_by or data_name.find(filter_by) == 0:
                    if only_data:
                        result_data.append(decode_data_value(data_value))
                    else:
                        result_data.append(f"{data_name} => {decode_data_value(data_value)}")
    return result_data


async def cmd_show_donates(return_json: bool = False, return_table: bool = False):
    """
    Display all donations and donors.

    Args:
        return_json: If True, return as JSON dict
        return_table: If True, return as table list

    Returns:
        Donation data in requested format (list, dict, or table)
    """
    accounts = await stellar_get_all_mtl_holders()
    account_list = []

    for account in accounts:
        if account["data"]:
            account_list.append([account["account_id"], account["data"]])

    # https://github.com/montelibero-org/mtl/blob/main/json/donation.json
    # "GBOZAJYX43ANOM66SZZFBDG7VZ2EGEOTIK5FGWRO54GLIZAKHTLSXXWM":
    #   [ {  "recipient": "GCPOWDQQDVSAQGJXZW3EWPPJ5JCF4KTTHBYNB4U54AKQVDLZXLLYMXY7",
    #        "percent": "100" } ]

    # find donate
    donate_json = {}
    donate_data = []
    donate_table = []
    for account in account_list:
        if account[1]:
            data = account[1]
            recipients = []
            for data_name in list(data):
                data_value = data[data_name]
                if data_name[:10] == "mtl_donate":
                    recipient = {
                        "recipient": decode_data_value(data_value),
                        "percent": data_name[data_name.find("=") + 1 :],
                    }
                    recipients.append(recipient)
            if recipients:
                donate_json[account[0]] = recipients
                donate_data.append(f"{account[0]} ==>")
                donate_table.append([account[0], "", ""])
                for recipient in recipients:
                    donate_data.append(f"          {recipient['percent']} ==> {recipient['recipient']}")
                    donate_table.append(["", recipient["percent"], recipient["recipient"]])
                donate_data.append("******")

    if return_json:
        return donate_json
    if return_table:
        return donate_table
    return donate_data


async def cmd_show_guards_list() -> list:
    """
    Show council/guards members.

    Returns:
        List of [guard_address, data_name, data_value] entries
    """
    account_json = await stellar_get_account(MTLAddresses.public_bod_eur)

    result_data = []
    if "data" in account_json:
        data = account_json["data"]
        for data_name in list(data):
            data_value = data[data_name]
            if data_name[:13] == "bod_guarantor":
                guard = decode_data_value(data_value)
                result_data.append([guard, "", ""])
                account_json2 = await stellar_get_account(guard)
                if "data" in account_json2:
                    data2 = account_json2["data"]
                    for data_name_2 in list(data2):
                        data_value = data2[data_name_2]
                        if data_name_2.find("bod") == 0:
                            result_data.append(["", data_name_2, decode_data_value(data_value)])
            result_data.append(["*", "*", "*"])
    return result_data
