"""Tests for SelfmodService — vote thresholds, warnings window, persistence."""

from datetime import datetime, timedelta, timezone

import pytest

from services.selfmod_service import (
    SelfmodService,
    VoteState,
    WARNING_WINDOW_DAYS,
    mute_duration_for_level,
    threshold_passed,
)
from tests.fakes import FakeDatabaseService


# ----------------------------------------------------------------------
# threshold_passed — table-driven
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("yes", "no", "expected"),
    [
        # Approve cases — formula: yes >= max(3, 3 * no)
        (3, 0, "approve"),
        (4, 0, "approve"),
        (3, 1, "approve"),  # 3 yes vs 1 no: 3 * 1 = 3, threshold met
        (6, 2, "approve"),  # 3 * no = 6 → reached
        (9, 3, "approve"),
        # Reject cases — symmetric
        (0, 3, "reject"),
        (2, 6, "reject"),
        (1, 3, "reject"),  # 3 no vs 1 yes: 3 * 1 = 3, threshold met
        # Pending cases
        (2, 0, None),
        (5, 2, None),  # need 6 yes when 2 no, only 5
        (1, 0, None),
        (1, 1, None),
        (0, 0, None),
        (2, 5, None),  # need 6 no when 2 yes, only 5
    ],
)
def test_threshold_passed_table(yes, no, expected):
    assert threshold_passed(yes, no) == expected


def test_mute_duration_for_level():
    assert mute_duration_for_level(1) == timedelta(days=1)
    assert mute_duration_for_level(2) == timedelta(days=7)
    assert mute_duration_for_level(3) is None  # escalate to kick
    assert mute_duration_for_level(0) is None
    assert mute_duration_for_level(5) is None


# ----------------------------------------------------------------------
# VoteState
# ----------------------------------------------------------------------


def test_vote_state_round_trip():
    state = VoteState(
        kind="join",
        chat_id=123,
        vote_msg_id=10,
        target_user_id=999,
        target_mention="@user",
        target_msg_id=5,
    )
    state.yes_voters.append(1)
    state.no_voters.append(2)
    state.voter_mentions["1"] = "@a"
    state.voter_mentions["2"] = "@b"

    restored = VoteState.from_dict(state.to_dict())
    assert restored.kind == "join"
    assert restored.target_user_id == 999
    assert restored.yes_voters == [1]
    assert restored.no_voters == [2]
    assert restored.voter_mentions == {"1": "@a", "2": "@b"}


def test_vote_state_has_voted_yes_and_no():
    state = VoteState(kind="mute", chat_id=1, vote_msg_id=2, target_user_id=3, target_mention="x")
    state.yes_voters.append(10)
    state.no_voters.append(20)
    assert state.has_voted(10) is True
    assert state.has_voted(20) is True
    assert state.has_voted(99) is False


# ----------------------------------------------------------------------
# Service: voting lifecycle
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_vote_persists_to_db():
    db = FakeDatabaseService()
    service = SelfmodService(db)

    state = await service.start_vote(
        kind="join",
        chat_id=100,
        vote_msg_id=10,
        target_user_id=42,
        target_mention="@joiner",
    )

    assert state.kind == "join"
    assert service.get_vote(100, 10) is state
    # Persistence: a follow-up service instance should see the vote.
    fresh = SelfmodService(db)
    assert fresh.get_vote(100, 10) is None  # not loaded yet
    loaded = await fresh.cast(100, 10, voter_id=1, voter_mention="@a", choice=True)
    assert loaded is not None  # loaded from DB on first cast


@pytest.mark.asyncio
async def test_cast_threshold_approve():
    db = FakeDatabaseService()
    service = SelfmodService(db)
    await service.start_vote(kind="join", chat_id=1, vote_msg_id=1, target_user_id=42, target_mention="@x")

    assert (await service.cast(1, 1, 100, "@a", True)).outcome is None
    assert (await service.cast(1, 1, 200, "@b", True)).outcome is None
    third = await service.cast(1, 1, 300, "@c", True)
    assert third.outcome == "approve"
    assert third.state.yes() == 3


@pytest.mark.asyncio
async def test_cast_threshold_reject_after_no_votes():
    db = FakeDatabaseService()
    service = SelfmodService(db)
    await service.start_vote(kind="join", chat_id=1, vote_msg_id=1, target_user_id=42, target_mention="@x")

    assert (await service.cast(1, 1, 100, "@a", False)).outcome is None
    assert (await service.cast(1, 1, 200, "@b", False)).outcome is None
    third = await service.cast(1, 1, 300, "@c", False)
    assert third.outcome == "reject"


