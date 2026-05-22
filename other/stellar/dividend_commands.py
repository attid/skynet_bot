# other/stellar/dividend_commands.py
"""Dividend calculation and payment command functions for MTL ecosystem.

These functions handle the creation, calculation, and execution of dividend
payments for EURMTL, SATSMTL, USDM and related tokens.
"""

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from stellar_sdk import Asset, TransactionBuilder, TransactionEnvelope
from stellar_sdk.client.aiohttp_client import AiohttpClient
from stellar_sdk.server_async import ServerAsync

from db.repositories import FinanceRepository
from other.config_reader import config
from .sdk_utils import load_account_async, get_network_passphrase, get_server, get_horizon_url
from other.loguru_tools import safe_catch_async
from shared.infrastructure.database.models import TDivList, TPayments, TTransaction

from .balance_utils import get_balances, stellar_get_holders, stellar_get_all_mtl_holders, stellar_get_issuer_assets
from .constants import BASE_FEE, PACK_COUNT, MTLAddresses, MTLAssets
from .payment_service import stellar_async_submit
from .sdk_utils import stellar_sign
from .xdr_utils import decode_data_value, stellar_get_transaction_builder


def isfloat(value) -> bool:
    """Check if value can be converted to float."""
    try:
        float(value)
        return True
    except ValueError:
        return False


def get_key_1(key):
    """Sort key function for dividend accounts - by balance (index 1)."""
    return key[1]


def cmd_gen_data_xdr(account_id: str, data: str, xdr: str = None) -> str:
    """
    Generate XDR for managing account data entry.

    Args:
        account_id: Stellar account public key
        data: Data string in format "name:value"
        xdr: Optional existing XDR to append to

    Returns:
        Transaction XDR string
    """
    if xdr:
        transaction = stellar_get_transaction_builder(xdr)
    else:
        server = get_server()
        root_account = server.load_account(account_id)
        transaction = TransactionBuilder(
            source_account=root_account, network_passphrase=get_network_passphrase(), base_fee=BASE_FEE
        )
        transaction.set_timeout(60 * 60 * 24 * 7)

    data = data.split(":")
    data_name = data[0]
    data_value = data[1]
    if len(data_value) == 0:
        data_value = None

    transaction.append_manage_data_op(data_name=data_name, data_value=data_value)
    transaction = transaction.build()
    return transaction.to_xdr()


def get_donate_list(account: dict) -> list:
    """
    Extract donation rules from account data entries.

    Args:
        account: Account data dict with 'data' and 'account_id' keys

    Returns:
        List of [account_id, recipient, percent] lists
    """
    donate_list = []
    if "data" in account:
        data = account.get("data")
        account_id = account.get("account_id")
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


async def get_liquidity_pools_for_asset(asset: Asset) -> list:
    """
    Get all liquidity pools containing specified asset.

    Args:
        asset: Stellar Asset to query

    Returns:
        List of pool dicts with reserves_dict added
    """
    async with ServerAsync(horizon_url=get_horizon_url(), client=AiohttpClient(request_timeout=3 * 60)) as server:
        pools = []
        pools_call_builder = server.liquidity_pools().for_reserves([asset]).limit(200)

        page_records = await pools_call_builder.call()
        while page_records["_embedded"]["records"]:
            for pool in page_records["_embedded"]["records"]:
                # Remove _links from results
                pool.pop("_links", None)

                # Convert reserves list to reserves_dict
                reserves_dict = {reserve["asset"]: reserve["amount"] for reserve in pool["reserves"]}
                pool["reserves_dict"] = reserves_dict

                # Remove original reserves list
                pool.pop("reserves", None)

                pools.append(pool)

            page_records = await pools_call_builder.next()
        return pools


async def cmd_create_list(session: AsyncSession, memo: str, pay_type: int) -> int:
    """
    Create new dividend list record in database.

    Args:
        session: Database session
        memo: Memo text for the dividend batch
        pay_type: Payment type (0=EURMTL div, 1=BIM, 4=SATSMTL, 5=USDM MTL, 6=USDM USDM)

    Returns:
        ID of created dividend list
    """
    new = TDivList(memo=memo, pay_type=pay_type)
    session.add(new)
    await session.flush()
    await session.commit()
    return new.id


