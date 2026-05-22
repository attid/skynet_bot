import datetime
import pytest
from aiogram import types

import routers.last_handler as last_handler
from routers.last_handler import (
    router as last_router,
    SpamCheckCallbackData,
    ReplyCallbackData,
    FirstMessageCallbackData,
)
from tests.conftest import RouterTestMiddleware
from tests.fakes import FakeAsyncMethod, FakeSession
from other.constants import BotValueTypes, MTLChats


def build_message_update(chat_id, user_id=123, text="Hello", **kwargs):
    return types.Update(
        update_id=kwargs.pop("update_id", 1),
        message=types.Message(
            message_id=kwargs.pop("message_id", 1),
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
            from_user=types.User(id=user_id, is_bot=False, first_name="User", username="user"),
            text=text,
            **kwargs,
        ),
    )


# --- Existing Tests (Router Integration) ---


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if last_router.parent_router:
        last_router._parent_router = None


@pytest.mark.asyncio
async def test_spam_detection_delegation(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    # Setup conditions using DI services
    chat_id = 123
    router_app_context.feature_flags.enable(chat_id, "no_first_link")

    # Mock services
    router_app_context.antispam_service.check_spam.return_value = True  # Yes spam

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Spammer", username="spammer"),
            text="Spam",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify check_spam called
    assert router_app_context.antispam_service.check_spam.called
    args, _ = router_app_context.antispam_service.check_spam.call_args
    assert isinstance(args[1], FakeSession)


@pytest.mark.asyncio
async def test_mute_enforcement(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = 999
    thread_id = 7
    channel_id = -100999999
    end_time = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()

    # Setup using DI services
    router_app_context.feature_flags.enable(chat_id, "moderate")
    router_app_context.admin_service.set_user_mute(chat_id, thread_id, channel_id, end_time, "Channel SpamChannel")

    # Message from muted channel
    update = types.Update(
        update_id=2,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(
                id=MTLChats.Channel_Bot, is_bot=True, first_name="Channel Bot", username="Channel_Bot"
            ),
            sender_chat=types.Chat(id=channel_id, type="channel", title="SpamChannel"),
            text="I should be deleted",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    del_req = next((r for r in requests if r["method"] == "deleteMessage"), None)
    assert del_req is not None


@pytest.mark.asyncio
async def test_cq_spam_check(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    cb_data = SpamCheckCallbackData(
        message_id=1, chat_id=123, user_id=456, good=False, new_message_id=2, message_thread_id=0
    ).pack()

    update = types.Update(
        update_id=3,
        callback_query=types.CallbackQuery(
            id="cb1",
            chat_instance="ci1",
            from_user=types.User(id=123456, is_bot=False, first_name="Admin", username="admin"),
            message=types.Message(
                message_id=10, date=datetime.datetime.now(), chat=types.Chat(id=123, type="supergroup"), text="Spam rep"
            ),
            data=cb_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "banChatMember" for r in requests)
    assert any("Banned" in r["data"]["text"] for r in requests if r["method"] == "answerCallbackQuery")
    assert any(r["method"] == "editMessageReplyMarkup" for r in requests)
    assert router_app_context.db_service._bot_users[456].user_type == 2


@pytest.mark.asyncio
async def test_cq_spam_check_restore_restrict_and_artifact(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    cb_data = SpamCheckCallbackData(
        message_id=1, chat_id=123, user_id=456, good=True, new_message_id=2, message_thread_id=0
    ).pack()

    update = types.Update(
        update_id=31,
        callback_query=types.CallbackQuery(
            id="cb_restore",
            chat_instance="ci_restore",
            from_user=types.User(id=123456, is_bot=False, first_name="Admin", username="admin"),
            message=types.Message(
                message_id=10,
                date=datetime.datetime.now(),
                chat=types.Chat(id=123, type="supergroup"),
                text="Spam rep",
            ),
            data=cb_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "restrictChatMember" for r in requests)
    assert any(r["method"] == "forwardMessage" for r in requests)
    assert any(
        "bringing the message back" in r["data"]["text"] for r in requests if r["method"] == "answerCallbackQuery"
    )
    assert router_app_context.db_service._bot_users[456].user_type == 1


@pytest.mark.asyncio
async def test_cq_reply_ban(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    cb_data = ReplyCallbackData(message_id=1, chat_id=123, user_id=456).pack()

    update = types.Update(
        update_id=4,
        callback_query=types.CallbackQuery(
            id="cb2",
            chat_instance="ci2",
            from_user=types.User(id=123456, is_bot=False, first_name="Admin", username="admin"),
            message=types.Message(
                message_id=10, date=datetime.datetime.now(), chat=types.Chat(id=123, type="supergroup"), text="Rep ban"
            ),
            data=cb_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "banChatMember" for r in requests)
    assert any(r["method"] == "deleteMessage" for r in requests)


@pytest.mark.asyncio
async def test_cq_first_vote(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    cb_data = FirstMessageCallbackData(user_id=111, message_id=1, spam=True).pack()

    update = types.Update(
        update_id=5,
        callback_query=types.CallbackQuery(
            id="cb3",
            chat_instance="ci3",
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            message=types.Message(
                message_id=10, date=datetime.datetime.now(), chat=types.Chat(id=123, type="supergroup"), text="Vote msg"
            ),
            data=cb_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "editMessageText" for r in requests)
    texts = [r["data"]["text"] for r in requests if r["method"] == "editMessageText"]
    assert any("Spam votes (1)" in t for t in texts)


@pytest.mark.asyncio
async def test_last_check_other_non_text(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = 777
    router_app_context.feature_flags.enable(chat_id, "no_first_link")

    update = types.Update(
        update_id=6,
        message=types.Message(
            message_id=50,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            photo=[types.PhotoSize(file_id="1", file_unique_id="1", width=1, height=1)],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.antispam_service.delete_and_log_spam.called


# --- Additional Router Integration Tests (No Fake Bot/Message) ---


@pytest.mark.asyncio
async def test_spam_check_blocked(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -1001
    router_app_context.feature_flags.enable(chat_id, "no_first_link")

    router_app_context.antispam_service.check_spam.return_value = True

    update = build_message_update(chat_id=chat_id, user_id=123, text="Spam")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    router_app_context.antispam_service.check_spam.assert_awaited_once()

    router_app_context.feature_flags.disable(chat_id, "no_first_link")


@pytest.mark.asyncio
async def test_spam_check_passed(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -1002
    router_app_context.feature_flags.enable(chat_id, "no_first_link")
    router_app_context.feature_flags.enable(chat_id, "listen")

    router_app_context.antispam_service.check_spam.return_value = False

    update = build_message_update(chat_id=chat_id, user_id=123, text="Clean")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    router_app_context.antispam_service.check_spam.assert_awaited_once()

    router_app_context.feature_flags.disable(chat_id, "no_first_link")
    router_app_context.feature_flags.disable(chat_id, "listen")


@pytest.mark.asyncio
async def test_mute_check_active(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -1003
    thread_id = None  # message_thread_id is None for non-topic messages
    router_app_context.feature_flags.enable(chat_id, "moderate")

    future_time = (datetime.datetime.now() + datetime.timedelta(minutes=10)).isoformat()
    router_app_context.admin_service.set_user_mute(chat_id, thread_id, 123, future_time, "User")

    update = build_message_update(chat_id=chat_id, user_id=123, text="Muted")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "deleteMessage" for r in requests)

    router_app_context.feature_flags.disable(chat_id, "moderate")


@pytest.mark.asyncio
async def test_mute_check_expired(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -1004
    thread_id = None
    router_app_context.feature_flags.enable(chat_id, "moderate")

    past_time = (datetime.datetime.now() - datetime.timedelta(minutes=10)).isoformat()
    router_app_context.admin_service.set_user_mute(chat_id, thread_id, 123, past_time, "User")

    update = build_message_update(chat_id=chat_id, user_id=123, text="Ok")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert not any(r["method"] == "deleteMessage" for r in requests)
    # Verify mute was removed from DI service
    assert not router_app_context.admin_service.is_user_muted(chat_id, thread_id, 123)

    router_app_context.feature_flags.disable(chat_id, "moderate")


@pytest.mark.asyncio
async def test_reply_only_violation(mock_telegram, router_app_context, monkeypatch):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -1005
    router_app_context.feature_flags.enable(chat_id, "reply_only")

    mock_sleep = FakeAsyncMethod()
    monkeypatch.setattr(last_handler.asyncio, "sleep", mock_sleep)

    update = build_message_update(chat_id=chat_id, user_id=123, text="No reply")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        r["method"] == "sendMessage" and "режим контроля использования функции ответа" in r["data"]["text"]
        for r in requests
    )

    router_app_context.feature_flags.disable(chat_id, "reply_only")


@pytest.mark.asyncio
async def test_reply_only_allowed(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -1006
    router_app_context.feature_flags.enable(chat_id, "reply_only")

    reply_to = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
        from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
        text="Original",
    )
    update = build_message_update(chat_id=chat_id, user_id=123, text="Reply", reply_to_message=reply_to)
    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert not any(
        r["method"] == "sendMessage" and "режим контроля использования функции ответа" in r["data"]["text"]
        for r in requests
    )

    router_app_context.feature_flags.disable(chat_id, "reply_only")


@pytest.mark.asyncio
async def test_community_vote_prompt(mock_telegram, router_app_context):
    from shared.domain.user import SpamStatus

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -1007
    user_id = 123
    # Set user as REGULAR (type 0) using DI service
    router_app_context.spam_status_service.set_status(user_id, SpamStatus.NEW)
    router_app_context.voting_service.enable_first_vote(chat_id)

    update = build_message_update(chat_id=chat_id, user_id=user_id, text="Hello")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        r["method"] == "sendMessage" and "Please help me detect spam messages" in r["data"]["text"] for r in requests
    )

    router_app_context.voting_service.disable_first_vote(chat_id)


@pytest.mark.asyncio
async def test_notify_message(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -1008
    dest_chat_id = -100555
    # Set up notification using DI service
    router_app_context.notification_service.set_message_notify(chat_id, f"{dest_chat_id}")

    update = build_message_update(chat_id=chat_id, user_id=123, text="Hello")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(dest_chat_id) for r in requests)

    router_app_context.notification_service.disable_message_notify(chat_id)


@pytest.mark.asyncio
async def test_save_last_persists_through_async_db_service(router_app_context):
    chat_id = -1010
    user_id = 123
    router_app_context.feature_flags.enable(chat_id, "save_last_message_date")
    router_app_context.db_service.update_user_chat_date = FakeAsyncMethod()

    message = build_message_update(chat_id=chat_id, user_id=user_id, text="Hello").message

    await last_handler.save_last(message, FakeSession(), app_context=router_app_context)

    router_app_context.db_service.update_user_chat_date.assert_awaited_once_with(user_id, chat_id)


@pytest.mark.asyncio
async def test_reply_only_allowed_saves_message_through_async_db_service(router_app_context):
    chat_id = -1011
    user_id = 123
    router_app_context.db_service.save_message = FakeAsyncMethod()

    reply_to = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
        from_user=types.User(id=user_id, is_bot=False, first_name="User", username="user"),
        text="Original",
    )
    message = build_message_update(chat_id=chat_id, user_id=user_id, text="Reply", reply_to_message=reply_to).message

    await last_handler.cmd_check_reply_only(
        message=message,
        session=FakeSession(),
        bot=router_app_context.bot,
        state=router_app_context.dispatcher.fsm.get_context(
            bot=router_app_context.bot, chat_id=chat_id, user_id=user_id
        ),
        app_context=router_app_context,
    )

    router_app_context.db_service.save_message.assert_awaited_once_with(
        user_id=user_id,
        username="user",
        chat_id=chat_id,
        thread_id=0,
        text="Reply",
    )


@pytest.mark.asyncio
async def test_cmd_tools_persists_pinned_url_through_async_db_service(router_app_context):
    chat_id = -1012
    message = build_message_update(chat_id=chat_id, user_id=123, text="https://eurmtl.me/sign_tools?xdr=abc").message
    message.as_(router_app_context.bot)
    router_app_context.db_service.save_bot_value = FakeAsyncMethod(side_effect=router_app_context.db_service.save_bot_value)
    router_app_context.db_service.load_bot_value = FakeAsyncMethod(side_effect=router_app_context.db_service.load_bot_value)
    router_app_context.stellar_service.check_url_xdr.return_value = ["ok"]

    await last_handler.cmd_tools(message, router_app_context.bot, FakeSession(), app_context=router_app_context)

    assert router_app_context.db_service.save_bot_value.call_args_list[:2] == [
        ((chat_id, BotValueTypes.PinnedUrl, "https://eurmtl.me/sign_tools?xdr=abc"), {}),
        ((chat_id, BotValueTypes.PinnedId, message.message_id), {}),
    ]
    router_app_context.stellar_service.check_url_xdr.assert_awaited_once_with("https://eurmtl.me/sign_tools?xdr=abc")


@pytest.mark.asyncio
async def test_cmd_last_check_persists_bot_user_through_async_db_service(
    mock_telegram, router_app_context, monkeypatch
):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(last_router)

    chat_id = -1013
    user_id = 123
    router_app_context.db_service.save_bot_user = FakeAsyncMethod()
    monkeypatch.setattr(last_handler, "check_alert", FakeAsyncMethod())

    update = build_message_update(chat_id=chat_id, user_id=user_id, text="Hello")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    router_app_context.db_service.save_bot_user.assert_awaited_once_with(user_id, "user", 1)
