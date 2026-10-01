"""Tests for the /ban easter egg counter and ephemeral command confirmations."""

import datetime
import json

import pytest
from aiogram import types

from routers.moderation import router as moderation_router
from services.ban_stats_service import BanStatsService
from tests.conftest import RouterTestMiddleware
from other.constants import MTLChats


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if moderation_router.parent_router:
        moderation_router._parent_router = None


def _make_group_update(update_id, message_id, user_id, username, text):
    return types.Update(
        update_id=update_id,
        message=types.Message(
            message_id=message_id,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup", title="Test Chat"),
            from_user=types.User(id=user_id, is_bot=False, first_name="Admin", username=username),
            text=text,
        ),
    )


def _ephemeral_texts(mock_telegram):
    result = []
    for r in mock_telegram.get_requests():
        if r["method"] != "sendMessage":
            continue
        params = r["data"].get("ephemeral_message_parameters")
        if not params:
            continue
        if isinstance(params, str):
            params = json.loads(params)
        result.append((r["data"]["text"], params["receiver_user_id"]))
    return result


# ---------------------------------------------------------------------------
# BanStatsService unit tests
# ---------------------------------------------------------------------------


def test_ban_stats_counts_bans_per_day():
    service = BanStatsService()
    today = datetime.date(2026, 9, 15)

    assert service.record_ban(1, today=today) == 1
    assert service.record_ban(1, today=today) == 2
    assert service.record_ban(1, today=today) == 3


def test_ban_stats_resets_on_next_day():
    service = BanStatsService()
    day1 = datetime.date(2026, 9, 15)
    day2 = datetime.date(2026, 9, 16)

    assert service.record_ban(1, today=day1) == 1
    assert service.record_ban(1, today=day1) == 2
    assert service.record_ban(1, today=day2) == 1


def test_ban_stats_isolated_per_admin():
    service = BanStatsService()
    today = datetime.date(2026, 9, 15)

    assert service.record_ban(1, today=today) == 1
    assert service.record_ban(1, today=today) == 2
    assert service.record_ban(2, today=today) == 1


# ---------------------------------------------------------------------------
# UtilsService.reply_ephemeral fallback
# ---------------------------------------------------------------------------


class _StubBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, *args, **kwargs):
        self.sent.append(kwargs)
        return "sent"


class _StubMessage:
    def __init__(self, from_user, message_thread_id=None):
        self.from_user = from_user
        self.bot = _StubBot()
        self.chat = types.Chat(id=-100123, type="supergroup", is_forum=True)
        self.message_thread_id = message_thread_id
        self.replies = []

    async def reply(self, text, parse_mode=None, reply_markup=None):
        self.replies.append(text)
        return "reply"


@pytest.mark.asyncio
async def test_reply_ephemeral_targets_sender():
    from services.external_services import UtilsService

    message = _StubMessage(types.User(id=777, is_bot=False, first_name="Admin"))
    await UtilsService().reply_ephemeral(message, "Added")

    assert message.replies == []
    assert message.bot.sent[0]["ephemeral_message_parameters"].receiver_user_id == 777


@pytest.mark.asyncio
async def test_reply_ephemeral_falls_back_for_bot_sender():
    from services.external_services import UtilsService

    message = _StubMessage(types.User(id=1087968824, is_bot=True, first_name="Channel"))
    await UtilsService().reply_ephemeral(message, "Added")

    assert message.replies == ["Added"]
    assert message.bot.sent == []


@pytest.mark.asyncio
async def test_reply_ephemeral_passes_topic_in_forum():
    from services.external_services import UtilsService

    message = _StubMessage(types.User(id=777, is_bot=False, first_name="Admin"), message_thread_id=42)
    await UtilsService().reply_ephemeral(message, "Added")

    assert message.bot.sent[0]["message_thread_id"] == 42
    assert message.bot.sent[0]["ephemeral_message_parameters"].receiver_user_id == 777


@pytest.mark.asyncio
async def test_reply_ephemeral_no_thread_id_outside_forum():
    from services.external_services import UtilsService

    message = _StubMessage(types.User(id=777, is_bot=False, first_name="User"))
    await UtilsService().reply_ephemeral(message, "Added")

    assert message.bot.sent[0]["message_thread_id"] is None
    assert message.bot.sent[0]["ephemeral_message_parameters"].receiver_user_id == 777


# ---------------------------------------------------------------------------
# /ban integration: ephemeral confirmation + easter egg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ban_sends_ephemeral_confirmation(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(moderation_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    update = _make_group_update(1, 1, 999, "admin", "/ban 123456")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.moderation_service.ban_user.called
    texts = _ephemeral_texts(mock_telegram)
    assert any("has been banned" in text for text, _ in texts)
    assert all(receiver == 999 for _, receiver in texts)
    # The command message itself is removed immediately.
    assert any(r["method"] == "deleteMessage" and r["data"]["message_id"] == "1" for r in mock_telegram.get_requests())


@pytest.mark.asyncio
async def test_ban_easter_egg_counts_daily_villains(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(moderation_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    await dp.feed_update(bot=router_app_context.bot, update=_make_group_update(1, 1, 999, "admin", "/ban 123456"))
    await dp.feed_update(bot=router_app_context.bot, update=_make_group_update(2, 2, 999, "admin", "/ban 123457"))

    ephemeral_texts = [text for text, _ in _ephemeral_texts(mock_telegram)]
    assert any("поймал злодея ID 123456" in text for text in ephemeral_texts)
    assert any("забанено 2 злодеев" in text and "ID 123457" in text for text in ephemeral_texts)
