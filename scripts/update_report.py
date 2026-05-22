from datetime import datetime
import json
import asyncio
import re
from typing import Any, Optional, cast

import numpy as np
import requests
from gspread import WorksheetNotFound
from sqlalchemy.ext.asyncio import AsyncSession
from stellar_sdk import Asset, AiohttpClient
from stellar_sdk.sep.federation import resolve_stellar_address_async

from db.repositories import MessageRepository, FinanceRepository
from other.config_reader import start_path, config
from other.constants import MTLChats
from other.gspread_tools import gs_copy_sheets_with_style, agcm
from other.stellar import (
    stellar_get_issuer_assets,
    get_balances,
    stellar_get_offers,
    MTLAddresses,
    get_asset_swap_spread,
    MTLAssets,
    resolve_account,
    stellar_get_holders,
    stellar_get_transactions,
    get_pool_balances,
    cmd_show_guards_list,
    cmd_show_donates,
    cmd_gen_mtl_vote_list,
    decode_data_value,
    stellar_add_mtl_holders_info,
    stellar_get_trade_cost,
)

from other.web_tools import get_debank_balance
from scripts.mtl_backup import save_assets
from loguru import logger
from other.loguru_tools import safe_catch_async

# https://docs.gspread.org/en/latest/


def parse_sheet_number(value: object) -> Optional[float]:
    """Parse a numeric value from a Google Sheets cell."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None

    # Normalize common minus signs and negatives in parentheses.
    text = text.replace("\u2212", "-").replace("\u2014", "-").replace("\u2013", "-")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"

    # Remove whitespace (including non-breaking/skinny spaces) and non-numeric symbols.
    text = text.replace("\u00a0", "").replace("\u2009", "").replace("\u202f", "").replace(" ", "")
    text = re.sub(r"[^0-9,.\-+]", "", text)

    if "," in text and "." in text:
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")

    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


@safe_catch_async
async def check_eurmtl_b13_negative(session: AsyncSession, ss: Optional[Any] = None) -> Optional[float]:
    """Check eurmtl_report!B13 for negative values and notify if needed."""
    if ss is None:
        agc = await agcm.authorize()
        ss = await agc.open_by_key("1ZaopK2DRbP5756RK2xiLVJxEEHhsfev5ULNW5Yz_EZc")

    wks_eurmtl = await ss.worksheet("eurmtl_report")
    cell_b13 = await wks_eurmtl.acell("B13")
    b13_value = parse_sheet_number(cell_b13.value)
    if b13_value is None:
        logger.warning("B13 value не удалось распарсить: {raw!r}", raw=cell_b13.value)
        return None

    if b13_value < 0:
        await MessageRepository(session).async_add_message(
            MTLChats.SignGroup, f"⚠️ Сумма отрицательная: {b13_value}", topic_id=59548
        )
    return b13_value


@safe_catch_async
async def update_main_report(session: AsyncSession):
    agc = await agcm.authorize()

    # Open a sheet from a spreadsheet in one go
    ss = await agc.open_by_key("1ZaopK2DRbP5756RK2xiLVJxEEHhsfev5ULNW5Yz_EZc")
    wks = await ss.worksheet("autodata_config")

    # update data
    # usd
    rq = requests.get(f"http://api.currencylayer.com/live?access_key={config.currencylayer_id}&format=1&currencies=EUR")
    await wks.update(range_name="D3", values=[[float(rq.json()["quotes"]["USDEUR"])]])

    # BTC,XLM,ETH,XRP
    rq = requests.get(f"http://api.coinlayer.com/api/live?access_key={config.coinlayer_id}&symbols=BTC,XLM,ETH,XRP")
    await wks.update(range_name="D4", values=[[float(rq.json()["rates"]["BTC"])]])
    await wks.update(range_name="D5", values=[[float(rq.json()["rates"]["XLM"])]])
    await wks.update(range_name="D20", values=[[float(rq.json()["rates"]["ETH"])]])
    await wks.update(range_name="D21", values=[[float(rq.json()["rates"]["XRP"])]])

    # aum — gold spot price per 10g (EUR) via Kitco
    try:
        rq = requests.get("https://proxy.kitco.com/getPM?symbol=AU&currency=EUR&unit=gram", timeout=15)
        gold_per_gram = float(rq.text.strip().split(",")[6])  # mid price EUR/gram
        await wks.update(range_name="D6", values=[[gold_per_gram * 10]])
    except Exception as e:
        logger.warning(f"Failed to fetch gold price from Kitco: {e}")

    # defi
    defi_balance = await get_debank_balance("0x0358d265874b5cf002d1801949f1cee3b08fa2e9")
    await wks.update(range_name="D8", values=[[int(defi_balance)]])
    # sentry_sdk.capture_message(f'debank error - {debank}')
    defi_balance = await get_debank_balance("0xDb36745AA3601E2f12b07db58fF8d91946850a36")
    await wks.update(range_name="D11", values=[[int(defi_balance)]])

    addresses = await wks.get_values("A2:A")
    for address in addresses:
        if address and address[0] and len(address[0]) == 56:
            sheet_name = f"{address[0][:4]}..{address[0][-4:]}"
            try:
                address_sheet = await ss.worksheet(sheet_name)
            except WorksheetNotFound:
                address_sheet = await ss.add_worksheet(title=sheet_name, rows=100, cols=10)

            assets, data = await get_balances(address[0], return_data=True)

            update_data = [["DATA"]]
            for key in data:
                decoded_value = decode_data_value(data[key])
                try:
                    decoded_value = float(decoded_value)
                except ValueError:
                    pass
                update_data.append([key, decoded_value])
            await address_sheet.update(range_name="C1", values=update_data)

            update_data = [["ASSETS"]]
            for key in assets:
                update_data.append([key, float(assets.get(key, 0))])
            await address_sheet.update(range_name="A1", values=update_data)

            assets = await stellar_get_issuer_assets(address[0])
            update_data = [["ISSUER", "AMOUNT", "COST"]]
            for key in assets:
                update_data.append(
                    [key, float(assets.get(key, 0)), await stellar_get_trade_cost(Asset(code=key, issuer=address[0]))]
                )
            await address_sheet.update(range_name="E1", values=update_data)

            pools = await get_pool_balances(address[0])
            update_data = [["POOLS", "SHARES", "AMOUNT1", "AMOUNT2"]]
            for pool in pools:
                # [{'pool_id': '1b492b669959d3f082b5fb7dcc847d43371fd1f586209899603b93ac1a39b7f8', 'name': 'MTL-EURMTL', 'shares': 761437.8395765, 'token1_amount': 348606.2247324, 'token2_amount': 1685938.1857397}]
                update_data.append(
                    [pool["name"], float(pool["shares"]), float(pool["token1_amount"]), float(pool["token2_amount"])]
                )
            await address_sheet.update(range_name="H1", values=update_data)

    await wks.update(range_name="D15", values=[[datetime.now().strftime("%d.%m.%Y %H:%M:%S")]])

    await asyncio.sleep(5)
    await asyncio.to_thread(
        gs_copy_sheets_with_style,
        "1ZaopK2DRbP5756RK2xiLVJxEEHhsfev5ULNW5Yz_EZc",
        "1v2s2kQfciWJbzENOy4lHNx-UYX61Uctdqf1rE-2NFWc",
        "report",
        None,
    )
    await asyncio.to_thread(
        gs_copy_sheets_with_style,
        "1ZaopK2DRbP5756RK2xiLVJxEEHhsfev5ULNW5Yz_EZc",
        "1iQgWZ7vjkcN7tMJDUvTSXvLvzIxWD6ZnkmF8kx_Hu1c",
        "usdm_report",
        None,
    )
    await asyncio.to_thread(
        gs_copy_sheets_with_style,
        "1ZaopK2DRbP5756RK2xiLVJxEEHhsfev5ULNW5Yz_EZc",
        "1hn_GnLoClx20WcAsh0Kax3WP4SC5PGnjs4QZeDnHWec",
        "report",
        "B_TBL",
    )

    await update_main_report_additional(session=session)

    # Проверка B13 на отрицательное значение
    await check_eurmtl_b13_negative(session=session, ss=ss)

    logger.info(f"Main report all done {datetime.now()}")


@safe_catch_async
async def update_main_report_additional(session: AsyncSession):
    agc = await agcm.authorize()
    ss = await agc.open_by_key("1hn_GnLoClx20WcAsh0Kax3WP4SC5PGnjs4QZeDnHWec")
    wks_all = await ss.worksheet("IND_ALL")
    wks_monitoring = await ss.worksheet("MONITORING")

    # Проверка значения в первой ячейке столбца D
    value_cell = await wks_all.acell("D1")
    if value_cell.value != "Value":
        raise ValueError("Ожидалось 'Value' в ячейке D1")

    # add data
    statistic = calculate_statistics()
    await wks_all.update(
        range_name="D19:D21", values=[[statistic["EURMTL"]], [statistic["SATSMTL"]], [statistic["USDM"]]]
    )

    await wks_all.update(range_name="D24", values=[[statistic["Median"]]])
    await wks_all.update(range_name="D25", values=[[statistic["EURMTL_NONE_ZERO"]]])
    await wks_all.update(range_name="D28", values=[[statistic["MTL_MTLRECT"]]])
    await wks_all.update(range_name="D41", values=[[statistic["MTLAP"]]])

    # Получение данных из столбца D
    column_d_values = await wks_all.col_values(4)

    # Получение всех значений из столбца A листа MONITORING
    column_a_values = await wks_monitoring.col_values(1)
    # Находим первую пустую ячейку
    last_row = len(column_a_values) + 1

    # Вставка текущей даты в найденную ячейку
    current_date = datetime.now().strftime("%d.%m.%Y")

    # Подготовка данных для обновления (одна строка)
    row_update = [current_date] + column_d_values[1:]

    # Обновление данных за один запрос
    await wks_monitoring.update(range_name=f"A{last_row}", values=[row_update], value_input_option="USER_ENTERED")


def calculate_statistics():
    with open(f"{start_path}/backup/all.last.json", "r") as file:
        accounts = json.load(file)

    usdm_count = 0
    mtlap_count = 0
    satsmtl_count = 0
    eurmtl_count = 0
    mtl_mtlrect_count = 0
    mtl_mtlrect_amounts = []
    eurmtl_none_zero_count = 0

    for account in accounts:
        has_usdm = has_satsmtl = has_eurmtl = False
        mtl_mtlrect_balance = 0

        for balance in account.get("balances", []):
            asset_code = balance.get("asset_code", "")
            balance_amount = float(balance.get("balance", "0"))

            if asset_code == "USDM":
                has_usdm = True
            elif asset_code == "SATSMTL":
                has_satsmtl = True
            elif asset_code == "EURMTL":
                has_eurmtl = True
                if balance_amount > 0:
                    eurmtl_none_zero_count += 1
            elif asset_code == "MTLAP" and balance_amount > 0:
                mtlap_count += 1
            if asset_code in ["MTL", "MTLRECT"]:
                mtl_mtlrect_balance += balance_amount

        if mtl_mtlrect_balance > 1:
            mtl_mtlrect_count += 1
            mtl_mtlrect_amounts.append(mtl_mtlrect_balance)
            usdm_count += has_usdm
            satsmtl_count += has_satsmtl
            eurmtl_count += has_eurmtl

    median_mtl_mtlrect = np.median(mtl_mtlrect_amounts) if mtl_mtlrect_amounts else 0

    return {
        "USDM": usdm_count,
        "SATSMTL": satsmtl_count,
        "EURMTL": eurmtl_count,
        "MTL_MTLRECT": mtl_mtlrect_count,
        "Median": median_mtl_mtlrect,
        "MTLAP": mtlap_count - 1,
        "EURMTL_NONE_ZERO": eurmtl_none_zero_count,
    }


@safe_catch_async
async def update_fire(session: AsyncSession):
    agc = await agcm.authorize()
    ss = await agc.open_by_key("1hn_GnLoClx20WcAsh0Kax3WP4SC5PGnjs4QZeDnHWec")
    wks = await ss.worksheet("IND_ALL")

    # Получаем все значения из столбцов B и D
    column_B = await wks.get("B1:B100")
    column_D = await wks.get("D1:D100")

    # Ищем строку 'book value of 1 token' в столбце B
    for i, row in enumerate(column_B):
        for cell in row:
            if cell == "Share Market Price":
                # Нашли нужную строку, получаем соответствующее значение из столбца D
                cost_fire = column_D[i][0]
                break
        else:
            continue
        break
    else:
        await MessageRepository(session).async_send_admin_message("bad fire value")
        raise Exception("bad fire value")

    logger.info(f"cost_fire {cost_fire}")
    cost_fire = float(cost_fire.replace(",", ".")) * 0.8
    # check_fire removed (unused/undefined)


async def update_guarantors_report():
    agc = await agcm.authorize()

    # Open a sheet from a spreadsheet in one go
    ss = await agc.open("EURMTL Guarantors")
    wks = await ss.worksheet("Guarantors")

    # Update a range of cells using the top left corner address
    now = datetime.now()

    address_list = await wks.col_values(2)
    address_list.pop(0)
    address_list.pop(0)
    len_address_list = len(address_list)

    all_accounts = await stellar_get_holders(MTLAssets.eurdebt_asset)
    for account in all_accounts:
        if account["id"] in address_list:
            pass
        else:
            balances = account["balances"]
            found = list(filter(lambda x: x.get("asset_code") and x.get("asset_code") == "EURDEBT", balances))
            if float(found[0]["balance"]) > 1:
                address_list.append(account["id"])

    if len(address_list) > len_address_list:
        update_list = []
        for account in address_list:
            update_list.append([account])
        await wks.update(range_name="B3", values=update_list)

    date_list = await wks.col_values(4)
    date_list.pop(0)
    #    date_list.pop(0)

    update_list = []

    for idx, address in enumerate(address_list):
        eur_sum = ""
        debt_sum = ""
        if idx == len(date_list):
            date_list.append("")
        if address and (len(address) == 56):
            # print(val)
            # get balance
            balances = await get_balances(address)
            eur_sum = round(float(balances.get("EURMTL", 0)))
            debt_sum = float(balances.get("EURDEBT", 0))
        dt_google = ""  # if dt == '' else (
        # datetime.strptime(dt, '%d.%m.%Y') - datetime(1899, 12, 30)).days
        update_list.append([dt_google, eur_sum, debt_sum])

    await wks.update(range_name="E3", values=update_list)

    # rects
    address_list = await wks.col_values(3)
    address_list.pop(0)
    address_list.pop(0)
    update_list = []
    for address in address_list:
        if len(address) == 56:
            balances = await get_balances(address)
            update_list.append([balances.get("MTLRECT", 0)])
        else:
            update_list.append(["=["])

    await wks.update(range_name="H3", values=update_list)

    await wks.update(range_name="B2", values=[[now.strftime("%d.%m.%Y %H:%M:%S")]])

    logger.info(f"report Guarantors all done {now}")


@safe_catch_async
async def update_top_holders_report(session: AsyncSession):
    agc = await agcm.authorize()

    now = datetime.now()

    ss = await agc.open("MTL_TopHolders")
    wks = await ss.worksheet("TopHolders")
    wks_d = await ss.worksheet("Delegate")

    delegate_list = {}
    vote_list = await cmd_gen_mtl_vote_list(trim_count=30, delegate_list=delegate_list)
    await stellar_add_mtl_holders_info(vote_list)

    update_data = []
    for account in vote_list:
        update_data.append(
            [
                account.account_id,
                account.balance_mtl,
                account.balance_rect,
                account.balance_delegated,
                account.balance,
                account.votes,
                account.calculated_votes,
            ]
        )

    await wks.update(range_name="B2", values=update_data)

    update_data = []
    for key in delegate_list:
        update_data.append([key, delegate_list[key]])

    for _ in range(1, 5):
        update_data.append(["", ""])

    await wks_d.update(range_name="A2", values=update_data)

    await wks.update(range_name="I1", values=[[now.strftime("%d.%m.%Y %H:%M:%S")]])

    records = await wks.get_values("I2:I21")
    gd_link = "https://docs.google.com/spreadsheets/d/1HSgK_QvK4YmVGwFXuW5CmqgszDxe99FAS2btN3FlQsI/edit#gid=171831156"
    for record in records:
        if record[0] != "0":
            text = f'You need update votes <a href="{gd_link}">more info</a>'
            await MessageRepository(session).async_add_message(MTLChats.SignGroup, text, use_alarm=1, topic_id=59558)
            break

    logger.info(f"report topholders all done {now}")


@safe_catch_async
async def update_bdm_report():
    agc = await agcm.authorize()

    now = datetime.now()

    ss = await agc.open("MTL_TopHolders")
    wks = await ss.worksheet("BDM")

    bdm_list = await cmd_show_guards_list()

    for bdm in bdm_list:
        if len(bdm[0]) == 56:
            bdm.append(await resolve_account(bdm[0]))
        if len(bdm[2]) == 56:
            bdm.append(await resolve_account(bdm[2]))

    await wks.update(range_name="A2", values=bdm_list)
    await wks.update(range_name="G1", values=[[now.strftime("%d.%m.%Y %H:%M:%S")]])

    logger.info(f"update bdm_report all done {now}")


async def update_mmwb_report(session: AsyncSession):
    agc = await agcm.authorize()

    now = datetime.now()

    ss = await agc.open("MMWB MM TABLE")
    wks = await ss.worksheet("DATA")

    # check structure
    records = await wks.get_values("O1")
    if records != [["Баланс %"]]:
        # print(records)
        raise Exception("wrong structure")
    records = await wks.get_values("B2:B6")
    if records[0][0] != "GDEMWIXGF3QQE7CJIOKWWMJAXAWGINJRR6DOOOSNO3C4UQGPDOA3OBOT":
        # print(records)
        raise Exception("wrong structure")

    # update data EURMTL	USDM	USDC	XLM BTC*
    update_data = []
    balances = await get_balances(MTLAddresses.public_exchange_eurmtl_xlm)
    offers = await stellar_get_offers(MTLAddresses.public_exchange_eurmtl_xlm)
    costs = await get_asset_swap_spread(MTLAssets.eurmtl_asset, MTLAssets.xlm_asset)
    update_data.append([balances.get("EURMTL", 0), None, None, balances.get("XLM", 0), None, len(offers), costs[2]])
    balances = await get_balances(MTLAddresses.public_exchange_eurmtl_usdm)
    offers = await stellar_get_offers(MTLAddresses.public_exchange_eurmtl_usdm)
    costs = await get_asset_swap_spread(MTLAssets.eurmtl_asset, MTLAssets.usdm_asset)
    update_data.append(
        [balances.get("EURMTL", 0), balances.get("USDM", 0), balances.get("USDC", 0), None, None, len(offers), costs[2]]
    )
    balances = await get_balances(MTLAddresses.public_exchange_usdm_sats)
    offers = await stellar_get_offers(MTLAddresses.public_exchange_usdm_sats)
    costs = await get_asset_swap_spread(MTLAssets.usdm_asset, MTLAssets.satsmtl_asset)
    update_data.append(
        [
            balances.get("EURMTL", 0),
            balances.get("USDM", 0),
            None,
            None,
            balances.get("SATSMTL", 0),
            len(offers),
            costs[2],
        ]
    )
    balances = await get_balances(MTLAddresses.public_exchange_usdm_mtlfarm)
    offers = await stellar_get_offers(MTLAddresses.public_exchange_usdm_mtlfarm)
    costs = await get_asset_swap_spread(MTLAssets.usdm_asset, MTLAssets.mtlfarm_asset)
    update_data.append(
        [
            balances.get("EURMTL", 0),
            balances.get("USDM", 0),
            None,
            None,
            balances.get("MTLFARM", 0),
            len(offers),
            costs[2],
        ]
    )
    balances = await get_balances(MTLAddresses.public_exchange_usdm_xlm)
    offers = await stellar_get_offers(MTLAddresses.public_exchange_usdm_xlm)
    costs = await get_asset_swap_spread(MTLAssets.usdm_asset, MTLAssets.xlm_asset)
    update_data.append([None, balances.get("USDM", 0), None, balances.get("XLM", 0), None, len(offers), costs[2]])
    balances = await get_balances(MTLAddresses.public_exchange_usdm_usdc)
    offers = await stellar_get_offers(MTLAddresses.public_exchange_usdm_usdc)
    costs = await get_asset_swap_spread(MTLAssets.usdm_asset, MTLAssets.usdc_asset)
    update_data.append([None, balances.get("USDM", 0), balances.get("USDC", 0), None, None, len(offers), costs[2]])

    balances = await get_balances(MTLAddresses.public_exchange_eurmtl_eurc)
    offers = await stellar_get_offers(MTLAddresses.public_exchange_eurmtl_eurc)
    costs = await get_asset_swap_spread(MTLAssets.eurmtl_asset, MTLAssets.eurc_asset)
    update_data.append([balances.get("EURMTL", 0), None, balances.get("EURC", 0), None, None, len(offers), costs[2]])

    balances = await get_balances(MTLAddresses.public_exchange_mtl_xlm)
    offers = await stellar_get_offers(MTLAddresses.public_exchange_mtl_xlm)
    costs = await get_asset_swap_spread(MTLAssets.mtl_asset, MTLAssets.xlm_asset)
    update_data.append([balances.get("MTL", 0), None, None, balances.get("XLM", 0), None, len(offers), costs[2]])

    balances = await get_balances(MTLAddresses.public_fire)
    update_data.append([balances.get("EURMTL", 0), None, None, None, balances.get("MTL", 0)])

    await wks.update(range_name="E2", values=update_data)

    records = await wks.get_values("O2:O6")
    for record in records:
        value = float(record[0].replace(",", "."))
        if value < 0.2 or value > 0.8:
            await MessageRepository(session).async_send_admin_message(f"update_mmwb_report balance error {value}")

    await wks.update(range_name="Q1", values=[[now.strftime("%d.%m.%Y %H:%M:%S")]])
    logger.info(f"update mmwb_report all done {now}")


def my_float(s):
    result = round(float(s), 2) if len(str(s)) > 1 else s
    return result


async def update_airdrop():
    agc = await agcm.authorize()
    client = AiohttpClient()

    # Open a sheet from a spreadsheet in one go
    ss = await agc.open("MTL_Airdrop_register")
    wks = await ss.worksheet("EUR_GNRL")

    # Update a range of cells using the top left corner address
    now = datetime.now()

    address_list = await wks.col_values(4)
    fed_address_list = await wks.col_values(5)
    start_pos = int((await wks.cell(1, 1)).value)

    start_pos = start_pos if start_pos > 2 else 2

    max_length = len(address_list) if len(address_list) > len(fed_address_list) else len(fed_address_list)

    # fill addresses

    # print(address_list)
    # print(fed_address_list)

    for idx in range(start_pos, max_length):
        if len(address_list) > idx:  # if address more that federal
            if (
                (len(address_list[idx]) < 10)
                and (len(fed_address_list) >= idx)
                and (len(fed_address_list[idx]) > 5)
                and (fed_address_list[idx].count("*") > 0)
            ):
                try:
                    # print(address_list[idx], fed_address_list[idx])
                    address = await resolve_stellar_address_async(fed_address_list[idx], client=client)
                    # print(address.account_id)
                    await wks.update(range_name=f"D{idx + 1}", values=[[address.account_id]])
                except Exception:
                    logger.info("Resolving error", address_list[idx], fed_address_list[idx])
        else:  # if federal more that address
            if (len(fed_address_list[idx]) > 5) and (fed_address_list[idx].count("*") > 0):
                # print(fed_address_list[idx], '***')
                address = await resolve_stellar_address_async(fed_address_list[idx], client=client)
                # print(address.account_id)
                await wks.update(range_name=f"D{idx + 1}", values=[[address.account_id]])

    address_list = await wks.col_values(4)
    address_list.pop(0)
    address_list.pop(0)
    update_list = []
    start_pos = start_pos if start_pos > 3 else 3

    for idx, address in enumerate(address_list[start_pos:]):
        mtl_sum = ""
        eurmtl_sum = ""
        xlm_sum = ""
        sats_sum = ""
        if address and (len(address) == 56):
            # print(val)
            # get balance
            balance_dic: dict = await get_balances(address)
            if balance_dic:
                mtl_sum = my_float(balance_dic.get("MTL", ""))
                eurmtl_sum = my_float(balance_dic.get("EURMTL", ""))
                xlm_sum = my_float(balance_dic.get("XLM", ""))
                sats_sum = my_float(balance_dic.get("SATSMTL", ""))
            else:
                mtl_sum, eurmtl_sum, xlm_sum, sats_sum = "D", "D", "D", "D"

        update_list.append([xlm_sum, eurmtl_sum, mtl_sum, sats_sum])

    # print(update_list)
    await wks.update(range_name=f"K{start_pos + 3}", values=update_list)
    await wks.update(range_name="O2", values=[[now.strftime("%d.%m.%Y %H:%M:%S")]])
    await client.close()

    logger.info(f"report 3 all done {now}")


async def update_donate_report(session: AsyncSession):
    await agcm.authorize()


#    # Open a sheet from a spreadsheet in one go
#    wks = gc.open("MTL_TopHolders").worksheet("Donates")
#
#    # Update a range of cells using the top left corner address
#    now = datetime.now()
#
#    # donates
#
#    updates = fb.execsql("""select user_key, iif(total_pay > 0, sl.total_pay, 0) total_pay,
#    coalesce(total_receive, 0) total_receive,
#    (select coalesce(sum(p.user_calc - p.user_div), 0)
#          from t_payments p
#         where p.id_div_list = sl.max_div_num
#           and p.user_key = sl.user_key) last_pay,
#       (select coalesce(sum(p.user_div), 0)
#          from t_payments p
#         where p.id_div_list = sl.max_donate_num
#           and p.user_key = sl.user_key) last_receive
#  from (select pp.user_key,
#               (select sum(p.user_calc - p.user_div)
#                  from t_payments p
#                  join t_div_list d on d.id = p.id_div_list
#                 where p.user_key = pp.user_key
#                   and d.memo like '%div%'
#                   and p.was_packed = 1) total_pay,
#               (select sum(p.user_div)
#                  from t_payments p
#                  join t_div_list d on d.id = p.id_div_list
#                 where p.user_key = pp.user_key
#                   and d.memo like '%donate%'
#                   and p.was_packed = 1) total_receive,
#               (select first 1 d.id
#                  from t_div_list d
#                 where d.memo like '%div%'
#                 order by d.id desc) max_div_num,
#               (select first 1 d.id
#                  from t_div_list d
#                 where d.memo like '%donate%'
#                 order by d.id desc) max_donate_num
#          from t_payments pp
#          join t_div_list dd on dd.id = pp.id_div_list and
#                dd.pay_type = 0
#         group by pp.user_key) sl
# where (sl.total_pay > 0) or (total_receive > 0)
#    """)
#    update_list = []
#
#    for key in updates:
#        account_name = address_id_to_username(key[0])
#        update_list.append([account_name, key[3], key[4], key[1], key[2]])
#
#    update_list.append(['', '', '', '', ''])
#    update_list.append(['', '', '', '', ''])
#    update_list.append(['', '', '', '', ''])
#
#    # print(update_list)
#    await wks.update('A2', update_list)
#    await wks.update('G1', now.strftime('%d.%m.%Y %H:%M:%S'))
#    logger.info(f'donate report done {now}')


