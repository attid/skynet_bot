# tests/other/stellar/test_voting_utils.py
"""Tests for MTL voting and delegation logic."""

from other.mytypes import MyShareHolder
import other.stellar.voting_utils as voting_utils

normalize_vote_weights = voting_utils.normalize_vote_weights


def make_shareholder(account_id: str, balance_rect: float) -> MyShareHolder:
    return MyShareHolder(account_id=account_id, balance_rect=balance_rect)


class TestApplyMtlDelegations:
    def test_blacklisted_source_cannot_delegate_balance(self):
        source = make_shareholder("GBLACKLISTED", 1_000)
        target = make_shareholder("GTARGET", 500)

        voting_utils.apply_mtl_delegations(
            [source, target],
            {source.account_id: target.account_id},
            {source.account_id: True},
        )

        assert source.balance == 0
        assert target.balance == 500
        assert target.balance_delegated == 0

    def test_delegation_to_blacklisted_target_removes_source_balance(self):
        source = make_shareholder("GSOURCE", 1_000)
        target = make_shareholder("GBLACKLISTED", 500)

        voting_utils.apply_mtl_delegations(
            [source, target],
            {source.account_id: target.account_id},
            {target.account_id: True},
        )

        assert source.balance == 0
        assert target.balance == 0

    def test_delegation_chain_with_blacklisted_account_is_a_sink(self):
        source = make_shareholder("GSOURCE", 1_000)
        intermediate = make_shareholder("GINTERMEDIATE", 700)
        blocked_target = make_shareholder("GBLACKLISTED", 500)
        final_target = make_shareholder("GFINAL", 900)
        delegations = {
            source.account_id: intermediate.account_id,
            intermediate.account_id: blocked_target.account_id,
            blocked_target.account_id: final_target.account_id,
        }

        voting_utils.apply_mtl_delegations(
            [source, intermediate, blocked_target, final_target],
            delegations,
            {blocked_target.account_id: True},
        )

        assert source.balance == 0
        assert intermediate.balance == 0
        assert blocked_target.balance == 0
        assert final_target.balance == 900
        assert final_target.balance_delegated == 0

    def test_valid_delegation_keeps_existing_transfer_behavior(self):
        source = make_shareholder("GSOURCE", 1_000)
        target = make_shareholder("GTARGET", 500)
        delegations = {source.account_id: target.account_id}

        voting_utils.apply_mtl_delegations([source, target], delegations, {})

        assert source.balance == 0
        assert target.balance == 1_500
        assert target.balance_delegated == 1_000
        assert delegations == {source.account_id: target.account_id}

    def test_multistep_delegation_does_not_count_delegated_balance_twice(self):
        source = make_shareholder("GSOURCE", 1_000)
        intermediate = make_shareholder("GINTERMEDIATE", 700)
        target = make_shareholder("GTARGET", 500)
        delegations = {
            source.account_id: intermediate.account_id,
            intermediate.account_id: target.account_id,
        }

        voting_utils.apply_mtl_delegations(
            [intermediate, source, target],
            delegations,
            {},
        )

        assert source.balance == 0
        assert intermediate.balance == 0
        assert target.balance == 2_200
        assert target.balance_delegated == 1_700

    def test_delegation_cycle_without_blacklist_terminates(self):
        first = make_shareholder("GFIRST", 1_000)
        second = make_shareholder("GSECOND", 500)

        voting_utils.apply_mtl_delegations(
            [first, second],
            {first.account_id: second.account_id, second.account_id: first.account_id},
            {},
        )

        assert first.balance + second.balance == 1_500


