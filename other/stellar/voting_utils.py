# other/stellar/voting_utils.py
"""Voting and governance utilities for MTL ecosystem."""

import math
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from loguru import logger
from stellar_sdk import Account, TransactionBuilder

from .sdk_utils import load_account_async, get_network_passphrase, get_server_async
from other.grist_tools import MTLGrist, grist_manager
from other.web_tools import http_session_manager
from other.mytypes import MyShareHolder

from .constants import BASE_FEE, MTLAddresses, MTLAssets
from .balance_utils import stellar_get_account, stellar_get_all_mtl_holders, stellar_get_holders
from .xdr_utils import decode_data_value

# Upper bound for operations inside a single vote transaction.
MAX_VOTE_OPERATIONS = 80


@dataclass
class VoteXdrResult:
    """Outcome of building vote-update XDR.

    Attributes:
        xdr: transaction XDR or ``None`` when nothing had to be changed.
        updated: accounts that got at least one operation.
        skipped: accounts that were already in the desired state.
    """

    xdr: str | None = None
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


async def cmd_get_blacklist() -> dict:
    """
    Fetch the MTL blacklist from GitHub.

    Returns:
        Dictionary of blacklisted addresses
    """
    response = await http_session_manager.get_web_request(
        "GET", url="https://raw.githubusercontent.com/montelibero-org/mtl/main/json/blacklist.json", return_type="json"
    )
    if isinstance(response.data, dict):
        return response.data
    raise ValueError("Invalid blacklist response format")


def check_mtla_delegate(account: str, result: dict, delegated_list: list = None):
    """
    Recursively check and resolve MTLA delegation chains.

    Args:
        account: Account ID to check
        result: Dictionary of all accounts and their delegation info
        delegated_list: List of accounts in current delegation chain (for cycle detection)

    Returns:
        Final delegate account ID or None
    """
    if delegated_list is None:
        delegated_list = []
    delegate_to_account = result[account]["delegate"]
    # Remove self-delegation cycle
    if delegate_to_account and delegate_to_account == account:
        result[account]["delegate"] = None
        return

    # Remove larger delegation cycle
    if delegate_to_account and delegate_to_account in delegated_list:
        result[account]["delegate"] = None
        return

    if delegate_to_account:
        if result[account]["vote"] > 0:
            delegated_list.append(account)
        if result[delegate_to_account]["delegate"]:
            result[account]["was_delegate"] = check_mtla_delegate(delegate_to_account, result, delegated_list)
        else:
            if "delegated_list" in result[delegate_to_account]:
                result[delegate_to_account]["delegated_list"].extend(delegated_list)
            else:
                result[delegate_to_account]["delegated_list"] = delegated_list
            result[account]["was_delegate"] = delegate_to_account
            return delegate_to_account


def apply_mtl_delegations(
    shareholder_list: list[MyShareHolder],
    delegate_list: dict[str, str],
    blacklist: dict[str, object],
) -> None:
    """Apply MTL delegations while treating blacklist entries as sinks."""
    blacklisted_accounts = {account_id for account_id, blocked in blacklist.items() if blocked}

    for shareholder in shareholder_list:
        account_id = shareholder.account_id
        visited: set[str] = set()

        while account_id not in visited:
            if account_id in blacklisted_accounts:
                shareholder.balance_mtl = 0
                shareholder.balance_rect = 0
                shareholder.balance_delegated = 0
                break

            visited.add(account_id)
            delegate_id = delegate_list.get(account_id)
            if not delegate_id:
                break
            account_id = delegate_id

    # Preserve the existing three-pass behavior for valid delegation chains.
    for _ in range(3):
        changes_made = False

        for shareholder in shareholder_list:
            delegate_id = delegate_list.get(shareholder.account_id)
            if not delegate_id:
                continue

            delegate = next((item for item in shareholder_list if item.account_id == delegate_id), None)
            if delegate:
                delegate.balance_delegated += shareholder.balance
                shareholder.balance_delegated = 0
                shareholder.balance_mtl = 0
                shareholder.balance_rect = 0
                changes_made = True

        if not changes_made:
            break


