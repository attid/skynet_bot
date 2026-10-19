# other/stellar/xdr_utils.py
"""XDR and transaction utility functions for Stellar blockchain."""

import base64
from typing import List, Optional

from loguru import logger
from stellar_sdk import (
    Account,
    Network,
    TextMemo,
    TransactionBuilder,
    TransactionEnvelope,
    FeeBumpTransactionEnvelope,
)
from stellar_sdk.client.aiohttp_client import AiohttpClient
from stellar_sdk.server_async import ServerAsync

from other.config_reader import config
from other.web_tools import get_eurmtl_xdr
from .address_utils import address_id_to_username

# Operation types that carry meaningful amounts and can be filtered by filter_sum.
# When filter_sum > 0, operations NOT in this set are skipped entirely.
AMOUNT_OPERATIONS = {
    "Payment",
    "ManageSellOffer",
    "ManageBuyOffer",
    "PathPaymentStrictSend",
    "PathPaymentStrictReceive",
    "CreatePassiveSellOffer",
    "Clawback",
}


def good_operation(operation, operation_name: str, filter_operation: list, ignore_operation: list) -> bool:
    """
    Check if operation matches filter criteria.

    Args:
        operation: Stellar operation object
        operation_name: Name of operation type to check
        filter_operation: List of operation names to include (empty means all)
        ignore_operation: List of operation names to exclude

    Returns:
        True if operation should be processed
    """
    if operation_name in ignore_operation:
        return False
    elif type(operation).__name__ == operation_name:
        return (not filter_operation) or (operation_name in filter_operation)
    return False


async def check_url_xdr(url: str, full_data: bool = True, grist_manager=None, global_data=None) -> List[str]:
    """
    Fetch XDR from URL and decode it.

    Args:
        url: URL to fetch XDR from (e.g., eurmtl.me transaction page)
        full_data: Whether to include full address lookups
        grist_manager: Optional Grist manager for address lookups
        global_data: Optional global data for name list cache

    Returns:
        List of decoded operation descriptions
    """
    xdr = await get_eurmtl_xdr(url)
    logger.debug("check_url_xdr: url={} xdr_len={} full_data={}", url, len(xdr or ""), full_data)
    return await decode_xdr(xdr, full_data=full_data, grist_manager=grist_manager, global_data=global_data)


