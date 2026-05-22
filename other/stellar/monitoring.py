# other/stellar/monitoring.py
"""Transaction monitoring utilities for Stellar operations.

Functions for checking new transactions, tracking operations, and
detecting asset-specific transactions in the MTL ecosystem.
"""

from datetime import datetime
from typing import Any, List, cast

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from stellar_sdk import Server

from .sdk_utils import get_server_async, get_horizon_url
from other.utils import float2str
from other.stellar.address_utils import address_id_to_username
from other.stellar.constants import MTLAddresses
from db.repositories import FinanceRepository
from shared.infrastructure.database.models import TOperations


async def cmd_check_new_transaction(
    ignore_operation: List, account_id: str = MTLAddresses.public_issuer, cash=None, chat_id: str | None = None
):
    """
    Check for new transactions on a Stellar account and decode them.

    Args:
        ignore_operation: List of operation types to ignore
        account_id: Stellar account to monitor
        cash: Optional cache dict to store transaction data
        chat_id: Chat ID for storing last processed transaction

    Returns:
        List of decoded transaction details
    """
    # Import here to avoid circular dependency
    from other.stellar.xdr_utils import decode_xdr
    from services.app_context import app_context

    result = []
    chat_key = str(chat_id or "")

    try:
        # Check cache first
        if cash is not None and account_id in cash:
            tr = cash[account_id]
        else:
            # Fetch from Horizon if not cached
            async with get_server_async() as server:
                tr = await server.transactions().for_account(account_id).order(desc=True).call()
            # Store in cache
            if cash is not None:
                cash[account_id] = tr

        # Get last processed transaction ID from database
        last_id = await app_context.db_service.load_kv_value(account_id + chat_key)

        # If no last_id, save current one and exit
        if last_id is None:
            if tr["_embedded"]["records"]:
                last_id = tr["_embedded"]["records"][0]["paging_token"]
                await app_context.db_service.save_kv_value(account_id + chat_key, last_id)
            return result

        new_transactions = []
        for record in tr["_embedded"]["records"]:
            if record["paging_token"] == last_id:
                break
            new_transactions.append(record)

        for transaction in new_transactions:
            if transaction["paging_token"] > last_id:
                last_id = transaction["paging_token"]
            try:
                tr = await decode_xdr(transaction["envelope_xdr"], ignore_operation=ignore_operation)
                if tr and 0 < len(tr) < 90:
                    link = f"https://viewer.eurmtl.me/transaction/{transaction['hash']}"
                    try:
                        tr_details = await decode_xdr(transaction["envelope_xdr"])
                        if tr_details:
                            tr_details.insert(0, f'(<a href="{link}">expert link</a>)')
                            result.append(tr_details)
                    except Exception as ex:
                        logger.opt(exception=True).error(
                            f"Error decoding XDR details for transaction {transaction['paging_token']}: {ex}"
                        )
                        # Add basic info if detailed decoding fails
                        result.append([f'(<a href="{link}">expert link</a>)', "Error decoding transaction details"])
            except Exception as ex:
                logger.opt(exception=True).error(f"Error processing transaction {transaction['paging_token']}: {ex}")
                continue

        await app_context.db_service.save_kv_value(account_id + chat_key, last_id)

    except Exception as ex:
        logger.opt(exception=True).error(f"Error in cmd_check_new_transaction for account {account_id}: {ex}")

    return result