async def cmd_get_new_vote_all_mtl(public_key: str, remove_master: bool = False) -> "VoteXdrResult":
    """
    Generate voting XDR transactions for MTL accounts.

    If public_key is a full Stellar address (>10 chars), generates XDR for that single account.
    Otherwise, generates XDR for all multisp accounts from Grist.

    Accounts that already have the desired signers/thresholds/master weight are
    skipped: no operations are emitted for them (previously every account got an
    empty SetOptions, which asked the multisig to sign a no-op).

    Args:
        public_key: Stellar public key or short identifier
        remove_master: Whether to remove master key weight

    Returns:
        VoteXdrResult with the XDR (None when nothing changed) and the account lists
    """
    vote_list = await cmd_gen_mtl_vote_list()
    if len(public_key) > 10:
        xdr = await gen_vote_xdr(public_key, vote_list, remove_master=remove_master, source=public_key)
        if xdr:
            return VoteXdrResult(xdr=xdr, updated=[public_key])
        return VoteXdrResult(xdr=None, skipped=[public_key])

    accounts = await grist_manager.load_table_data(MTLGrist.EURMTL_accounts, filter_dict={"signers_type": ["multisp"]})

    updated: list[str] = []
    skipped: list[str] = []
    xdr: str | None = None
    source_account = await load_account_async(MTLAddresses.public_issuer)
    transaction = TransactionBuilder(
        source_account=source_account, network_passphrase=get_network_passphrase(), base_fee=BASE_FEE
    )
    sequence = transaction.source_account.sequence
    transaction.set_timeout(60 * 60 * 24 * 7)
    for account in accounts:
        account_id = account["account_id"]
        if len(transaction.operations) >= MAX_VOTE_OPERATIONS:
            logger.warning(
                "vote xdr: operation limit {} reached, {} accounts left out",
                MAX_VOTE_OPERATIONS,
                len(accounts) - len(updated) - len(skipped),
            )
            skipped.extend(row["account_id"] for row in accounts[len(updated) + len(skipped) :])
            break
        vote_list_copy = deepcopy(vote_list)
        # return sequence because every build inc number
        transaction.source_account.sequence = sequence
        account_xdr = await gen_vote_xdr(account_id, vote_list_copy, transaction, source=account_id, remove_master=True)
        if account_xdr:
            updated.append(account_id)
            xdr = account_xdr
        else:
            skipped.append(account_id)
            logger.debug("vote xdr: {} already up to date, skipped", account_id)

    return VoteXdrResult(xdr=xdr, updated=updated, skipped=skipped)


def is_vote_distribution_within_limit(weights: list[int], max_share: float = 0.40) -> bool:
    """Return whether the largest vote weight is within the allowed share."""
    total_weight = sum(weights)
    if total_weight == 0:
        return True
    return max(weights) / total_weight <= max_share


def normalize_vote_weights(
    balances: list[float],
    target_min: float = 0.33,
    target_max: float = 0.40,
) -> list[int]:
    """Limit a dominant holder while preserving already-safe distributions.

    Returns proportional integer weights unchanged when the largest holder is
    already at or below ``target_max``. Otherwise, uses binary search to find a
    power-law exponent that moves the largest share close to ``target_min``.

    Args:
        balances: Non-empty list of balances sorted descending. Must contain at
            least one positive value.
        target_min: Target share for a holder that requires normalization (0-1).
        target_max: Maximum share allowed before normalization is applied (0-1).

    Returns:
        List of integer vote weights (same length as *balances*).
    """
    total_sum = sum(balances)
    if total_sum == 0:
        return [0] * len(balances)

    base_votes = [math.ceil(b * 100 / total_sum) for b in balances]
    total_vote = sum(base_votes)
    big_vote = base_votes[0]
    if is_vote_distribution_within_limit(base_votes, target_max):
        return base_votes

    diff = (big_vote - total_vote / 3) / total_vote

    # Целимся ближе к нижней границе (33%), а не в середину (36.5%)
    target_mid = target_min + 0.005

    lo, hi = 0.0, 5.0
    best_coeff = 1.74  # fallback
    best_distance = float("inf")

    for _ in range(100):
        mid = (lo + hi) / 2
        exponent = 1 - (mid - diff) * diff
        trial = [round(bv**exponent) for bv in base_votes]
        trial_sum = sum(trial)
        if trial_sum == 0:
            hi = mid
            continue
        major_share = trial[0] / trial_sum
        distance = abs(major_share - target_mid)

        if distance < best_distance:
            best_distance = distance
            best_coeff = mid

        if major_share > target_mid:
            lo = mid
        else:
            hi = mid

    exponent = 1 - (best_coeff - diff) * diff
    return [round(bv**exponent) for bv in base_votes]