class TestNormalizeVoteWeights:
    """Tests for normalize_vote_weights pure function."""

    def test_major_holder_within_target_range(self):
        """With typical distribution, major holder should be within 33-40%."""
        balances = [50000, 20000, 15000, 10000, 5000]
        weights = normalize_vote_weights(balances)
        total = sum(weights)
        major_share = weights[0] / total
        assert 0.33 <= major_share <= 0.40, f"Major share {major_share:.2%} outside 33-40%"

    def test_dominant_holder(self):
        """Normalize a dominant holder while preserving the minimum weight."""
        balances = [80000, 5000, 5000, 5000, 5000, 1]
        weights = normalize_vote_weights(balances)
        total = sum(weights)

        assert 0.33 <= weights[0] / total <= 0.40
        assert weights[-1] == 1

    def test_equal_balances(self):
        """Equal balances should produce equal weights."""
        balances = [10000, 10000, 10000, 10000]
        weights = normalize_vote_weights(balances)
        assert all(w == weights[0] for w in weights)

    def test_two_holders(self):
        """With two holders the function should still work."""
        balances = [70000, 30000]
        weights = normalize_vote_weights(balances)
        total = sum(weights)
        assert total > 0
        major_share = weights[0] / total
        assert 0.33 <= major_share <= 0.70  # two holders — cannot go below 50% naturally

    def test_many_small_holders(self):
        """With many small holders around one big, should hit 33-40%."""
        balances = [30000] + [2000] * 20
        weights = normalize_vote_weights(balances)
        total = sum(weights)
        major_share = weights[0] / total
        assert 0.33 <= major_share <= 0.40, f"Major share {major_share:.2%} outside 33-40%"

    def test_realistic_distribution(self):
        """Simulate a realistic MTL distribution."""
        balances = [45000, 25000, 18000, 12000, 8000, 6000, 4000, 3000, 2000, 1000]
        weights = normalize_vote_weights(balances)
        total = sum(weights)
        major_share = weights[0] / total
        assert 0.33 <= major_share <= 0.40, f"Major share {major_share:.2%} outside 33-40%"

    def test_balanced_distribution_skips_power_law_normalization(self):
        """Keep proportional weights when the largest holder is already below 40%."""
        balances = [9503, 9172, 8744, 6666, 5519, 2694, 1600, 1501, 1337, 1074, 1060, 957, 866, 649, 530, 500]

        weights = normalize_vote_weights(balances)

        assert weights == [19, 18, 17, 13, 11, 6, 4, 3, 3, 3, 3, 2, 2, 2, 2, 1]

    def test_preserves_ordering(self):
        """Weights should preserve the balance ordering (descending)."""
        balances = [50000, 30000, 20000, 10000, 5000]
        weights = normalize_vote_weights(balances)
        for i in range(len(weights) - 1):
            assert weights[i] >= weights[i + 1], f"Weight ordering violated at index {i}"

    def test_all_weights_positive(self):
        """All weights should be positive for positive balances."""
        balances = [50000, 20000, 10000, 5000, 1000]
        weights = normalize_vote_weights(balances)
        assert all(w > 0 for w in weights)

    def test_zero_balances(self):
        """All-zero balances should return all-zero weights."""
        balances = [0, 0, 0]
        weights = normalize_vote_weights(balances)
        assert weights == [0, 0, 0]

    def test_single_holder(self):
        """Single holder should get all votes."""
        balances = [50000]
        weights = normalize_vote_weights(balances)
        assert len(weights) == 1
        assert weights[0] > 0

    def test_custom_target_range(self):
        """Custom target range should be respected."""
        balances = [50000, 20000, 15000, 10000, 5000]
        weights = normalize_vote_weights(balances, target_min=0.25, target_max=0.30)
        total = sum(weights)
        major_share = weights[0] / total
        assert 0.25 <= major_share <= 0.30, f"Major share {major_share:.2%} outside 25-30%"

    def test_output_length_matches_input(self):
        """Output list should have same length as input."""
        balances = [50000, 20000, 15000]
        weights = normalize_vote_weights(balances)
        assert len(weights) == len(balances)


def test_vote_distribution_limit_accepts_any_largest_share_up_to_forty_percent():
    assert voting_utils.is_vote_distribution_within_limit([19, 18, 17, 13, 11, 6, 4, 3, 3, 3, 3, 2, 2, 2, 2, 1])
    assert voting_utils.is_vote_distribution_within_limit([40, 30, 20, 10])
    assert not voting_utils.is_vote_distribution_within_limit([41, 30, 20, 9])


# ============================================================================
# gen_vote_xdr: only real changes produce operations
# ============================================================================

import pytest  # noqa: E402
from stellar_sdk import Account, TransactionEnvelope, Network  # noqa: E402

