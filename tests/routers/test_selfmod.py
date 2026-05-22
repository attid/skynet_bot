"""Integration tests for routers/selfmod.py — vote callbacks + 👾 mute reaction."""

import datetime
from types import SimpleNamespace

import pytest
from aiogram import types

from other.constants import BotValueTypes, MTLChats
from routers.selfmod import (
    SelfmodVoteCallback,
    begin_join_vote,
    router as selfmod_router,
    selfmod_reaction,
)
from services.admin_service import AdminManagementService
from services.selfmod_service import SelfmodService
from tests.conftest import RouterTestMiddleware


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if selfmod_router.parent_router:
        selfmod_router._parent_router = None


def _swap_real_selfmod(ctx) -> SelfmodService:
    """Replace the fake selfmod service with the real one wired to the fake DB."""
    real = SelfmodService(ctx.db_service)
    ctx.selfmod_service = real
    return real


def _swap_real_admin(ctx) -> AdminManagementService:
    """Replace the fake admin service with the real in-memory one."""
    real = AdminManagementService()
    ctx.admin_service = real
    return real


def _vote_update(chat_id: int, vote_msg_id: int, voter_id: int, voter_uname: str, yes: bool):
    cb_data = SelfmodVoteCallback(yes=yes, msg_id=vote_msg_id).pack()
    return types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id=f"cb-{voter_id}",
            chat_instance=f"ci-{voter_id}",
            from_user=types.User(id=voter_id, is_bot=False, first_name=voter_uname, username=voter_uname),
            message=types.Message(
                message_id=vote_msg_id,
                date=datetime.datetime.now(),
                chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
                text="Vote",
            ),
            data=cb_data,
        ),
    )


# ----------------------------------------------------------------------
# Join vote
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_join_vote_approve_lifts_restrict_and_logs(mock_telegram, router_app_context):
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    dp = ctx.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(ctx))
    dp.include_router(selfmod_router)

    chat_id = -100123
    target = types.User(id=42, is_bot=False, first_name="Newcomer", username="newcomer")
    chat = SimpleNamespace(id=chat_id, title="TestChat", username="testchat")

    await begin_join_vote(ctx.bot, chat, target, ctx)
    state = next(iter(selfmod_service._votes.values()))
    vote_msg_id = state.vote_msg_id

    for voter_id, name in [(101, "alice"), (102, "bob"), (103, "carol")]:
        await dp.feed_update(bot=ctx.bot, update=_vote_update(chat_id, vote_msg_id, voter_id, name, yes=True))

    requests = mock_telegram.get_requests()
    methods = [r["method"] for r in requests]

    # Initial restrict (no_send) + lift restrict (full perms) on approve.
    assert methods.count("restrictChatMember") >= 2
    # Voting message was forwarded to SpamGroup before deletion (audit trail)
    forwards = [
        r
        for r in requests
        if r["method"] == "forwardMessage"
        and int(r["data"].get("chat_id", 0)) == MTLChats.SpamGroup
        and int(r["data"].get("from_chat_id", 0)) == chat_id
        and int(r["data"].get("message_id", 0)) == vote_msg_id
    ]
    assert forwards, "Voting message must be forwarded to SpamGroup before delete"
    assert "deleteMessage" in methods
    # Spam-chat received both 'started' and 'approved'
    spam_msgs = [
        r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage" and r["data"].get("chat_id") in (str(MTLChats.SpamGroup), MTLChats.SpamGroup)
    ]
    assert any("join_vote_started" in t for t in spam_msgs)
    assert any("join_vote_approved" in t for t in spam_msgs)
    # Voting message text contains voter mentions (like good/spam vote)
    edits = [r for r in requests if r["method"] == "editMessageText"]
    assert any(
        "alice" in r["data"]["text"] and "bob" in r["data"]["text"] and "carol" in r["data"]["text"] for r in edits
    ), "Final voting text must list all voters"
    # State cleaned up
    assert selfmod_service.get_vote(chat_id, vote_msg_id) is None


@pytest.mark.asyncio
async def test_join_vote_reject_bans_and_logs(mock_telegram, router_app_context):
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    dp = ctx.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(ctx))
    dp.include_router(selfmod_router)

    chat_id = -100124
    target = types.User(id=42, is_bot=False, first_name="Newcomer", username="newcomer")
    chat = SimpleNamespace(id=chat_id, title="TestChat", username=None)

    await begin_join_vote(ctx.bot, chat, target, ctx)
    state = next(iter(selfmod_service._votes.values()))
    vote_msg_id = state.vote_msg_id

    for voter_id, name in [(201, "a"), (202, "b"), (203, "c")]:
        await dp.feed_update(bot=ctx.bot, update=_vote_update(chat_id, vote_msg_id, voter_id, name, yes=False))

    requests = mock_telegram.get_requests()
    methods = [r["method"] for r in requests]
    assert "banChatMember" in methods
    spam_texts = [
        r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage" and r["data"].get("chat_id") in (str(MTLChats.SpamGroup), MTLChats.SpamGroup)
    ]
    assert any("join_vote_rejected" in t for t in spam_texts)
    assert selfmod_service.get_vote(chat_id, vote_msg_id) is None