async def update_donates_new():
    agc = await agcm.authorize()

    # Update a range of cells using the top left corner address
    now = datetime.now()
    # Open a sheet from a spreadsheet in one go
    ss = await agc.open("MTL_TopHolders")
    wks = await ss.worksheet("DonatesNew")

    update_list = await cmd_show_donates(return_table=True)

    await wks.update(range_name="A2", values=update_list)
    await wks.update(range_name="E1", values=[[now.strftime("%d.%m.%Y %H:%M:%S")]])
    update_list.append(["", "", ""])
    update_list.append(["", "", ""])
    update_list.append(["", "", ""])

    logger.info(f"new done {now}")


async def update_export(session: AsyncSession):
    agc = await agcm.authorize()

    # Open a sheet from a spreadsheet in one go
    ss = await agc.open("test export 4")
    wks = await ss.worksheet("2023")

    # Update a range of cells using the top left corner address
    now = datetime.now()

    update_list = []

    # print(update_list)
    last_row = (await wks.find("LAST", in_column=1)).row
    last_id = (await wks.get_values(f"A{last_row - 1}"))[0][0]

    list_operation = await FinanceRepository(session).async_get_operations(last_id)

    for record in list_operation:
        update_list.append(
            [
                record.id,
                record.dt.strftime("%d.%m.%Y %H:%M:%S"),
                record.operation,
                float(record.amount1) if record.amount1 else None,
                record.code1,
                float(cast(float, record.amount2)) if record.amount2 else None,
                record.code2,
                record.from_account,
                record.for_account,
                None,
                None,
                record.ledger,
            ]
        )

    update_list.append(
        [
            "LAST",
        ]
    )
    await wks.update(range_name=f"A{last_row}", values=update_list, value_input_option="USER_ENTERED")
    # await wks.update('H1', now.strftime('%d.%m.%Y %H:%M:%S'))

    logger.info(f"export all done {now}")