async def cmd_calc_bim_pays(session: AsyncSession, list_id: int, test_sum: int = 0) -> list:
    """
    Calculate MTLAP holder dividend allocations for Basic Income MTL (BIM).

    Args:
        session: Database session
        list_id: Dividend list ID to associate payments with
        test_sum: Optional fixed amount for testing (0 = use real balance)

    Returns:
        List of [address, balance, calc_div, final_div, list_id] lists
    """
    if test_sum > 0:
        div_sum = test_sum
    else:
        div_sum = await get_balances(MTLAddresses.public_bod_eur)
        div_sum = int(float(div_sum["EURMTL"]) / 2)  # 50%
        logger.info(f"div_sum = {div_sum}")

    accounts = await stellar_get_holders(MTLAssets.mtlap_asset)

    secretary = "GCPOWDQQDVSAQGJXZW3EWPPJ5JCF4KTTHBYNB4U54AKQVDLZXLLYMXY7"

    valid_accounts = [
        account
        for account in accounts
        if account["account_id"] != secretary
        and (await get_balances(account["account_id"], account_json=account)).get("EURMTL") is not None
    ]
    one_mtlap_accounts = [
        account
        for account in valid_accounts
        if 1 <= (await get_balances(account["account_id"], account_json=account))["MTLAP"] < 2
    ]
    two_or_more_mtlap_accounts = [
        account
        for account in valid_accounts
        if (await get_balances(account["account_id"], account_json=account))["MTLAP"] >= 2
    ]

    amount_for_one_mtlap_accounts = int(div_sum * 0.2)
    amount_for_two_or_more_mtlap_accounts = int(div_sum * 0.8)

    sdiv_one_mtlap = (
        int(amount_for_one_mtlap_accounts / len(one_mtlap_accounts) * 100) / 100 if one_mtlap_accounts else 0
    )
    sdiv_two_mtlap = (
        int(amount_for_two_or_more_mtlap_accounts / len(two_or_more_mtlap_accounts) * 100) / 100
        if two_or_more_mtlap_accounts
        else 0
    )

    mtl_accounts = []
    for account in valid_accounts:
        balances = await get_balances(account["account_id"], account_json=account)
        bls = balances["EURMTL"]
        if account in two_or_more_mtlap_accounts:
            div = sdiv_two_mtlap
        elif account in one_mtlap_accounts:
            div = sdiv_one_mtlap
        else:
            div = 0
        mtl_accounts.append([account["account_id"], bls, div, div, list_id])

    mtl_accounts.sort(key=lambda x: x[0], reverse=True)
    payments = [
        TPayments(user_key=item[0], mtl_sum=item[1], user_calc=item[2], user_div=item[3], id_div_list=item[4])
        for item in mtl_accounts
    ]
    session.add_all(payments)
    await session.commit()

    return mtl_accounts