async def decode_xdr(
    xdr: str,
    filter_sum: int = -1,
    filter_operation: Optional[List[str]] = None,
    ignore_operation: Optional[List[str]] = None,
    filter_asset=None,
    full_data: bool = False,
    grist_manager=None,
    global_data=None,
    filter_account: Optional[str] = None,
) -> List[str]:
    """
    Decode XDR and explain its operations in human-readable format.

    Args:
        xdr: Transaction XDR string
        filter_sum: Minimum amount to include (use -1 for all)
        filter_operation: List of operation types to include (None for all)
        ignore_operation: List of operation types to exclude
        filter_asset: Asset to filter for (None for all)
        full_data: Whether to perform full address lookups
        grist_manager: Optional Grist manager for address lookups
        global_data: Optional global data for name list cache

    Returns:
        List of operation descriptions (Russian language)
    """
    if ignore_operation is None:
        ignore_operation = []
    if filter_operation is None:
        filter_operation = []
    result = []
    data_exist = False

    if FeeBumpTransactionEnvelope.is_fee_bump_transaction_envelope(xdr):
        fee_transaction = FeeBumpTransactionEnvelope.from_xdr(xdr, network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE)
        transaction = fee_transaction.transaction.inner_transaction_envelope
    else:
        transaction = TransactionEnvelope.from_xdr(xdr, network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE)

    tx_source_id = transaction.transaction.source.account_id

    # Skip mass transactions (e.g. airdrop-style 50+ operations) unless the tx was
    # initiated by the monitored account (filter_account).
    if (
        "MASS" in ignore_operation
        and len(transaction.transaction.operations) >= 50
        and (not filter_account or tx_source_id != filter_account)
    ):
        return []

    # If filter_account is the tx source, show all operations (no per-op filtering needed)
    filter_ops_by_account = filter_account and tx_source_id != filter_account

    source_name = await address_id_to_username(
        tx_source_id, full_data=full_data, grist_manager=grist_manager, global_data=global_data
    )
    result.append(f"Операции с аккаунта {source_name}")

    if transaction.transaction.memo.__class__ == TextMemo:
        memo = transaction.transaction.memo
        result.append(f'  Memo "{memo.memo_text.decode()}"\n')
    result.append(f"  Всего {len(transaction.transaction.operations)} операций\n")

    for idx, operation in enumerate(transaction.transaction.operations):
        # When filter_sum is active, skip operations without meaningful amounts
        if filter_sum > 0 and type(operation).__name__ not in AMOUNT_OPERATIONS:
            continue

        # When filter_account is set and tx source is different,
        # only show operations where filter_account is directly involved
        if filter_ops_by_account:
            op_source_id = operation.source.account_id if operation.source else tx_source_id
            op_accounts = {op_source_id}
            if hasattr(operation, "destination"):
                dest = operation.destination
                if hasattr(dest, "account_id"):
                    op_accounts.add(dest.account_id)
                elif isinstance(dest, str):
                    op_accounts.add(dest)
            if hasattr(operation, "from_") and operation.from_:
                op_accounts.add(operation.from_.account_id)
            if hasattr(operation, "trustor") and operation.trustor:
                op_accounts.add(operation.trustor)
            if filter_account not in op_accounts:
                continue

        result.append(f"Операция {idx} - {type(operation).__name__}")
        if operation.source:
            op_source_name = await address_id_to_username(
                operation.source.account_id, full_data=full_data, grist_manager=grist_manager, global_data=global_data
            )
            result.append(f"*** для аккаунта {op_source_name}")

        if good_operation(operation, "Payment", filter_operation, ignore_operation):
            if "SPAM" in ignore_operation and operation.asset.code == "XLM" and operation.amount < "0.1":
                continue
            if float(operation.amount) > filter_sum:
                if (filter_asset is None) or (operation.asset == filter_asset):
                    data_exist = True
                    dest_name = await address_id_to_username(
                        operation.destination.account_id,
                        full_data=full_data,
                        grist_manager=grist_manager,
                        global_data=global_data,
                    )
                    result.append(f"    Перевод {operation.amount} {operation.asset.code} на аккаунт {dest_name}")
            continue

        if good_operation(operation, "SetOptions", filter_operation, ignore_operation):
            data_exist = True
            if operation.signer:
                signer_name = await address_id_to_username(
                    operation.signer.signer_key.encoded_signer_key,
                    full_data=full_data,
                    grist_manager=grist_manager,
                    global_data=global_data,
                )
                result.append(f"    Изменяем подписанта {signer_name} новые голоса : {operation.signer.weight}")
            if operation.med_threshold:
                data_exist = True
                result.append(f"Установка нового требования. Нужно будет {operation.med_threshold} голосов")
            if operation.home_domain:
                data_exist = True
                result.append(f"Установка нового домена {operation.home_domain}")
            continue

        if good_operation(operation, "ChangeTrust", filter_operation, ignore_operation):
            data_exist = True
            if operation.asset.type == "liquidity_pool_shares":
                if operation.limit == "0":
                    result.append(
                        f"    Закрываем линию доверия к пулу {operation.asset.asset_a.code}/{operation.asset.asset_b.code}"
                    )
                else:
                    result.append(
                        f"    Открываем линию доверия к пулу {operation.asset.asset_a.code}/{operation.asset.asset_b.code}"
                    )
            else:
                issuer_name = await address_id_to_username(
                    operation.asset.issuer, full_data=full_data, grist_manager=grist_manager, global_data=global_data
                )
                if operation.limit == "0":
                    result.append(
                        f"    Закрываем линию доверия к токену {operation.asset.code} от аккаунта {issuer_name}"
                    )
                else:
                    result.append(
                        f"    Открываем линию доверия к токену {operation.asset.code} от аккаунта {issuer_name}"
                    )
            continue

        if good_operation(operation, "CreateClaimableBalance", filter_operation, ignore_operation):
            data_exist = True
            result.append(f"  Спам {operation.asset.code}")
            result.append("  Остальные операции игнорируются.")
            break

        if good_operation(operation, "ManageSellOffer", filter_operation, ignore_operation):
            if float(operation.amount) > filter_sum:
                data_exist = True
                result.append(
                    f"    Офер на продажу {operation.amount} {operation.selling.code} по цене {operation.price.n / operation.price.d} {operation.buying.code}"
                )
            continue

        if good_operation(operation, "CreatePassiveSellOffer", filter_operation, ignore_operation):
            if float(operation.amount) > filter_sum:
                data_exist = True
                result.append(
                    f"    Пассивный офер на продажу {operation.amount} {operation.selling.code} по цене {operation.price.n / operation.price.d} {operation.buying.code}"
                )
            continue

        if good_operation(operation, "ManageBuyOffer", filter_operation, ignore_operation):
            if float(operation.amount) > filter_sum:
                data_exist = True
                result.append(
                    f"    Офер на покупку {operation.amount} {operation.buying.code} по цене {operation.price.n / operation.price.d} {operation.selling.code}"
                )
            continue

        if good_operation(operation, "PathPaymentStrictSend", filter_operation, ignore_operation):
            if (float(operation.dest_min) > filter_sum) and (float(operation.send_amount) > filter_sum):
                if (filter_asset is None) or (filter_asset in [operation.send_asset, operation.dest_asset]):
                    data_exist = True
                    dest_name = await address_id_to_username(
                        operation.destination.account_id,
                        full_data=full_data,
                        grist_manager=grist_manager,
                        global_data=global_data,
                    )
                    result.append(
                        f"    Покупка {dest_name}, шлем {operation.send_asset.code} {operation.send_amount} в обмен на {operation.dest_asset.code} min {operation.dest_min} "
                    )
            continue

        if good_operation(operation, "PathPaymentStrictReceive", filter_operation, ignore_operation):
            if (float(operation.send_max) > filter_sum) and (float(operation.dest_amount) > filter_sum):
                if (filter_asset is None) or (filter_asset in [operation.send_asset, operation.dest_asset]):
                    data_exist = True
                    dest_name = await address_id_to_username(
                        operation.destination.account_id,
                        full_data=full_data,
                        grist_manager=grist_manager,
                        global_data=global_data,
                    )
                    result.append(
                        f"    Продажа {dest_name}, Получаем {operation.send_asset.code} max {operation.send_max} в обмен на {operation.dest_asset.code} {operation.dest_amount} "
                    )
            continue

        if good_operation(operation, "ManageData", filter_operation, ignore_operation):
            data_exist = True
            result.append(f"    ManageData {operation.data_name} = {operation.data_value} ")
            continue

        if good_operation(operation, "SetTrustLineFlags", filter_operation, ignore_operation):
            data_exist = True
            trustor_name = await address_id_to_username(
                operation.trustor, full_data=full_data, grist_manager=grist_manager, global_data=global_data
            )
            result.append(f"    Trustor {trustor_name} for asset {operation.asset.code}")
            if operation.clear_flags is not None:
                result.append(f"    Clear flags: {operation.clear_flags}")
            if operation.set_flags is not None:
                result.append(f"    Set flags: {operation.set_flags}")
            continue

        if good_operation(operation, "CreateAccount", filter_operation, ignore_operation):
            data_exist = True
            dest_name = await address_id_to_username(
                operation.destination, full_data=full_data, grist_manager=grist_manager, global_data=global_data
            )
            result.append(f"    Создание аккаунта {dest_name} с суммой {operation.starting_balance} XLM")
            continue

        if good_operation(operation, "AccountMerge", filter_operation, ignore_operation):
            data_exist = True
            dest_name = await address_id_to_username(
                operation.destination.account_id,
                full_data=full_data,
                grist_manager=grist_manager,
                global_data=global_data,
            )
            result.append(f"    Слияние аккаунта c {dest_name} ")
            continue

        if good_operation(operation, "ClaimClaimableBalance", filter_operation, ignore_operation):
            data_exist = True
            balance_name = await address_id_to_username(
                operation.balance_id, full_data=full_data, grist_manager=grist_manager, global_data=global_data
            )
            result.append(f"    ClaimClaimableBalance {balance_name}")
            continue

        if good_operation(operation, "BeginSponsoringFutureReserves", filter_operation, ignore_operation):
            data_exist = True
            sponsored_name = await address_id_to_username(
                operation.sponsored_id, full_data=full_data, grist_manager=grist_manager, global_data=global_data
            )
            result.append(f"    BeginSponsoringFutureReserves {sponsored_name}")
            continue

        if good_operation(operation, "EndSponsoringFutureReserves", filter_operation, ignore_operation):
            data_exist = True
            result.append("    EndSponsoringFutureReserves")
            continue

        if type(operation).__name__ == "Clawback":
            data_exist = True
            from_name = await address_id_to_username(
                operation.from_.account_id, full_data=full_data, grist_manager=grist_manager, global_data=global_data
            )
            result.append(f"    Возврат {operation.amount} {operation.asset.code} с аккаунта {from_name}")
            continue

        if type(operation).__name__ == "LiquidityPoolDeposit":
            data_exist = True
            min_price = operation.min_price.n / operation.min_price.d
            max_price = operation.max_price.n / operation.max_price.d
            result.append(
                f"    LiquidityPoolDeposit {operation.liquidity_pool_id} пополнение {operation.max_amount_a}/{operation.max_amount_b} ограничения цены {min_price}/{max_price}"
            )
            continue

        if type(operation).__name__ == "LiquidityPoolWithdraw":
            data_exist = True
            result.append(
                f"    LiquidityPoolWithdraw {operation.liquidity_pool_id} вывод {operation.amount} минимум {operation.min_amount_a}/{operation.min_amount_b} "
            )
            continue

        if type(operation).__name__ in [
            "PathPaymentStrictSend",
            "ManageBuyOffer",
            "ManageSellOffer",
            "AccountMerge",
            "PathPaymentStrictReceive",
            "ClaimClaimableBalance",
            "CreateAccount",
            "CreateClaimableBalance",
            "ChangeTrust",
            "SetOptions",
            "Payment",
            "ManageData",
            "BeginSponsoringFutureReserves",
            "EndSponsoringFutureReserves",
            "CreatePassiveSellOffer",
        ]:
            continue

        data_exist = True
        result.append("Прости хозяин, не понимаю")
        logger.info(["bad xdr", idx, operation])

    if data_exist:
        return result
    else:
        return []