async def cmd_gen_mtl_vote_list(trim_count: int = 20, delegate_list: dict = None) -> list[MyShareHolder]:
    """
    Generate MTL signer vote list based on MTLRECT holdings.

    Calculates voting power based on token balance and delegation, applying
    normalization only when the largest holder exceeds 40% of votes.

    Args:
        trim_count: Maximum number of shareholders to return
        delegate_list: Optional pre-existing delegation mapping

    Returns:
        List of MyShareHolder objects sorted by voting power
    """
    if delegate_list is None:
        delegate_list = {}
    shareholder_list = []

    # Get current signers from issuer account
    source_account = await load_account_async(MTLAddresses.public_issuer)
    sg = source_account.load_ed25519_public_key_signers()

    # Create dictionary for quick signer lookup
    signer_weights = {s.account_id: s.weight for s in sg}

    accounts = await stellar_get_all_mtl_holders()

    # mtl
    for account in accounts:
        balances = account["balances"]
        balance_mtl = 0  # no votes from 2025
        balance_rect = 0

        for balance in balances:
            if balance["asset_type"][0:15] == "credit_alphanum":
                if balance["asset_code"] == "MTLRECT" and balance["asset_issuer"] == MTLAddresses.public_issuer:
                    balance_rect = int(float(balance["balance"]))

        account_id = account["account_id"]
        if account_id != MTLAddresses.public_issuer:
            # Set votes from signer weights
            votes = signer_weights.get(account_id, 0)

            shareholder = MyShareHolder(
                account_id=account_id,
                balance_mtl=balance_mtl,
                balance_rect=balance_rect,
                data=account.get("data"),
                votes=votes,
            )
            shareholder_list.append(shareholder)

    # Add signers that are not in shareholder_list but have weight > 0
    existing_account_ids = {sh.account_id for sh in shareholder_list}
    for signer_id, weight in signer_weights.items():
        if weight > 0 and signer_id not in existing_account_ids:
            shareholder = MyShareHolder(account_id=signer_id, balance_mtl=0, balance_rect=0, votes=weight)
            shareholder_list.append(shareholder)

    # Filter shareholder_list, keeping only accounts with balance >= 1
    shareholder_list = [sh for sh in shareholder_list if sh.balance >= 1]

    # Sort shareholder_list by balance descending
    shareholder_list.sort(key=lambda sh: sh.balance, reverse=True)

    # Find delegate
    for shareholder in shareholder_list:
        if shareholder.data:
            data = shareholder.data
            for data_name in list(data):
                data_value = data[data_name]
                if data_name in ("delegate", "mtl_delegate"):
                    delegate_list[shareholder.account_id] = decode_data_value(data_value)

    blacklist = await cmd_get_blacklist()
    apply_mtl_delegations(shareholder_list, delegate_list, blacklist)

    # Sort shareholder_list by balance descending
    shareholder_list.sort(key=lambda sh: sh.balance, reverse=True)

    # Filter participants with MTLRECT balance >= 500 for vote calculation
    eligible_shareholders = [sh for sh in shareholder_list if sh.balance_rect >= 500]

    if eligible_shareholders:
        balances = [sh.balance for sh in eligible_shareholders]
        vote_weights = normalize_vote_weights(balances, target_min=0.33, target_max=0.40)

        for i, account in enumerate(eligible_shareholders):
            account.calculated_votes = vote_weights[i]

        total_calculated = sum(vote_weights)
        major_percent = vote_weights[0] / total_calculated * 100 if total_calculated else 0

        if not is_vote_distribution_within_limit(vote_weights, max_share=0.40):
            logger.warning(f"Could not fit into 33-40% range, got {major_percent:.2f}%")
            # Add warning entry to the end of shareholder_list so it appears in the report table
            warning_holder = MyShareHolder(
                account_id=f"WARNING: major={major_percent:.1f}% outside 33-40%",
                balance_mtl=0,
                balance_rect=0,
                calculated_votes=0,
            )
            shareholder_list.append(warning_holder)
        else:
            logger.info(f"Major has {major_percent:.2f}% votes")

        # Update calculated_votes in main shareholder_list
        # Create dictionary for quick lookup of calculated votes
        calculated_votes_dict = {sh.account_id: sh.calculated_votes for sh in eligible_shareholders}

        # Update calculated_votes for all participants in main list
        for shareholder in shareholder_list:
            if shareholder.account_id in calculated_votes_dict:
                shareholder.calculated_votes = calculated_votes_dict[shareholder.account_id]
            else:
                shareholder.calculated_votes = 0  # Participants without voting rights get 0

    # Double sort: first by calculated_votes, then by votes, then by balance
    shareholder_list.sort(key=lambda sh: (sh.calculated_votes, sh.votes, sh.balance), reverse=True)

    return shareholder_list[:trim_count]