async def cmd_calc_divs(session: AsyncSession, div_list_id: int, donate_list_id: int, test_sum: int = 0) -> list:
    """
    Calculate and prepare EURMTL dividends for MTL/MTLRECT holders.

    Args:
        session: Database session
        div_list_id: Dividend list ID for regular payments
        donate_list_id: Dividend list ID for donation payments
        test_sum: Optional fixed amount for testing (0 = use real balance)

    Returns:
        List of [address, balance, calc_div, final_div, list_id] lists
    """
    div_accounts = []
    donates = []

    # Get all accounts with MTL
    accounts = await stellar_get_all_mtl_holders()

    # Calculate total MTL and MTLRECT sum
    mtl_sum = 0.0
    for account in accounts:
        balances = account["balances"]
        for balance in balances:
            if balance["asset_type"][0:15] == "credit_alphanum":
                if balance["asset_issuer"] == MTLAddresses.public_issuer:
                    if balance["asset_code"] == "MTL":
                        mtl_sum += float(balance["balance"])
                    elif balance["asset_code"] == "MTLRECT":
                        mtl_sum += float(balance["balance"])

    # Determine distribution amount
    if test_sum > 0:
        div_sum = test_sum
    else:
        div_sum = await get_balances(MTLAddresses.public_div)
        div_sum = float(div_sum["EURMTL"]) - 0.1
        logger.info(f"div_sum = {div_sum}")
        await stellar_async_submit(
            stellar_sign(
                cmd_gen_data_xdr(MTLAddresses.public_div, f"LAST_DIVS:{div_sum}"),
                config.private_sign.get_secret_value(),
            )
        )

    # Process each account
    for account in accounts:
        balances = account["balances"]
        balance_mtl = 0
        balance_rect = 0
        eur = 0
        # check all balance
        for balance in balances:
            if balance["asset_type"][0:15] == "credit_alphanum":
                if balance["asset_issuer"] == MTLAddresses.public_issuer:
                    if balance["asset_code"] == "MTL":
                        balance_mtl = round(float(balance["balance"]), 7)
                    elif balance["asset_code"] == "MTLRECT":
                        balance_rect = round(float(balance["balance"]), 7)
                    elif balance["asset_code"] == "EURMTL":
                        eur = 1

        total_balance = balance_mtl + balance_rect
        div = round(div_sum / mtl_sum * total_balance, 7)
        donates.extend(get_donate_list(account))

        if (
            (eur > 0)
            and (div > 0.0001)
            and (account["account_id"] not in [MTLAddresses.public_issuer, MTLAddresses.public_pawnshop])
        ):
            div_accounts.append([account["account_id"], total_balance, div, div, div_list_id])

    # calc donate
    donate_list = []
    for mtl_account in div_accounts:
        found_list = list(filter(lambda x: x[0] == mtl_account[0], donates))
        for donate_rules in found_list:
            calc_sum = round(float(donate_rules[2]) * float(mtl_account[2]) / 100, 7)
            if mtl_account[3] >= calc_sum:
                found_calc = list(filter(lambda x: x[0] == donate_rules[1], donate_list))
                if found_calc:
                    for donate in donate_list:
                        if donate[0] == donate_rules[1]:
                            donate[3] += calc_sum
                            break
                else:
                    donate_list.append([donate_rules[1], 0, 0, calc_sum, donate_list_id])
                mtl_account[3] = mtl_account[3] - calc_sum

    div_accounts.sort(key=get_key_1, reverse=True)
    div_accounts.extend(donate_list)

    # Save to DB
    payments = [
        TPayments(user_key=item[0], mtl_sum=item[1], user_calc=item[2], user_div=item[3], id_div_list=item[4])
        for item in div_accounts
    ]
    session.add_all(payments)
    await session.commit()

    return div_accounts


async def cmd_calc_sats_divs(session: AsyncSession, div_list_id: int, test_sum: int = 0):
    """
    Calculate SATSMTL dividends for MTL/MTLRECT holders.

    Note: Currently disabled (returns issuer assets only).

    Args:
        session: Database session
        div_list_id: Dividend list ID
        test_sum: Optional fixed amount for testing

    Returns:
        Issuer assets dict (calculation logic is commented out)
    """
    all_issuer = await stellar_get_issuer_assets(MTLAddresses.public_issuer)
    # Implementation is currently commented out in the original
    return all_issuer


async def cmd_calc_usdm_divs(session: AsyncSession, div_list_id: int, test_sum: int = 0):
    """
    Calculate USDM dividends for MTL/MTLRECT holders.

    Note: Currently disabled (returns None).

    Args:
        session: Database session
        div_list_id: Dividend list ID
        test_sum: Optional fixed amount for testing

    Returns:
        None (calculation logic is commented out)
    """
    pass