async def cmd_check_fee() -> str:
    """
    Get current network fee range.

    Returns:
        String with fee range like "100-500"
    """
    async with ServerAsync(horizon_url=config.horizon_url, client=AiohttpClient()) as server:
        fee = await server.fee_stats().call()
    fee_charged = fee["fee_charged"]
    return fee_charged["min"] + "-" + fee_charged["max"]


def stellar_get_transaction_builder(xdr: str) -> TransactionBuilder:
    """
    Create TransactionBuilder from existing XDR.

    Useful for modifying existing transactions.

    Args:
        xdr: Transaction XDR string

    Returns:
        TransactionBuilder object that can be modified
    """
    # Convert XDR back to TransactionEnvelope
    transaction_envelope = TransactionEnvelope.from_xdr(xdr, network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE)

    # Extract existing transaction from TransactionEnvelope
    existing_transaction = transaction_envelope.transaction

    # Load source account
    source_account = Account(account=existing_transaction.source.account_id, sequence=existing_transaction.sequence - 1)

    # Create new TransactionBuilder with same source info
    transaction_builder = TransactionBuilder(
        source_account=source_account,
        network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE,
        base_fee=existing_transaction.fee,  # Keep original base fee
    )

    # Set time bounds if they were specified
    if existing_transaction.preconditions.time_bounds:
        transaction_builder.set_timeout(existing_transaction.preconditions.time_bounds.max_time)
    else:
        # If no time bounds, set unlimited time
        transaction_builder.set_timeout(0)

    # Add all existing operations from old transaction
    for op in existing_transaction.operations:
        transaction_builder.append_operation(op)

    # Return TransactionBuilder for further modifications
    return transaction_builder


def decode_data_value(data_value: str) -> str:
    """
    Decode base64-encoded data entry value.

    Args:
        data_value: Base64-encoded string

    Returns:
        Decoded string or 'decode error' on failure
    """
    try:
        base64_message = data_value
        base64_bytes = base64_message.encode("ascii")
        message_bytes = base64.b64decode(base64_bytes)
        message = message_bytes.decode("ascii")
        return message
    except Exception as ex:
        logger.info(f"decode_data_value error: {ex}")
        return "decode error"
