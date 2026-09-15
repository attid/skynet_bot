import datetime

import pytest
from aiogram import types

from routers.last_handler import router as last_router
from shared.domain.user import SpamStatus
from tests.conftest import RouterTestMiddleware

ANON_ADMIN_BOT_ID = 1087968824  # Telegram's GroupAnonymousBot
SPAM_CAPTION = "Больше видосиков ниже 👇"


def build_message(chat_id, **kwargs):
    return types.Update(
        update_id=kwargs.pop("update_id", 1),
        message=types.Message(
            message_id=kwargs.pop("message_id", 1),
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
            **kwargs,
        ),
    )


def guest_bot_message(chat_id, caller_id, text="Открыть нашего бота", message_id=1, **kwargs):
    return build_message(
        chat_id,
        message_id=message_id,
        from_user=types.User(id=555000, is_bot=True, first_name="82mzow9w", username="spam_guest_bot"),
        guest_bot_caller_user=types.User(id=caller_id, is_bot=False, first_name="Niko", username="niko"),
        text=text,
        **kwargs,
    )


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if last_router.parent_router:
        last_router._parent_router = None


def feed(dp, bot, update):
    return dp.feed_update(bot=bot, update=update)


@pytest.mark.asyncio
async def test_guest_call_from_new_user_banned(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id, caller_id = -100555001, 7001
    await feed(dp, router_app_context.bot, guest_bot_message(chat_id, caller_id, message_id=31, update_id=1))

    requests = mock_telegram.get_requests()
    deleted_ids = {int(r["data"]["message_id"]) for r in requests if r["method"] == "deleteMessage"}
    assert 31 in deleted_ids
    restricts = [r for r in requests if r["method"] == "restrictChatMember"]
    assert restricts and int(restricts[0]["data"]["user_id"]) == caller_id
    assert any(r["method"] == "forwardMessage" for r in requests)
    assert router_app_context.db_service._bot_users[caller_id].user_type == 2


@pytest.mark.asyncio
async def test_guest_call_media_from_new_user_banned(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id, caller_id = -100555002, 7002
    router_app_context.feature_flags.enable(chat_id, "no_first_link")
    update = build_message(
        chat_id,
        message_id=32,
        update_id=1,
        from_user=types.User(id=555000, is_bot=True, first_name="82mzow9w", username="spam_guest_bot"),
        guest_bot_caller_user=types.User(id=caller_id, is_bot=False, first_name="Niko", username="niko"),
        caption=SPAM_CAPTION,
        photo=[types.PhotoSize(file_id="f1", file_unique_id="u1", width=10, height=10)],
    )
    await feed(dp, router_app_context.bot, update)

    requests = mock_telegram.get_requests()
    deleted_ids = {int(r["data"]["message_id"]) for r in requests if r["method"] == "deleteMessage"}
    assert 32 in deleted_ids
    restricts = [r for r in requests if r["method"] == "restrictChatMember"]
    assert restricts and int(restricts[0]["data"]["user_id"]) == caller_id
    assert router_app_context.db_service._bot_users[caller_id].user_type == 2


@pytest.mark.asyncio
async def test_guest_call_from_good_user_allowed(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id, caller_id = -100555003, 7003
    router_app_context.spam_status_service.set_status(caller_id, SpamStatus.GOOD)
    await feed(dp, router_app_context.bot, guest_bot_message(chat_id, caller_id, message_id=33, update_id=1))

    requests = mock_telegram.get_requests()
    assert not any(r["method"] == "deleteMessage" for r in requests)
    assert not any(r["method"] == "restrictChatMember" for r in requests)


@pytest.mark.asyncio
async def test_member_bot_without_binding_passes(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -100555004
    update = build_message(
        chat_id,
        message_id=34,
        update_id=1,
        from_user=types.User(id=555001, is_bot=True, first_name="UsefulBot", username="useful_bot"),
        text="/start",
    )
    await feed(dp, router_app_context.bot, update)

    requests = mock_telegram.get_requests()
    assert not any(r["method"] == "deleteMessage" for r in requests)
    assert not any(r["method"] == "restrictChatMember" for r in requests)


@pytest.mark.asyncio
async def test_anonymous_admin_messages_keep_old_path(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -100555005
    update = build_message(
        chat_id,
        message_id=35,
        update_id=1,
        from_user=types.User(id=ANON_ADMIN_BOT_ID, is_bot=True, first_name="Group"),
        sender_chat=types.Chat(id=chat_id, type="supergroup"),
        text="Объявление от анонимного админа",
    )
    await feed(dp, router_app_context.bot, update)

    requests = mock_telegram.get_requests()
    assert not any(r["method"] == "deleteMessage" for r in requests)
    assert not any(r["method"] == "restrictChatMember" for r in requests)