@safe_catch_async
async def cmd_calc_usdm_usdm_divs(
    session: AsyncSession, div_list_id: int, test_sum: int = 0, test_for_address: Optional[str] = None
) -> list:
    """
    Calculate USDM distribution dividends for USDM holders.

    Distributes USDM to holders based on their average balance over the period.

    Args:
        session: Database session
        div_list_id: Dividend list ID
        test_sum: Optional fixed amount for testing (0 = use real balance)
        test_for_address: Optional address to calculate for (returns only that address)

    Returns:
        List of [address, balance, calc_div, final_div, list_id] lists
    """
    div_accounts = []
    if test_sum > 0:
        div_sum = test_sum
    else:
        div_sum = await get_balances(MTLAddresses.public_usdm_div)
        div_sum = float(div_sum["USDM"]) - 0.1
        logger.info(f"div_sum = {div_sum}")
        if not test_for_address:  # Only write to blockchain if not a test calculation
            await stellar_async_submit(
                stellar_sign(
                    cmd_gen_data_xdr(MTLAddresses.public_usdm_div, f"LAST_DIVS_USDM:{div_sum}"),
                    config.private_sign.get_secret_value(),
                )
            )

    if div_sum > 700:
        logger.info(f"div_sum = {div_sum}")
        return []

    accounts = await stellar_get_holders(MTLAssets.usdm_asset)
    pools = await get_liquidity_pools_for_asset(MTLAssets.usdm_asset)
    total_calc_sum = 0

    for account in accounts:
        balances = account["balances"]
        token_balance = 0
        for balance in balances:
            if (
                balance["asset_type"] == "credit_alphanum4"
                and balance["asset_code"] == MTLAssets.usdm_asset.code
                and balance["asset_issuer"] == MTLAssets.usdm_asset.issuer
            ):
                token_balance += float(balance["balance"])
            elif balance["asset_type"] == "liquidity_pool_shares":
                # Find pool by ID and calculate USDM share for account
                pool_id = balance["liquidity_pool_id"]
                pool_share = float(balance["balance"])
                for pool in pools:
                    if pool["id"] == pool_id:
                        usdm_amount = float(
                            pool["reserves_dict"].get(MTLAssets.usdm_asset.code + ":" + MTLAssets.usdm_asset.issuer, 0)
                        )
                        total_shares = float(pool["total_shares"])
                        # Calculate USDM share in pool belonging to account
                        if total_shares > 0 and pool_share > 0:
                            token_balance += (pool_share / total_shares) * usdm_amount

        div_accounts.append([account["account_id"], token_balance, 0, 0, div_list_id])
        total_calc_sum += token_balance

    div_accounts_dict = {account[0]: account[1] for account in div_accounts}

    period_start = date(2025, 11, 1)
    period_end = date(2025, 11, 10)
    current_date = period_end

    div_accounts_dict_month = {account: 0 for account in div_accounts_dict}
    month_full_sum = 0

    while current_date >= period_start:
        for key, value in div_accounts_dict.items():
            if value < 0:
                div_accounts_dict[key] = 0

        total_token_balance = sum(div_accounts_dict.values())
        month_full_sum += total_token_balance
        for key, value in div_accounts_dict.items():
            div_accounts_dict_month[key] += value

        if current_date == period_start:
            break

        for record in await FinanceRepository(session).async_get_operations_by_asset(
            MTLAssets.usdm_asset.code, current_date
        ):
            if record.for_account in div_accounts_dict:
                if record.operation == "account_credited":
                    div_accounts_dict[record.for_account] -= float(record.amount1)
                elif record.operation == "account_debited":
                    div_accounts_dict[record.for_account] += float(record.amount1)
                elif record.operation == "trade":
                    if record.code1 == "USDM":
                        div_accounts_dict[record.for_account] += float(record.amount1)
                    if record.code2 == "USDM":
                        div_accounts_dict[record.for_account] -= float(record.amount2)

        current_date = current_date - timedelta(days=1)

    if month_full_sum == 0:
        logger.warning("No positive balances found for the configured dividend period")
        return []

    for record in div_accounts:
        record[2] = round((div_accounts_dict_month[record[0]] / month_full_sum) * div_sum, 7)
        record[3] = record[2]

    div_accounts.sort(key=get_key_1, reverse=True)

    # Filter div_accounts, keeping only elements that satisfy the condition
    div_accounts = [record for record in div_accounts if round(record[2], 5) > 0]

    if test_for_address:
        # Find record for test address
        test_account_data = next((record for record in div_accounts if record[0] == test_for_address), None)
        if test_account_data:
            return [test_account_data]  # Return only test address data
        return []  # If address not found
    else:
        # Standard DB save only if not a test calculation
        payments = [
            TPayments(user_key=item[0], mtl_sum=item[1], user_calc=item[2], user_div=item[3], id_div_list=item[4])
            for item in div_accounts
        ]
        session.add_all(payments)
        await session.commit()
        return div_accounts