@pytest.mark.asyncio
async def test_join_vote_scaled_threshold(mock_telegram, router_app_context):
    """2 no + 5 yes is still pending; 6th yes approves."""
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    dp = ctx.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(ctx))
    dp.include_router(selfmod_router)

    chat_id = -100125
    target = types.User(id=42, is_bot=False, first_name="N", username="n")
    chat = SimpleNamespace(id=chat_id, title="T", username=None)

    await begin_join_vote(ctx.bot, chat, target, ctx)
    state = next(iter(selfmod_service._votes.values()))
    vote_msg_id = state.vote_msg_id

    # 2 no
    for vid in (1, 2):
        await dp.feed_update(bot=ctx.bot, update=_vote_update(chat_id, vote_msg_id, vid, f"u{vid}", yes=False))
    # 5 yes — vote should still be open
    for vid in (10, 11, 12, 13, 14):
        await dp.feed_update(bot=ctx.bot, update=_vote_update(chat_id, vote_msg_id, vid, f"u{vid}", yes=True))
    assert selfmod_service.get_vote(chat_id, vote_msg_id) is not None

    # 6th yes → approve closes the vote
    await dp.feed_update(bot=ctx.bot, update=_vote_update(chat_id, vote_msg_id, 15, "u15", yes=True))
    assert selfmod_service.get_vote(chat_id, vote_msg_id) is None


@pytest.mark.asyncio
async def test_double_vote_blocked(mock_telegram, router_app_context):
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    dp = ctx.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(ctx))
    dp.include_router(selfmod_router)

    chat_id = -100126
    target = types.User(id=42, is_bot=False, first_name="N", username="n")
    chat = SimpleNamespace(id=chat_id, title="T", username=None)
    await begin_join_vote(ctx.bot, chat, target, ctx)
    state = next(iter(selfmod_service._votes.values()))
    vote_msg_id = state.vote_msg_id

    await dp.feed_update(bot=ctx.bot, update=_vote_update(chat_id, vote_msg_id, 1, "u1", yes=True))
    await dp.feed_update(bot=ctx.bot, update=_vote_update(chat_id, vote_msg_id, 1, "u1", yes=True))

    requests = mock_telegram.get_requests()
    answer_texts = [r["data"].get("text", "") for r in requests if r["method"] == "answerCallbackQuery"]
    assert any("already voted" in t.lower() for t in answer_texts)
    # State has only one yes vote
    assert selfmod_service.get_vote(chat_id, vote_msg_id).yes() == 1


@pytest.mark.asyncio
async def test_target_cannot_vote_on_self(mock_telegram, router_app_context):
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    dp = ctx.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(ctx))
    dp.include_router(selfmod_router)

    chat_id = -100127
    target = types.User(id=42, is_bot=False, first_name="N", username="n")
    chat = SimpleNamespace(id=chat_id, title="T", username=None)
    await begin_join_vote(ctx.bot, chat, target, ctx)
    state = next(iter(selfmod_service._votes.values()))
    vote_msg_id = state.vote_msg_id

    # Target tries to vote for self
    await dp.feed_update(bot=ctx.bot, update=_vote_update(chat_id, vote_msg_id, 42, "n", yes=True))
    requests = mock_telegram.get_requests()
    answer_texts = [r["data"].get("text", "") for r in requests if r["method"] == "answerCallbackQuery"]
    assert any("cannot vote on yourself" in t.lower() for t in answer_texts)
    assert selfmod_service.get_vote(chat_id, vote_msg_id).yes() == 0


# ----------------------------------------------------------------------
# Mute vote via 👾 reaction
# ----------------------------------------------------------------------


def _reaction_event(chat_id: int, message_id: int, reactor_id: int, emoji: str = "👾", is_bot: bool = False):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, title="Group"),
        message_id=message_id,
        user=SimpleNamespace(id=reactor_id, is_bot=is_bot, username="reactor"),
        new_reaction=[types.ReactionTypeEmoji(emoji=emoji)],
    )