@pytest.mark.asyncio
async def test_cast_scaled_threshold_2_no_needs_6_yes():
    db = FakeDatabaseService()
    service = SelfmodService(db)
    await service.start_vote(kind="join", chat_id=1, vote_msg_id=1, target_user_id=42, target_mention="@x")
    # 2 no
    await service.cast(1, 1, 1, "@a", False)
    await service.cast(1, 1, 2, "@b", False)
    # 5 yes — still pending (need 6)
    for uid in (10, 11, 12, 13, 14):
        result = await service.cast(1, 1, uid, f"@u{uid}", True)
        assert result.outcome is None, f"unexpected close at uid={uid}"
    # 6th yes → approve
    final = await service.cast(1, 1, 15, "@u15", True)
    assert final.outcome == "approve"


@pytest.mark.asyncio
async def test_cast_double_vote_blocked():
    db = FakeDatabaseService()
    service = SelfmodService(db)
    await service.start_vote(kind="join", chat_id=1, vote_msg_id=1, target_user_id=42, target_mention="@x")
    first = await service.cast(1, 1, 100, "@a", True)
    second = await service.cast(1, 1, 100, "@a", True)
    assert first.already_voted is False
    assert second.already_voted is True
    assert second.state.yes() == 1


@pytest.mark.asyncio
async def test_cast_unknown_vote_returns_none():
    service = SelfmodService(FakeDatabaseService())
    result = await service.cast(99, 99, 1, "@x", True)
    assert result is None


@pytest.mark.asyncio
async def test_close_vote_removes_state():
    db = FakeDatabaseService()
    service = SelfmodService(db)
    await service.start_vote(kind="join", chat_id=1, vote_msg_id=1, target_user_id=42, target_mention="@x")
    await service.close_vote(1, 1)
    assert service.get_vote(1, 1) is None


@pytest.mark.asyncio
async def test_has_active_mute_vote():
    db = FakeDatabaseService()
    service = SelfmodService(db)
    await service.start_vote(kind="mute", chat_id=1, vote_msg_id=10, target_user_id=42, target_mention="@x")
    assert service.has_active_mute_vote(1, 42) is True
    assert service.has_active_mute_vote(1, 99) is False
    assert service.has_active_mute_vote(2, 42) is False


# ----------------------------------------------------------------------
# Warnings window
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_warning_increments():
    db = FakeDatabaseService()
    service = SelfmodService(db)
    assert await service.add_warning(1, 42) == 1
    assert await service.add_warning(1, 42) == 2
    assert await service.add_warning(1, 42) == 3
    assert await service.get_warnings(1, 42) == 3


@pytest.mark.asyncio
async def test_warnings_outside_window_filtered():
    fixed_now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    service = SelfmodService(FakeDatabaseService(), now_fn=lambda: fixed_now)
    # Manually inject a stale and a fresh timestamp
    service._warnings[1] = {
        42: [
            (fixed_now - timedelta(days=WARNING_WINDOW_DAYS + 1)).isoformat(),  # stale
            (fixed_now - timedelta(days=WARNING_WINDOW_DAYS - 1)).isoformat(),  # fresh
        ]
    }
    service._loaded_chats.add(1)

    assert await service.get_warnings(1, 42) == 1


@pytest.mark.asyncio
async def test_add_warning_purges_old_entries():
    fixed_now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    db = FakeDatabaseService()
    service = SelfmodService(db, now_fn=lambda: fixed_now)
    # Pre-seed with a stale entry
    service._warnings[1] = {42: [(fixed_now - timedelta(days=WARNING_WINDOW_DAYS + 5)).isoformat()]}
    service._loaded_chats.add(1)

    level = await service.add_warning(1, 42)
    assert level == 1  # the stale one is dropped


@pytest.mark.asyncio
async def test_reset_warnings():
    db = FakeDatabaseService()
    service = SelfmodService(db)
    await service.add_warning(1, 42)
    await service.add_warning(1, 42)
    assert await service.get_warnings(1, 42) == 2
    await service.reset_warnings(1, 42)
    assert await service.get_warnings(1, 42) == 0


@pytest.mark.asyncio
async def test_list_warnings():
    db = FakeDatabaseService()
    service = SelfmodService(db)
    await service.add_warning(1, 100)
    await service.add_warning(1, 100)
    await service.add_warning(1, 200)

    listing = await service.list_warnings(1)
    assert listing == {100: 2, 200: 1}


# ----------------------------------------------------------------------
# Persistence round-trip across instances
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warnings_persist_round_trip():
    db = FakeDatabaseService()
    s1 = SelfmodService(db)
    await s1.add_warning(1, 42)
    await s1.add_warning(1, 42)

    s2 = SelfmodService(db)
    assert await s2.get_warnings(1, 42) == 2


@pytest.mark.asyncio
async def test_active_votes_persist_round_trip():
    db = FakeDatabaseService()
    s1 = SelfmodService(db)
    await s1.start_vote(kind="join", chat_id=1, vote_msg_id=10, target_user_id=42, target_mention="@x")
    await s1.cast(1, 10, 100, "@a", True)

    s2 = SelfmodService(db)
    # Trigger load by casting another vote
    result = await s2.cast(1, 10, 200, "@b", True)
    assert result is not None
    assert result.state.yes() == 2