@safe_catch_async
async def cmd_calc_usdm_sum() -> float:
    """
    Calculate daily USDM dividend sum from monthly allocation.

    Returns:
        Daily dividend sum as float
    """
    today = datetime.now(timezone.utc).date()
    if today.day >= 10:
        target_month = today.month
        target_year = today.year
    else:
        if today.month == 1:
            target_month = 12
            target_year = today.year - 1
        else:
            target_month = today.month - 1
            target_year = today.year

    key = f"next_divs_{target_month}"
    _, data = await get_balances(MTLAddresses.public_usdm, return_data=True)

    if not data or key not in data:
        raise ValueError(f"Dividend data '{key}' not found")

    value_str = decode_data_value(data[key])
    try:
        monthly_sum = Decimal(value_str)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse dividend sum '{value_str}' for {key}") from exc

    days_in_month = calendar.monthrange(target_year, target_month)[1]
    daily_sum = (monthly_sum / Decimal(days_in_month)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return float(daily_sum)


@safe_catch_async
async def cmd_calc_usdm_daily(
    session: AsyncSession, div_list_id: int, test_sum: int = 0, test_for_address: Optional[str] = None
) -> list:
    """
    Calculate daily USDM distributions to USDM holders.

    Args:
        session: Database session
        div_list_id: Dividend list ID
        test_sum: Optional fixed amount for testing (0 = use calculated daily sum)
        test_for_address: Optional address to calculate for (returns only that address)

    Returns:
        List of [address, balance, calc_div, final_div, list_id] lists
    """
    div_accounts = []
    if test_sum > 0:
        div_sum = test_sum
    else:
        div_sum = await cmd_calc_usdm_sum()

    if div_sum > 100:
        logger.info(f"div_sum = {div_sum}")
        raise ValueError("Dividend sum too high")

    accounts = await stellar_get_holders(MTLAssets.usdm_asset)
    pools = await get_liquidity_pools_for_asset(MTLAssets.usdm_asset)
    total_calc_sum = 0

    for account in accounts:
        balances = account["balances"]
        token_balance = 0
        for balance in balances:
            if (
                balance["asset_type"] == "credit_alphanum4"
                and balance["asset_code"] == MTLAssets.usdm_asset.code
                and balance["asset_issuer"] == MTLAssets.usdm_asset.issuer
            ):
                token_balance += float(balance["balance"])
            elif balance["asset_type"] == "liquidity_pool_shares":
                pool_id = balance["liquidity_pool_id"]
                pool_share = float(balance["balance"])
                for pool in pools:
                    if pool["id"] == pool_id:
                        usdm_amount = float(
                            pool["reserves_dict"].get(MTLAssets.usdm_asset.code + ":" + MTLAssets.usdm_asset.issuer, 0)
                        )
                        total_shares = float(pool["total_shares"])
                        if total_shares > 0 and pool_share > 0:
                            token_balance += (pool_share / total_shares) * usdm_amount

        div_accounts.append([account["account_id"], token_balance, 0, 0, div_list_id])
        total_calc_sum += token_balance

    if total_calc_sum <= 0:
        logger.warning("No positive USDM balances found for daily dividend calculation")
        return []

    for record in div_accounts:
        share = record[1] / total_calc_sum
        record[2] = round(share * div_sum, 7)
        record[3] = record[2]

    div_accounts.sort(key=get_key_1, reverse=True)

    # Filter div_accounts, keeping only elements that satisfy the condition
    div_accounts = [record for record in div_accounts if round(record[2], 5) > 0]

    if test_for_address:
        # Find record for test address
        test_account_data = next((record for record in div_accounts if record[0] == test_for_address), None)
        if test_account_data:
            return [test_account_data]  # Return only test address data
        return []  # If address not found
    else:
        # Standard DB save only if not a test calculation
        payments = [
            TPayments(user_key=item[0], mtl_sum=item[1], user_calc=item[2], user_div=item[3], id_div_list=item[4])
            for item in div_accounts
        ]
        session.add_all(payments)
        await session.commit()
        return div_accounts


async def cmd_gen_xdr(session: AsyncSession, list_id: int) -> int:
    """
    Generate XDR for batch dividend payments.

    Args:
        session: Database session
        list_id: Dividend list ID to generate XDR for

    Returns:
        Number of remaining unpacked payments
    """
    div_list = await FinanceRepository(session).async_get_div_list(list_id)
    if div_list is None:
        raise ValueError(f"Dividend list {list_id} not found")
    memo = div_list.memo
    pay_type = div_list.pay_type
    server = get_server()
    div_account, asset = None, None

    if pay_type == 0:
        div_account = server.load_account(MTLAddresses.public_div)
        asset = MTLAssets.eurmtl_asset

    if pay_type == 1:
        div_account = server.load_account(MTLAddresses.public_bod_eur)
        asset = MTLAssets.eurmtl_asset

    if pay_type == 4:
        div_account = server.load_account(MTLAddresses.public_div)
        asset = MTLAssets.satsmtl_asset

    if pay_type == 5:
        div_account = server.load_account(MTLAddresses.public_div)
        asset = MTLAssets.usdm_asset

    if pay_type == 6:
        div_account = server.load_account(MTLAddresses.public_usdm_div)
        asset = MTLAssets.usdm_asset

    transaction = TransactionBuilder(
        source_account=div_account, network_passphrase=get_network_passphrase(), base_fee=BASE_FEE
    )
    transaction.set_timeout(60 * 60 * 24 * 7)

    for payment in await FinanceRepository(session).async_get_payments(list_id, PACK_COUNT):
        if round(payment.user_div, 7) > 0:
            transaction.append_payment_op(
                destination=payment.user_key, amount=str(round(payment.user_div, 7)), asset=asset
            )
        payment.was_packed = 1
    await session.commit()

    transaction.add_text_memo(memo)
    transaction = transaction.build()
    xdr = transaction.to_xdr()

    session.add(TTransaction(xdr=xdr, id_div_list=list_id, xdr_id=0))
    await session.commit()
    need = await FinanceRepository(session).async_count_unpacked_payments(list_id)
    return need


async def cmd_send_by_list_id(session: AsyncSession, list_id: int) -> int:
    """
    Send all pending payments for a dividend list.

    Args:
        session: Database session
        list_id: Dividend list ID to send payments for

    Returns:
        Number of remaining unsent transactions
    """
    for db_transaction in await FinanceRepository(session).async_load_transactions(list_id):
        transaction = TransactionEnvelope.from_xdr(db_transaction.xdr, network_passphrase=get_network_passphrase())
        div_account = await load_account_async(transaction.transaction.source.account_id)
        sequence = div_account.sequence + 1
        transaction.transaction.sequence = sequence
        transaction.sign(config.private_sign.get_secret_value())
        transaction_resp = await stellar_async_submit(transaction.to_xdr())
        logger.info(transaction_resp)
        db_transaction.was_send = 1
        db_transaction.xdr_id = sequence
    await session.commit()

    return await FinanceRepository(session).async_count_unsent_transactions(list_id)
