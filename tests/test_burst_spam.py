import datetime

import pytest
from aiogram import types

import routers.last_handler as last_handler
from routers.last_handler import router as last_router
from services.burst_spam_service import BurstSpamService
from shared.domain.user import SpamStatus
from tests.conftest import RouterTestMiddleware


def build_message_update(update_id, message_id, chat_id, user_id, text):
    return types.Update(
        update_id=update_id,
        message=types.Message(
            message_id=message_id,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
            from_user=types.User(id=user_id, is_bot=False, first_name="Spammer", username="spammer"),
            text=text,
        ),
    )


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if last_router.parent_router:
        last_router._parent_router = None


# --- Unit tests: BurstSpamService ---


SPAM_TEXT = "Салют, есть тут в чате те, кто мог бы мне помочь с 1м деликатным вопросов ?"


def test_first_message_registered_without_hit():
    service = BurstSpamService()
    assert service.register(1, 2, 10, SPAM_TEXT, now=1000.0) is None


def test_second_identical_message_hits_with_panel():
    service = BurstSpamService()
    service.register(1, 2, 10, SPAM_TEXT, now=1000.0)
    service.register_panel(1, 2, 10, 99)

    hit = service.register(1, 2, 11, SPAM_TEXT, now=1005.0)

    assert hit is not None
    assert hit.chat_id == 1
    assert hit.user_id == 2
    assert hit.copies == 2
    assert [record.message_id for record in hit.records] == [10]
    assert hit.records[0].panel_message_id == 99


def test_normalization_matches_case_and_whitespace():
    service = BurstSpamService()
    service.register(1, 2, 10, SPAM_TEXT, now=1000.0)
    hit = service.register(1, 2, 11, "  " + SPAM_TEXT.upper() + " \n", now=1005.0)
    assert hit is not None


def test_different_text_does_not_hit():
    service = BurstSpamService()
    service.register(1, 2, 10, SPAM_TEXT, now=1000.0)
    assert service.register(1, 2, 11, "A completely different message body here", now=1005.0) is None


def test_short_text_is_ignored():
    service = BurstSpamService()
    assert service.register(1, 2, 10, "спасибо", now=1000.0) is None
    assert service.register(1, 2, 11, "спасибо", now=1005.0) is None


def test_text_outside_window_does_not_hit():
    service = BurstSpamService(window_seconds=600)
    service.register(1, 2, 10, SPAM_TEXT, now=1000.0)
    assert service.register(1, 2, 11, SPAM_TEXT, now=1000.0 + 601) is None


def test_hits_are_isolated_per_chat_and_user():
    service = BurstSpamService()
    service.register(1, 2, 10, SPAM_TEXT, now=1000.0)
    service.register(1, 3, 20, SPAM_TEXT, now=1001.0)
    service.register(5, 2, 30, SPAM_TEXT, now=1002.0)

    hit = service.register(1, 2, 11, SPAM_TEXT, now=1003.0)
    assert hit is not None
    assert [record.message_id for record in hit.records] == [10]


def test_hit_rearms_on_further_copies():
    service = BurstSpamService()
    service.register(1, 2, 10, SPAM_TEXT, now=1000.0)
    first_hit = service.register(1, 2, 11, SPAM_TEXT, now=1005.0)
    assert first_hit is not None

    # The triggering copy stays tracked, so the next duplicate bursts immediately.
    second_hit = service.register(1, 2, 12, SPAM_TEXT, now=1010.0)
    assert second_hit is not None
    assert [record.message_id for record in second_hit.records] == [11]


# --- Router integration tests ---


@pytest.mark.asyncio
async def test_burst_duplicates_deleted_and_user_restricted(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id, user_id = -100333333, 777
    router_app_context.burst_spam_service = BurstSpamService()
    router_app_context.voting_service.enable_first_vote(chat_id)
    # Deterministic vote-panel id: every sendMessage replies with message_id=555
    mock_telegram.add_response(
        "sendMessage",
        {
            "ok": True,
            "result": {
                "message_id": 555,
                "date": 1234567890,
                "chat": {"id": chat_id, "type": "supergroup"},
                "text": "Please help me detect spam messages",
            },
        },
    )

    await dp.feed_update(
        bot=router_app_context.bot,
        update=build_message_update(1, 11, chat_id, user_id, SPAM_TEXT),
    )
    await dp.feed_update(
        bot=router_app_context.bot,
        update=build_message_update(2, 12, chat_id, user_id, SPAM_TEXT),
    )

    requests = mock_telegram.get_requests()
    deleted_ids = {int(r["data"]["message_id"]) for r in requests if r["method"] == "deleteMessage"}
    assert {11, 12, 555} <= deleted_ids, f"expected copies and vote panel deleted, got {deleted_ids}"
    assert any(r["method"] == "restrictChatMember" for r in requests)
    assert any(r["method"] == "forwardMessage" for r in requests)
    assert router_app_context.db_service._bot_users[user_id].user_type == 2


@pytest.mark.asyncio
async def test_good_user_duplicates_are_ignored(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id, user_id = -100444444, 888
    router_app_context.burst_spam_service = BurstSpamService()
    router_app_context.spam_status_service.set_status(user_id, SpamStatus.GOOD)

    await dp.feed_update(
        bot=router_app_context.bot,
        update=build_message_update(1, 21, chat_id, user_id, SPAM_TEXT),
    )
    await dp.feed_update(
        bot=router_app_context.bot,
        update=build_message_update(2, 22, chat_id, user_id, SPAM_TEXT),
    )

    requests = mock_telegram.get_requests()
    assert not any(r["method"] == "deleteMessage" for r in requests)
    assert not any(r["method"] == "restrictChatMember" for r in requests)


def test_last_handler_module_exports_burst_handler():
    # The integration point must stay wired to the router module.
    assert hasattr(last_handler, "_handle_burst_spam")