@pytest.mark.asyncio
async def test_eyes_reaction_starts_mute_vote(mock_telegram, router_app_context):
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    chat_id = -100200
    target_user_id = 7777

    # Cache the offending message context (as the cache middleware would).
    await ctx.message_thread_cache_service.remember_message_context(
        chat_id=chat_id,
        message_id=555,
        thread_id=0,
        user_id=target_user_id,
        username="badguy",
        full_name="Bad Guy",
    )

    event = _reaction_event(chat_id, 555, reactor_id=999)
    handled = await selfmod_reaction(event, ctx.bot, ctx)
    assert handled is True
    assert selfmod_service.has_active_mute_vote(chat_id, target_user_id) is True

    spam_logs = [
        r["data"]["text"]
        for r in mock_telegram.get_requests()
        if r["method"] == "sendMessage" and r["data"].get("chat_id") in (str(MTLChats.SpamGroup), MTLChats.SpamGroup)
    ]
    assert any("mute_vote_started" in t for t in spam_logs)


@pytest.mark.asyncio
async def test_eyes_reaction_from_bot_ignored(mock_telegram, router_app_context):
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    await ctx.message_thread_cache_service.remember_message_context(
        chat_id=-100201,
        message_id=10,
        thread_id=0,
        user_id=42,
        username="user",
        full_name="User",
    )

    event = _reaction_event(-100201, 10, reactor_id=ctx.bot.id, is_bot=True)
    handled = await selfmod_reaction(event, ctx.bot, ctx)
    assert handled is False
    assert selfmod_service.has_active_mute_vote(-100201, 42) is False


@pytest.mark.asyncio
async def test_eyes_reaction_without_cache_no_op(mock_telegram, router_app_context):
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)

    event = _reaction_event(-100202, 99, reactor_id=10)
    handled = await selfmod_reaction(event, ctx.bot, ctx)
    assert handled is False
    assert not selfmod_service._votes


@pytest.mark.asyncio
async def test_eyes_reaction_other_emoji_ignored(mock_telegram, router_app_context):
    ctx = router_app_context
    _swap_real_selfmod(ctx)
    await ctx.message_thread_cache_service.remember_message_context(
        chat_id=-100203,
        message_id=12,
        thread_id=0,
        user_id=42,
        username="user",
        full_name="User",
    )
    event = _reaction_event(-100203, 12, reactor_id=10, emoji="❤")
    handled = await selfmod_reaction(event, ctx.bot, ctx)
    assert handled is False


# ----------------------------------------------------------------------
# Mute escalation: 1d → 7d → kick vote
# ----------------------------------------------------------------------


async def _start_mute_and_approve(ctx, dp, chat_id: int, target_user_id: int, target_msg_id: int):
    """Helper: start a mute vote and pass it (3 yes)."""
    from routers.selfmod import begin_mute_vote

    selfmod_service = ctx.selfmod_service
    chat = SimpleNamespace(id=chat_id, title="Group", username=None)
    await begin_mute_vote(
        ctx.bot,
        chat,
        target_user_id=target_user_id,
        target_mention="@target",
        target_msg_id=target_msg_id,
        app_context=ctx,
    )
    # latest vote
    vote_msg_id = max(msg_id for (cid, msg_id), _ in selfmod_service._votes.items() if cid == chat_id)
    for vid, name in [(1001, "a"), (1002, "b"), (1003, "c")]:
        await dp.feed_update(bot=ctx.bot, update=_vote_update(chat_id, vote_msg_id, vid, name, yes=True))
    return vote_msg_id


@pytest.mark.asyncio
async def test_mute_vote_first_offense_one_day(mock_telegram, router_app_context):
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    admin_service = _swap_real_admin(ctx)
    dp = ctx.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(ctx))
    dp.include_router(selfmod_router)

    chat_id = -100300
    target = 4242
    await _start_mute_and_approve(ctx, dp, chat_id, target, target_msg_id=1)

    # First mute → 1 day, warning level 1
    assert await selfmod_service.get_warnings(chat_id, target) == 1
    # Real AdminManagementService received the mute (chat_thread_key = "{chat_id}-0")
    topic_key = f"{chat_id}-0"
    mutes = admin_service.get_topic_mutes_by_key(topic_key)
    assert target in mutes, f"Expected mute for user {target} in {topic_key}, got {mutes}"
    persisted_mutes = await ctx.db_service.load_bot_value(0, BotValueTypes.TopicMutes, "{}")
    assert str(target) in persisted_mutes
    end_time_iso = mutes[target]["end_time"]
    end_dt = datetime.datetime.fromisoformat(end_time_iso)
    now = datetime.datetime.now()
    delta = end_dt - now
    # Roughly 1 day ahead (allow ±1 minute jitter)
    assert datetime.timedelta(hours=23, minutes=59) <= delta <= datetime.timedelta(hours=24, minutes=1)
    # Telegram restrict was called with until_date equal to end_dt
    requests = mock_telegram.get_requests()
    restricts = [r for r in requests if r["method"] == "restrictChatMember"]
    assert restricts, "Expected restrict_chat_member call"
    spam_logs = [
        r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage" and r["data"].get("chat_id") in (str(MTLChats.SpamGroup), MTLChats.SpamGroup)
    ]
    assert any("mute_vote_approved" in t and "level: 1" in t for t in spam_logs)