async def update_fest(session: AsyncSession):
    # Авторизация и открытие таблицы
    agc = await agcm.authorize()
    ss = await agc.open_by_key("1m4NcL3Dqo1UnF4LEGjNO6ZYxSnhykN1HT_2Uts8HpaU")
    # get date
    wks = await ss.worksheet("config")
    date_1 = datetime.strptime((await wks.get_values("B1"))[0][0], "%d.%m.%Y")
    date_2 = datetime.strptime((await wks.get_values("B2"))[0][0], "%d.%m.%Y")

    wks = await ss.worksheet("data")

    # Получение данных из таблицы
    data = await wks.get_all_values()

    # Проверка структуры данных
    headers = data[0]
    if headers[4] != "Итого выручка лавки (сумма входящих транз EURMTL)":
        print(headers[4])
        raise ValueError("Неверный формат таблицы")

    # Обработка данных
    update_list = []
    for row in data[1:]:  # Пропускаем заголовки
        address = row[1]
        if len(address) == 56:  # Проверяем, что адрес состоит из 56 символов
            transactions = await stellar_get_transactions(address, date_1, date_2)
            # total_amount = sum(transaction.amount for transaction in transactions if transaction)
            total_amount = 0
            for transaction in transactions:
                if (
                    transaction.get("asset_code") == MTLAssets.eurmtl_asset.code
                    and transaction.get("asset_issuer") == MTLAssets.eurmtl_asset.issuer
                    and transaction.get("type") == "payment"
                    and transaction.get("to") == address
                ):
                    total_amount += float(transaction["amount"])

            update_list.append([total_amount])
        else:
            update_list.append([0])

    # Обновление таблицы
    await wks.update(range_name="E2", values=update_list, value_input_option="USER_ENTERED")

    wks = await ss.worksheet("config")
    await wks.update(range_name="B4", values=[[datetime.now().strftime("%d.%m.%Y %H:%M:%S")]])
    logger.info("update_fest completed successfully")