async def cmd_gen_fin_vote_list(account_id: str = MTLAddresses.public_fin) -> list:
    """
    Generate FIN signer vote list based on donation history.

    Analyzes payment history to the FIN account, considering:
    - Payments in the last 365 days
    - Inactive donors (>90 days since last donation) are excluded
    - Top 10 donors get voting power based on log2 of normalized donations

    Args:
        account_id: The FIN account to analyze donations to

    Returns:
        List of [donor_id, total_sum, votes, 0, last_donation_date]
    """
    delegate_key = "tfm_delegate"
    days_to_track = 365
    days_inactive = 90
    top_donors = 10
    coefficients = [12, 5]

    # Step 1
    now = datetime.now()
    one_year_ago = now - timedelta(days=days_to_track)

    donor_dict = {}

    async with get_server_async() as server:
        payments_call_builder = server.payments().for_account(account_id).order(desc=True)
        page_records = await payments_call_builder.call()

        while page_records["_embedded"]["records"]:
            for payment in page_records["_embedded"]["records"]:
                if (
                    payment.get("to")
                    and payment["to"] == account_id
                    and datetime.strptime(payment["created_at"], "%Y-%m-%dT%H:%M:%SZ") > one_year_ago
                ):
                    amount = float(payment["amount"])
                    last_donation_date = datetime.strptime(payment["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                    if payment["from"] not in donor_dict:
                        donor_dict[payment["from"]] = {"sum": amount, "date": last_donation_date}
                    else:
                        donor_dict[payment["from"]]["sum"] += amount
                        if last_donation_date > donor_dict[payment["from"]]["date"]:
                            donor_dict[payment["from"]]["date"] = last_donation_date
            page_records = await payments_call_builder.next()

        # Step 3
        ninety_days_ago = now - timedelta(days=days_inactive)
        for donor, data in list(donor_dict.items()):
            if data["date"] < ninety_days_ago:
                donor_dict.pop(donor)

        # Step 4 and 5
        for donor, data in donor_dict.items():
            account_data = await server.accounts().account_id(donor).call()
            delegate_data = account_data["data"]
            if delegate_key in delegate_data:
                delegate_id = delegate_data[delegate_key]
                payment_amount = data["sum"]
                payment_date = data["date"]

                if delegate_id in donor_dict:
                    donor_dict[delegate_id]["sum"] += payment_amount
                    if payment_date > donor_dict[delegate_id]["date"]:
                        donor_dict[delegate_id]["date"] = payment_date

        # Step 6
        sorted_donors = sorted(donor_dict.items(), key=lambda x: (x[1]["sum"], x[1]["date"]), reverse=True)

        # Step 7
        top_sorted_donors = sorted_donors[:top_donors]

        # Step 8
        final_list = []
        for donor, data in top_sorted_donors:
            sum_of_payments = data["sum"]
            for coeff in coefficients:
                sum_of_payments /= coeff
            votes = math.log2(sum_of_payments)
            final_list.append([donor, data["sum"], int(votes), 0, data["date"]])

    return final_list


async def gen_vote_xdr(
    public_key: str,
    vote_list: list[MyShareHolder],
    transaction: TransactionBuilder = None,
    source: str = None,
    remove_master: bool = False,
    max_count: int = 20,
    threshold_style: int = 0,
) -> str | None:
    """
    Create SetOptions XDR with signers for voting.

    Updates the account's signers based on calculated voting weights and
    sets appropriate thresholds. Only real changes produce operations: signer
    weights that already match, thresholds that are already correct and a
    master weight that is already 0 do not add anything.

    Args:
        public_key: Account to update signers for
        vote_list: List of shareholders with calculated votes
        transaction: Optional existing transaction builder to append to
        source: Source account for operations
        remove_master: Whether to set master key weight to 0
        max_count: Maximum number of signers to include
        threshold_style: 0 for 50%+1 threshold, 1 for 2/3 threshold

    Returns:
        XDR transaction string, or ``None`` when the account needs no changes.
    """
    # Load signers, thresholds and sequence without blocking the event loop
    source_account = await load_account_async(public_key)

    sg = source_account.load_ed25519_public_key_signers()
    current_weights = {s.account_id: s.weight for s in sg}
    current_thresholds = (
        int(source_account.thresholds.low_threshold),
        int(source_account.thresholds.med_threshold),
        int(source_account.thresholds.high_threshold),
    )

    for s in sg:
        was_found = False
        for arr in vote_list:
            if arr.account_id == s.account_id:
                arr.votes = s.weight
                was_found = True
        if not was_found and s.account_id != public_key:
            vote_list.append(MyShareHolder(account_id=s.account_id, votes=s.weight))

    vote_list.sort(key=lambda k: k.calculated_votes, reverse=True)

    # Move users to delete to top
    tmp_list = []
    del_count = 0

    for arr in vote_list:
        if (int(arr.calculated_votes) == 0) & (int(arr.votes) > 0):
            tmp_list.append(arr)
            vote_list.remove(arr)
            del_count += 1

    tmp_list.extend(vote_list)

    while len(tmp_list) > max_count + del_count:
        arr = tmp_list.pop(max_count + del_count)
        if arr.votes > 0:
            del_count += 1
            tmp_list.insert(0, MyShareHolder(account_id=arr.account_id, votes=arr.votes))

    vote_list = tmp_list

    if transaction is None:
        root_account = Account(public_key, sequence=source_account.sequence)
        transaction = TransactionBuilder(
            source_account=root_account, network_passphrase=get_network_passphrase(), base_fee=BASE_FEE
        )
        transaction.set_timeout(60 * 60 * 24 * 7)

    changed = False
    threshold = 0

    for arr in vote_list:
        if int(arr.calculated_votes) != int(arr.votes):
            transaction.append_ed25519_public_key_signer(arr.account_id, int(arr.calculated_votes), source=source)
            changed = True
        threshold += int(arr.calculated_votes)

    if threshold_style == 1:
        threshold = threshold // 3 * 2
    else:
        threshold = threshold // 2 + 1

    thresholds_changed = (threshold, threshold, threshold) != current_thresholds
    master_needs_reset = remove_master and current_weights.get(public_key, 0) != 0

    if thresholds_changed or master_needs_reset:
        transaction.append_set_options_op(
            low_threshold=threshold,
            med_threshold=threshold,
            high_threshold=threshold,
            source=source,
            master_weight=0 if master_needs_reset else None,
        )
        changed = True

    if not changed:
        logger.debug("gen_vote_xdr: no changes for {}, nothing to sign", public_key)
        return None

    return transaction.build().to_xdr()


async def get_mtlap_votes() -> dict:
    """
    Get MTLAP governance votes with delegation resolution.

    Builds a voting tree based on MTLAP token holdings and delegation chains.
    Accounts need at least 2 MTLAP to vote or have delegators with 2+ MTLAP.

    Returns:
        Dictionary mapping account_id to voting info:
        {
            'delegate': delegate account or None,
            'vote': MTLAP balance,
            'can_vote': True if can participate in governance,
            'delegated_list': list of accounts that delegated to this one
        }
    """
    result = {}
    # Build tree based on holders
    accounts = await stellar_get_holders(MTLAssets.mtlap_asset)
    for account in accounts:
        delegate = None
        if account["data"] and account["data"].get("mtla_a_delegate"):
            delegate = decode_data_value(account["data"]["mtla_a_delegate"])
        vote = 0
        for balance in account["balances"]:
            if (
                balance.get("asset_code")
                and balance["asset_code"] == MTLAssets.mtlap_asset.code
                and balance["asset_issuer"] == MTLAssets.mtlap_asset.issuer
            ):
                vote = int(float(balance["balance"]))
                break
        result[account["id"]] = {"delegate": delegate, "vote": vote, "can_vote": vote >= 2}

    # Add accounts that don't exist yet
    find_new = True
    while find_new:
        find_new = False
        for account in list(result):
            if result[account]["delegate"] and result[account]["delegate"] not in result:
                find_new = True
                new_account = await stellar_get_account(result[account]["delegate"])
                delegate = None
                if new_account.get("data") and new_account["data"].get("mtla_a_delegate"):
                    delegate = decode_data_value(new_account["data"]["mtla_a_delegate"])
                vote = 0
                balances = new_account.get("balances")
                if balances:
                    for balance in balances:
                        if (
                            balance.get("asset_code")
                            and balance["asset_code"] == MTLAssets.mtlap_asset.code
                            and balance["asset_issuer"] == MTLAssets.mtlap_asset.issuer
                        ):
                            vote = int(float(balance["balance"]))
                            break
                result[new_account["id"]] = {"delegate": delegate, "vote": vote, "can_vote": vote >= 2}

    for account in list(result):
        check_mtla_delegate(account, result)

    # Check if account can vote
    for account in list(result):
        if not result[account]["can_vote"]:
            # Check if there are delegators with 2 or more tokens
            if "delegated_list" in result[account]:
                for delegator in result[account]["delegated_list"]:
                    if result[delegator]["vote"] >= 2:
                        result[account]["can_vote"] = True
                        break

    # Remove accounts that cannot vote
    for account in list(result):
        if not result[account]["can_vote"]:
            del result[account]

    del result["GDGC46H4MQKRW3TZTNCWUU6R2C7IPXGN7HQLZBJTNQO6TW7ZOS6MSECR"]
    del result["GCNVDZIHGX473FEI7IXCUAEXUJ4BGCKEMHF36VYP5EMS7PX2QBLAMTLA"]

    return result


async def stellar_add_mtl_holders_info(accounts: list[MyShareHolder]):
    """
    Enrich account list with signer weight information from MTL issuer.

    Updates the votes attribute of each account in the list based on
    their signer weight on the MTL issuer account.

    Args:
        accounts: List of MyShareHolder objects to update
    """
    async with get_server_async() as server:
        source_account = await server.load_account(MTLAddresses.public_issuer)
        sg = source_account.load_ed25519_public_key_signers()

    # Create dictionary for quick weight lookup by account_id
    signer_weights = {s.account_id: s.weight for s in sg}

    # Update votes for accounts based on signer weights
    for account in accounts:
        if account.account_id in signer_weights:
            account.votes = signer_weights[account.account_id]