async def cmd_check_new_asset_transaction(
    session: AsyncSession,
    asset: str,
    filter_sum: int = -1,
    filter_operation=None,
    filter_asset=None,
    chat_id: str | None = None,
    grist_manager=None,
):
    """
    Check for new transactions involving a specific asset.

    Args:
        session: SQLAlchemy database session
        asset: Asset code to monitor (format: "CODE-ISSUER")
        filter_sum: Minimum amount threshold
        filter_operation: List of operations to filter
        filter_asset: Specific asset to filter
        chat_id: Chat ID for storing last processed transaction
        grist_manager: Optional Grist manager for name lookups

    Returns:
        List of decoded effect details
    """
    try:
        from services.app_context import app_context

        if filter_operation is None:
            filter_operation = []
        result = []
        asset_name = asset.split("-")[0]
        chat_key = str(chat_id or "")

        # Get last processed effect ID from database
        last_id = await app_context.db_service.load_kv_value(asset + chat_key)

        # If no last_id, save current one and exit
        if last_id is None:
            # Get data to determine current max_id
            data = await FinanceRepository(session).async_get_new_effects_for_token(asset_name, "-1", filter_sum)
            if data:
                # Save last effect ID as initial last_id
                await app_context.db_service.save_kv_value(asset + chat_key, data[-1].id)
            return result

        max_id = last_id

        # Get new effects for token
        data = await FinanceRepository(session).async_get_new_effects_for_token(asset_name, last_id, filter_sum)
        for row in data:
            try:
                effect = await _decode_db_effect(row, grist_manager=grist_manager)
                if effect:  # Check effect is not empty
                    result.append(effect)
                    max_id = row.id
            except Exception as ex:
                logger.opt(exception=True).error(f"Error decoding effect for row {row.id}: {ex}")
                continue

        # Save new max_id if it's greater than last_id
        if max_id > last_id:
            await app_context.db_service.save_kv_value(asset + chat_key, max_id)

        return result

    except Exception as ex:
        logger.opt(exception=True).error(f"Error in cmd_check_new_asset_transaction for asset {asset}: {ex}")
        return []


async def _decode_db_effect(row: TOperations, grist_manager=None):
    """
    Decode a database effect row into human-readable format.

    Args:
        row: TOperations database row
        grist_manager: Optional Grist manager for name lookups

    Returns:
        Formatted string describing the operation
    """
    try:
        row_any = cast(Any, row)
        result = (
            f'<a href="https://viewer.eurmtl.me/operation/{row_any.id.split("-")[0]}">'
            f"Операция</a> с аккаунта {await address_id_to_username(row_any.for_account, full_data=True, grist_manager=grist_manager)} \n"
        )
        if row_any.operation == "trade":
            result += f"  {row_any.operation}  {float2str(row_any.amount1)} {row_any.code1} for {float2str(row_any.amount2)} {row_any.code2} \n"
        else:
            result += f"  {row_any.operation} for {float2str(row_any.amount1)} {row_any.code1} \n"
        return result
    except Exception as ex:
        logger.opt(exception=True).error(f"Error in _decode_db_effect for operation {cast(Any, row).id}: {ex}")
        return None


def cmd_check_last_operation(address: str, filter_operation=None) -> datetime:
    """
    Get the timestamp of the last operation on a Stellar account.

    Args:
        address: Stellar account address
        filter_operation: Optional operation filter (currently unused)

    Returns:
        datetime of the last operation
    """
    operations = Server(horizon_url=get_horizon_url()).operations().for_account(address).order().limit(1).call()
    op = operations["_embedded"]["records"][0]
    dt = datetime.strptime(op["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    return dt


def get_memo_by_op(op: str):
    """
    Get the memo text from a transaction by operation ID.

    Args:
        op: Operation ID

    Returns:
        Memo text or 'None' if no memo
    """
    operation = Server(horizon_url=get_horizon_url()).operations().operation(op).call()
    transaction = Server(horizon_url=get_horizon_url()).transactions().transaction(operation["transaction_hash"]).call()
    return transaction.get("memo", "None")


async def stellar_get_transactions(address, start_range, end_range):
    """
    Fetch transactions for an address within a date range.

    Args:
        address: Stellar account address
        start_range: Start datetime for the range
        end_range: End datetime for the range

    Returns:
        List of transaction records within the specified date range
    """
    transactions = []
    async with get_server_async() as server:
        # Start fetching transaction pages
        payments_call_builder = server.payments().for_account(account_id=address).limit(200).order()
        page_records = await payments_call_builder.call()
        while page_records["_embedded"]["records"]:
            # Check each transaction against date range
            for record in page_records["_embedded"]["records"]:
                tx_date = datetime.strptime(record["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                if tx_date < start_range:
                    # If transaction date is before start range, stop fetching
                    return transactions
                if start_range.date() <= tx_date.date() <= end_range.date():
                    transactions.append(record)
            # Get next page
            page_records = await payments_call_builder.next()

    return transactions