async def main_report():
    from db.session import AsyncSessionPool

    logger.add("logs/update_report.log", rotation="1 MB")

    async with AsyncSessionPool() as session:
        await update_main_report(session)
        await session.commit()
    await update_guarantors_report()
    # async with AsyncSessionPool() as session:
    #     await update_bim_data(session)
    async with AsyncSessionPool() as session:
        await update_top_holders_report(session)
        await session.commit()
    async with AsyncSessionPool() as session:
        await update_mmwb_report(session)
        await session.commit()
    await update_donates_new()
    # async with AsyncSessionPool() as session:
    #     await update_wallet_report(session)
    #     await update_wallet_report2(session)
    #     await update_export(session)
    #     await update_fire(session)


@safe_catch_async
async def lite_report(session_pool):
    await save_assets([MTLAssets.mtl_asset, MTLAssets.mtlap_asset, MTLAssets.mtlrect_asset, MTLAssets.eurmtl_asset])
    await asyncio.sleep(10)

    async with session_pool() as session:
        await update_main_report(session)
        await asyncio.sleep(10)
        await update_top_holders_report(session)
        await asyncio.sleep(10)
        await update_mmwb_report(session)
        await session.commit()
        # await update_wallet_report(session)
        # await update_wallet_report2(session)


async def test_report():
    from db.session import AsyncSessionPool

    logger.add("logs/update_report.log", rotation="1 MB")

    async with AsyncSessionPool() as session:
        await check_eurmtl_b13_negative(session)
        await session.commit()


if __name__ == "__main__":
    logger.add("logs/mtl_report.log", rotation="1 MB")

    asyncio.run(test_report())

    # if 'report' in sys.argv:
    #     sentry_sdk.init(
    #         dsn=config.sentry_report_dsn,
    #         traces_sample_rate=1.0,
    #         profiles_sample_rate=1.0,
    #     )
    #     asyncio.run(main_report())
    # elif 'one_exchange' in sys.argv:
    #     pass
    # else:
    #     print('need more parameters')
    #     from db.quik_pool import quik_pool
    #
    #     asyncio.run(update_main_report(quik_pool()))  # only from skynet
    #     # print(calculate_statistics())