@pytest.mark.asyncio
async def test_mute_vote_second_offense_seven_days(mock_telegram, router_app_context):
    """Pre-seeded warning=1 → second approve uses 7-day duration in real admin store."""
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    admin_service = _swap_real_admin(ctx)
    dp = ctx.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(ctx))
    dp.include_router(selfmod_router)

    chat_id = -100310
    target = 5252
    await selfmod_service.add_warning(chat_id, target)  # pre-existing level 1
    await _start_mute_and_approve(ctx, dp, chat_id, target, target_msg_id=1)

    assert await selfmod_service.get_warnings(chat_id, target) == 2
    mutes = admin_service.get_topic_mutes_by_key(f"{chat_id}-0")
    assert target in mutes
    end_dt = datetime.datetime.fromisoformat(mutes[target]["end_time"])
    delta = end_dt - datetime.datetime.now()
    # Roughly 7 days
    assert datetime.timedelta(days=6, hours=23) <= delta <= datetime.timedelta(days=7, hours=1)


@pytest.mark.asyncio
async def test_mute_vote_third_offense_starts_kick_vote(mock_telegram, router_app_context):
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    admin_service = _swap_real_admin(ctx)
    dp = ctx.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(ctx))
    dp.include_router(selfmod_router)

    chat_id = -100301
    target = 4343

    # Pre-seed 2 prior warnings
    await selfmod_service.add_warning(chat_id, target)
    await selfmod_service.add_warning(chat_id, target)
    assert await selfmod_service.get_warnings(chat_id, target) == 2

    await _start_mute_and_approve(ctx, dp, chat_id, target, target_msg_id=1)

    # 3rd offense → kick vote opened (no direct mute applied)
    assert await selfmod_service.get_warnings(chat_id, target) == 3
    # Real admin_service should NOT have a mute for this user — escalation skips the mute step
    assert admin_service.get_topic_mutes_by_key(f"{chat_id}-0") == {}
    spam_logs = [
        r["data"]["text"]
        for r in mock_telegram.get_requests()
        if r["method"] == "sendMessage" and r["data"].get("chat_id") in (str(MTLChats.SpamGroup), MTLChats.SpamGroup)
    ]
    assert any("kick_vote_started" in t for t in spam_logs)
    assert any("action: escalate" in t for t in spam_logs)


@pytest.mark.asyncio
async def test_kick_vote_approve_bans(mock_telegram, router_app_context):
    ctx = router_app_context
    selfmod_service = _swap_real_selfmod(ctx)
    dp = ctx.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(ctx))
    dp.include_router(selfmod_router)

    chat_id = -100302
    target = 4444
    # Get straight to a kick vote by pre-seeding warnings to 2 and triggering one mute vote.
    await selfmod_service.add_warning(chat_id, target)
    await selfmod_service.add_warning(chat_id, target)
    await _start_mute_and_approve(ctx, dp, chat_id, target, target_msg_id=1)

    # Find the kick vote (started by the escalation) and approve it with 3 yes.
    kick_msg_ids = [
        msg_id for (cid, msg_id), st in selfmod_service._votes.items() if cid == chat_id and st.kind == "kick"
    ]
    assert kick_msg_ids
    kick_msg_id = kick_msg_ids[0]
    for vid, name in [(2001, "x"), (2002, "y"), (2003, "z")]:
        await dp.feed_update(bot=ctx.bot, update=_vote_update(chat_id, kick_msg_id, vid, name, yes=True))

    methods = [r["method"] for r in mock_telegram.get_requests()]
    assert "banChatMember" in methods
    spam_logs = [
        r["data"]["text"]
        for r in mock_telegram.get_requests()
        if r["method"] == "sendMessage" and r["data"].get("chat_id") in (str(MTLChats.SpamGroup), MTLChats.SpamGroup)
    ]
    assert any("kick_vote_approved" in t for t in spam_logs)