ACC = "GACKTN5DAZGWXRWB2WLM6OPBDHAMT6SJNGLJZPQMEZBUR4JUGBX2UK7V"
VOTE_KEY = "GBYH3M3REQM3WQOJY26FYORN23EXY22FWBHVZ74TT5GYOF22IIA7YSOX"
OTHER_KEY = "GCPOWDQQDVSAQGJXZW3EWPPJ5JCF4KTTHBYNB4U54AKQVDLZXLLYMXY7"


def fake_account(signers: dict[str, int], thresholds: tuple[int, int, int], sequence: int = 10):
    """Build an `Account` shaped like a Horizon response."""
    return Account(
        ACC,
        sequence,
        raw_data={
            "signers": [
                {"type": "ed25519_public_key", "key": key, "weight": weight} for key, weight in signers.items()
            ],
            "thresholds": {
                "low_threshold": thresholds[0],
                "med_threshold": thresholds[1],
                "high_threshold": thresholds[2],
            },
        },
    )


def patch_account(monkeypatch, account):
    async def _load(account_id):
        assert account_id == ACC
        return account

    monkeypatch.setattr(voting_utils, "load_account_async", _load)


def decode_set_options(xdr: str) -> list:
    """Decode XDR and return raw set_options op bodies."""
    envelope = TransactionEnvelope.from_xdr(xdr, network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE)
    return [op.to_xdr_object().body.set_options_op for op in envelope.transaction.operations]


@pytest.mark.asyncio
async def test_gen_vote_xdr_returns_none_when_nothing_changes(monkeypatch):
    """Already correct signers + thresholds + master weight must produce no ops."""
    patch_account(monkeypatch, fake_account({ACC: 0, VOTE_KEY: 7}, (4, 4, 4)))
    vote_list = [MyShareHolder(account_id=VOTE_KEY, votes=7, calculated_votes=7)]

    xdr = await voting_utils.gen_vote_xdr(ACC, vote_list, source=ACC, remove_master=True)

    assert xdr is None


@pytest.mark.asyncio
async def test_gen_vote_xdr_only_changes_diff_and_thresholds(monkeypatch):
    """A weight change adds the signer op and the thresholds op."""
    patch_account(monkeypatch, fake_account({ACC: 0, VOTE_KEY: 7}, (4, 4, 4)))
    vote_list = [MyShareHolder(account_id=VOTE_KEY, votes=7, calculated_votes=10)]

    xdr = await voting_utils.gen_vote_xdr(ACC, vote_list, source=ACC, remove_master=True)

    assert xdr is not None
    operations = decode_set_options(xdr)
    assert len(operations) == 2
    assert operations[0].signer.weight.uint32 == 10
    assert operations[1].low_threshold.uint32 == 6
    # master weight must stay untouched when it is already 0
    assert operations[1].master_weight is None


@pytest.mark.asyncio
async def test_gen_vote_xdr_resets_master_weight_when_it_is_not_zero(monkeypatch):
    """master_weight=0 is sent only when the key still has weight."""
    patch_account(monkeypatch, fake_account({ACC: 5, VOTE_KEY: 7}, (4, 4, 4)))
    vote_list = [MyShareHolder(account_id=VOTE_KEY, votes=7, calculated_votes=7)]

    xdr = await voting_utils.gen_vote_xdr(ACC, vote_list, source=ACC, remove_master=True)

    assert xdr is not None
    operations = decode_set_options(xdr)
    assert len(operations) == 1
    assert operations[0].master_weight.uint32 == 0


@pytest.mark.asyncio
async def test_gen_vote_xdr_keeps_master_weight_when_not_asked(monkeypatch):
    """Without remove_master an unchanged account stays untouched."""
    patch_account(monkeypatch, fake_account({ACC: 5, VOTE_KEY: 7}, (4, 4, 4)))
    vote_list = [MyShareHolder(account_id=VOTE_KEY, votes=7, calculated_votes=7)]

    xdr = await voting_utils.gen_vote_xdr(ACC, vote_list, source=ACC, remove_master=False)

    assert xdr is None


