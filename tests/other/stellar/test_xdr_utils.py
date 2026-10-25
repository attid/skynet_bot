# tests/other/stellar/test_xdr_utils.py
"""Tests for MASS/SPAM filters in XDR decoding."""

from unittest.mock import AsyncMock, patch

import pytest
from stellar_sdk import Account, Asset, Claimant, ClaimPredicate, Keypair, Network, TransactionBuilder

from other.stellar.xdr_utils import decode_xdr


def _make_test_xdr(*, source: str, destination: str, op_count: int) -> str:
    source_account = Account(account=source, sequence=1)
    tb = TransactionBuilder(
        source_account=source_account,
        network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE,
        base_fee=100,
    )
    tb.set_timeout(0)

    for _ in range(op_count):
        tb.append_payment_op(destination=destination, amount="1", asset=Asset.native())

    return tb.build().to_xdr()


@pytest.mark.asyncio
async def test_mass_filter_skips_from_50_when_not_from_filter_account():
    src = Keypair.random().public_key
    dst = Keypair.random().public_key
    xdr = _make_test_xdr(source=src, destination=dst, op_count=50)

    with patch("other.stellar.xdr_utils.address_id_to_username", new=AsyncMock(return_value="@user")):
        # Account is involved (as destination) but is not the tx source.
        res = await decode_xdr(xdr, ignore_operation=["MASS"], filter_account=dst)

    assert res == []


@pytest.mark.asyncio
async def test_mass_filter_does_not_skip_when_from_filter_account():
    src = Keypair.random().public_key
    dst = Keypair.random().public_key
    xdr = _make_test_xdr(source=src, destination=dst, op_count=50)

    with patch("other.stellar.xdr_utils.address_id_to_username", new=AsyncMock(return_value="@user")):
        res = await decode_xdr(xdr, ignore_operation=["MASS"], filter_account=src)

    assert res != []


def _make_faucet_xdr(*, source: str, destination: str, op_pairs: int, amount: str) -> str:
    """Build a faucet-style tx: dust payments interleaved with claimable balances."""
    source_account = Account(account=source, sequence=1)
    tb = TransactionBuilder(
        source_account=source_account,
        network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE,
        base_fee=100,
    )
    tb.set_timeout(0)
    tb.add_text_memo("BFAB faucet")

    for _ in range(op_pairs):
        tb.append_payment_op(destination=destination, amount=amount, asset=Asset.native())
        tb.append_create_claimable_balance_op(
            asset=Asset.native(),
            amount="1",
            claimants=[Claimant(destination=destination, predicate=ClaimPredicate.predicate_unconditional())],
        )

    return tb.build().to_xdr()


@pytest.mark.asyncio
async def test_spam_filter_skips_dust_payment_in_scientific_notation():
    """stellar-sdk renders one stroop as "1E-7", so the SPAM check must be numeric."""
    src = Keypair.random().public_key
    dst = Keypair.random().public_key
    xdr = _make_faucet_xdr(source=src, destination=dst, op_pairs=1, amount="0.0000001")

    with patch("other.stellar.xdr_utils.address_id_to_username", new=AsyncMock(return_value="@user")):
        without_spam_filter = await decode_xdr(xdr, ignore_operation=["MASS"], filter_account=src)
        with_spam_filter = await decode_xdr(xdr, ignore_operation=["SPAM", "MASS"], filter_account=src)

    assert any("1E-7 XLM" in line for line in without_spam_filter)
    assert not any("Payment" in line for line in with_spam_filter)
    assert not any("Перевод" in line for line in with_spam_filter)


@pytest.mark.asyncio
async def test_spam_filter_drops_whole_faucet_transaction():
    src = Keypair.random().public_key
    dst = Keypair.random().public_key
    xdr = _make_faucet_xdr(source=src, destination=dst, op_pairs=13, amount="0.0000001")

    with patch("other.stellar.xdr_utils.address_id_to_username", new=AsyncMock(return_value="@user")):
        res = await decode_xdr(
            xdr,
            ignore_operation=["CreateClaimableBalance", "SPAM", "MASS"],
            filter_account=src,
        )

    assert res == []


@pytest.mark.asyncio
async def test_ignored_operation_types_leave_no_empty_headers():
    src = Keypair.random().public_key
    dst = Keypair.random().public_key
    xdr = _make_test_xdr(source=src, destination=dst, op_count=3)

    with patch("other.stellar.xdr_utils.address_id_to_username", new=AsyncMock(return_value="@user")):
        res = await decode_xdr(xdr, ignore_operation=["Payment"], filter_account=src)

    assert res == []


@pytest.mark.asyncio
async def test_spam_filter_keeps_payments_at_or_above_threshold():
    src = Keypair.random().public_key
    dst = Keypair.random().public_key
    xdr = _make_test_xdr(source=src, destination=dst, op_count=1)

    with patch("other.stellar.xdr_utils.address_id_to_username", new=AsyncMock(return_value="@user")):
        res = await decode_xdr(xdr, ignore_operation=["SPAM"], filter_account=src)

    assert any("Перевод 1 XLM" in line for line in res)