@pytest.mark.asyncio
async def test_gen_vote_xdr_removes_extra_signer(monkeypatch):
    """A signer missing from the vote list gets weight 0 (removal)."""
    patch_account(monkeypatch, fake_account({ACC: 0, VOTE_KEY: 7, OTHER_KEY: 3}, (5, 5, 5)))
    vote_list = [MyShareHolder(account_id=VOTE_KEY, votes=7, calculated_votes=7)]

    xdr = await voting_utils.gen_vote_xdr(ACC, vote_list, source=ACC, remove_master=True)

    assert xdr is not None
    operations = decode_set_options(xdr)
    signer_ops = [op for op in operations if op.signer is not None]
    assert len(signer_ops) == 1
    assert signer_ops[0].signer.weight.uint32 == 0


# ============================================================================
# cmd_get_new_vote_all_mtl: skip accounts without changes
# ============================================================================

from other.stellar.constants import MTLAddresses  # noqa: E402


def patch_multi_accounts(monkeypatch, accounts_by_id: dict, issuer_account):
    async def _load(account_id):
        if account_id == MTLAddresses.public_issuer:
            return issuer_account
        return accounts_by_id[account_id]

    async def _load_vote_list():
        return [MyShareHolder(account_id=VOTE_KEY, votes=7, calculated_votes=10)]

    async def _load_table(*args, **kwargs):
        return [{"account_id": account_id} for account_id in accounts_by_id]

    monkeypatch.setattr(voting_utils, "load_account_async", _load)
    monkeypatch.setattr(voting_utils, "cmd_gen_mtl_vote_list", _load_vote_list)
    monkeypatch.setattr(voting_utils.grist_manager, "load_table_data", _load_table)


def make_account(account_id: str, signers: dict[str, int], thresholds: tuple[int, int, int], sequence: int = 10):
    return Account(
        account_id,
        sequence,
        raw_data={
            "signers": [
                {"type": "ed25519_public_key", "key": key, "weight": weight} for key, weight in signers.items()
            ],
            "thresholds": {
                "low_threshold": thresholds[0],
                "med_threshold": thresholds[1],
                "high_threshold": thresholds[2],
            },
        },
    )


@pytest.mark.asyncio
async def test_cmd_get_new_vote_all_mtl_skips_accounts_without_changes(monkeypatch):
    """Accounts already in the desired state are reported as skipped, not updated."""
    changed_account = "GDASYWP6F44TVNJKZKQ2UEVZOKTENCJFTWVMP6UC7JBZGY4ZNB6YAVD4"
    unchanged_account = "GCOJHUKGHI6IATN7AIEK4PSNBPXIAIZ7KB2AWTTUCNIAYVPUB2DMCITY"
    issuer_account = make_account(MTLAddresses.public_issuer, {MTLAddresses.public_issuer: 0}, (1, 1, 1), sequence=100)
    patch_multi_accounts(
        monkeypatch,
        {
            changed_account: make_account(changed_account, {changed_account: 0, VOTE_KEY: 7}, (4, 4, 4)),
            # already has the calculated weight (10) and the matching threshold (10 // 2 + 1)
            unchanged_account: make_account(unchanged_account, {unchanged_account: 0, VOTE_KEY: 10}, (6, 6, 6)),
        },
        issuer_account,
    )

    result = await voting_utils.cmd_get_new_vote_all_mtl("")

    assert result.updated == [changed_account]
    assert result.skipped == [unchanged_account]
    assert result.xdr is not None
    operations = decode_set_options(result.xdr)
    assert len(operations) == 2  # signer weight + thresholds for the changed account only


@pytest.mark.asyncio
async def test_cmd_get_new_vote_all_mtl_returns_none_when_nothing_changed(monkeypatch):
    """No accounts to update -> no transaction at all."""
    account = "GCOJHUKGHI6IATN7AIEK4PSNBPXIAIZ7KB2AWTTUCNIAYVPUB2DMCITY"
    issuer_account = make_account(MTLAddresses.public_issuer, {MTLAddresses.public_issuer: 0}, (1, 1, 1), sequence=100)
    patch_multi_accounts(
        monkeypatch,
        {account: make_account(account, {account: 0, VOTE_KEY: 10}, (6, 6, 6))},
        issuer_account,
    )

    result = await voting_utils.cmd_get_new_vote_all_mtl("")

    assert result.xdr is None
    assert result.updated == []
    assert result.skipped == [account]
