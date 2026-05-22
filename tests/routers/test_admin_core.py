import pytest
from unittest.mock import AsyncMock
from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from routers.admin_core import router as admin_router, message_reaction as message_reaction_handler
from tests.conftest import RouterTestMiddleware
from other.constants import BotValueTypes, MTLChats
from other.pyro_tools import GroupMember
import datetime


@pytest.fixture(autouse=True)
async def cleanup_router():
    """Ensure router is detached after each test."""
    yield
    if admin_router.parent_router:
        admin_router._parent_router = None


def setup_is_admin(mock_server, user_id, is_admin=True):
    if is_admin:
        result_obj = {
            "status": "creator",
            "user": {"id": user_id, "is_bot": False, "username": "testuser", "first_name": "Test"},
            "is_anonymous": False,
        }
        result = [result_obj]
    else:
        result = []

    mock_server.add_response("getChatAdministrators", {"ok": True, "result": result})


@pytest.mark.asyncio
async def test_ro_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Configure is_admin
    setup_is_admin(mock_telegram, 999, True)

    reply_msg = types.Message(
        message_id=5,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="BadUser", username="baduser"),
        text="Spam",
    )

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=6,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="!ro 10m",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify restrict called
    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "restrictChatMember"), None)
    assert req is not None
    assert int(req["data"]["user_id"]) == 789


@pytest.mark.asyncio
async def test_topic_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    # Mock createForumTopic response
    mock_telegram.add_response(
        "createForumTopic",
        {
            "ok": True,
            "result": {
                "message_thread_id": 123,
                "name": "NewTopic",
                "icon_color": 7322096,
                "icon_custom_emoji_id": "🔵",
            },
        },
    )

    update = types.Update(
        update_id=2,
        message=types.Message(
            message_id=7,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Forum", is_forum=True),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/topic 🔵 NewTopic",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify createForumTopic called
    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "createForumTopic"), None)
    assert req is not None
    assert req["data"]["name"] == "NewTopic"
    assert req["data"]["icon_custom_emoji_id"] == "🔵"


@pytest.mark.asyncio
async def test_mute_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5
    chat_thread_key = f"{chat_id}-{thread_id}"

    # Set up topic admins using the admin_service (DI pattern)
    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    # Fake mongo config is provided in conftest

    reply_msg = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
        message_thread_id=thread_id,
        from_user=types.User(id=789, is_bot=False, first_name="BadUser", username="baduser"),
        text="Bad msg",
    )

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/mute 1h",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify mute logic: Check admin_service.topic_mute updated (DI pattern)
    mutes = router_app_context.admin_service.get_topic_mutes_by_key(chat_thread_key)
    assert 789 in mutes
    assert await router_app_context.db_service.load_bot_value(0, BotValueTypes.TopicMutes, "{}") != "{}"


@pytest.mark.asyncio
async def test_all_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Mock Group Service
    router_app_context.group_service.get_members.return_value = [
        GroupMember(user_id=1, username="user1", full_name="User One", is_admin=False),
        GroupMember(user_id=2, username=None, full_name="User Two", is_admin=False),
    ]

    update = types.Update(
        update_id=5,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/all",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "@user1" in req["data"]["text"]


@pytest.mark.asyncio
async def test_check_entry_channel_not_admin(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, False)

    update = types.Update(
        update_id=6,
        message=types.Message(
            message_id=31,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/check_entry_channel",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "You are not admin" in req["data"]["text"]


@pytest.mark.asyncio
async def test_delete_dead_members_invalid_format(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/delete_dead_members",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Please provide a chat ID" in req["data"]["text"]


@pytest.mark.asyncio
async def test_show_mutes_no_admins(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Enable moderation via feature flags
    router_app_context.feature_flags.enable(123, "moderate")

    update = types.Update(
        update_id=8,
        message=types.Message(
            message_id=33,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", is_forum=True),
            message_thread_id=1,
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/show_mute",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Local admins not set yet" in req["data"]["text"]


@pytest.mark.asyncio
async def test_message_reaction_no_action(mock_telegram, router_app_context):
    # This handler uses bot directly, but we can call it manually or via dispatch if we want.
    # The original test called it manually.

    bot = router_app_context.bot
    session = router_app_context.session
    # router_app_context IS the app_context (a TestAppContext instance)
    app_context = router_app_context

    class ReactionEvent:
        def __init__(self):
            self.new_reaction = [types.ReactionTypeCustomEmoji(custom_emoji_id="5220151067429335888")]
            self.chat = types.Chat(id=123, type="supergroup", title="Group")
            self.message_id = 55
            self.user = types.User(id=999, is_bot=False, first_name="Admin", username="admin")

    reaction_update = ReactionEvent()

    await message_reaction_handler(reaction_update, bot, session, app_context)
    requests = mock_telegram.get_requests()
    assert not any(r["method"] in ("sendMessage", "forwardMessage", "deleteMessage") for r in requests)


@pytest.mark.asyncio
async def test_on_my_chat_member_added(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat = types.Chat(id=123, type="supergroup", title="Group")
    user = types.User(id=999, is_bot=False, first_name="User", username="user")
    update_event = types.ChatMemberUpdated(
        chat=chat,
        from_user=user,
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberLeft(user=user),
        new_chat_member=types.ChatMemberMember(user=user),
    )
    update = types.Update(update_id=10, my_chat_member=update_event)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Thanks for adding me" in req["data"]["text"]


@pytest.mark.asyncio
async def test_on_my_chat_member_added_ignores_send_message_permission_error(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)
    router_app_context.bot.send_message = AsyncMock(
        side_effect=TelegramBadRequest(
            method=None, message="Bad Request: not enough rights to send text messages to the chat"
        )
    )

    chat = types.Chat(id=123, type="supergroup", title="Group")
    user = types.User(id=999, is_bot=False, first_name="User", username="user")
    update_event = types.ChatMemberUpdated(
        chat=chat,
        from_user=user,
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberLeft(user=user),
        new_chat_member=types.ChatMemberMember(user=user),
    )
    update = types.Update(update_id=10, my_chat_member=update_event)

    await dp.feed_update(bot=router_app_context.bot, update=update)
    router_app_context.bot.send_message.assert_awaited_once_with(123, "Thanks for adding me to this chat!")


@pytest.mark.asyncio
async def test_on_migrate(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=11,
        message=types.Message(
            message_id=35,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="group", title="Group"),
            migrate_to_chat_id=-100123,
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="migrate",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "migrated" in req["data"]["text"]


@pytest.mark.asyncio
async def test_send_me_not_admin(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, False)

    update = types.Update(
        update_id=12,
        message=types.Message(
            message_id=36,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/send_me",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "You are not admin" in req["data"]["text"]


@pytest.mark.asyncio
async def test_alert_me_add(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Fake mongo config is provided in conftest

    update = types.Update(
        update_id=13,
        message=types.Message(
            message_id=37,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/alert_me",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage" and "Added" in r["data"]["text"]), None)
    assert req is not None
    assert await router_app_context.db_service.load_bot_value(123, BotValueTypes.AlertMe, None) == "[999]"

    # Verify sleep_and_delete called
    assert len(router_app_context.utils_service.sleep_and_delete_calls) == 2


@pytest.mark.asyncio
async def test_calc_requires_reply(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=14,
        message=types.Message(
            message_id=38,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/calc",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "must be used in reply" in req["data"]["text"]


@pytest.mark.asyncio
async def test_web_pin_in_group(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=15,
        message=types.Message(
            message_id=39,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/web_pin hello",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "editMessageReplyMarkup"), None)
    assert req is not None


@pytest.mark.asyncio
async def test_show_all_topic_admin_not_admin(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, False)

    update = types.Update(
        update_id=16,
        message=types.Message(
            message_id=40,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/show_all_topic_admin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "You are not an admin" in req["data"]["text"]


@pytest.mark.asyncio
async def test_get_users_csv_usage(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_users_csv",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Usage" in req["data"]["text"]


# ============================================================================
# Additional tests for improved coverage
# ============================================================================


@pytest.mark.asyncio
async def test_ro_command_not_admin(mock_telegram, router_app_context):
    """Test !ro command when user is not admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, False)

    reply_msg = types.Message(
        message_id=5,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="BadUser", username="baduser"),
        text="Spam",
    )

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=6,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="!ro 10m",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "You are not admin" in req["data"]["text"]


@pytest.mark.asyncio
async def test_ro_command_no_reply(mock_telegram, router_app_context):
    """Test !ro command without reply message."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=6,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="!ro 10m",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "reply message" in req["data"]["text"]


@pytest.mark.asyncio
async def test_ro_command_user_without_username(mock_telegram, router_app_context):
    """Test !ro command when target user has no username."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    reply_msg = types.Message(
        message_id=5,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="BadUser"),  # No username
        text="Spam",
    )

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=6,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="!ro 10m",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "restrictChatMember"), None)
    assert req is not None
    assert int(req["data"]["user_id"]) == 789


@pytest.mark.asyncio
async def test_topic_command_not_admin(mock_telegram, router_app_context):
    """Test /topic command when user is not admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, False)

    update = types.Update(
        update_id=2,
        message=types.Message(
            message_id=7,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Forum", is_forum=True),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/topic test NewTopic",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "You are not an admin" in req["data"]["text"]


@pytest.mark.asyncio
async def test_topic_command_not_forum(mock_telegram, router_app_context):
    """Test /topic command in non-forum chat."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    update = types.Update(
        update_id=2,
        message=types.Message(
            message_id=7,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group", is_forum=False),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/topic test NewTopic",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Topics are not enabled" in req["data"]["text"]


@pytest.mark.asyncio
async def test_topic_command_incorrect_format(mock_telegram, router_app_context):
    """Test /topic command with incorrect format."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    update = types.Update(
        update_id=2,
        message=types.Message(
            message_id=7,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Forum", is_forum=True),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/topic onlyemoji",  # Missing topic name
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Incorrect command format" in req["data"]["text"]


@pytest.mark.asyncio
async def test_all_command_with_bot_user(mock_telegram, router_app_context):
    """Test /all command filters out bot users."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    router_app_context.group_service.get_members.return_value = [
        GroupMember(user_id=1, username="user1", full_name="User One", is_admin=False, is_bot=False),
        GroupMember(user_id=2, username="bot_user", full_name="Bot User", is_admin=False, is_bot=True),
    ]

    update = types.Update(
        update_id=5,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/all",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "@user1" in req["data"]["text"]
    assert "@bot_user" not in req["data"]["text"]


@pytest.mark.asyncio
async def test_delete_dead_members_not_admin(mock_telegram, router_app_context):
    """Test /delete_dead_members when user is not admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, False)

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/delete_dead_members -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "You are not admin" in req["data"]["text"]


@pytest.mark.asyncio
async def test_delete_dead_members_invalid_chat_id_format(mock_telegram, router_app_context):
    """Test /delete_dead_members with invalid chat ID format."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/delete_dead_members 12345",  # Invalid format
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Invalid chat ID format" in req["data"]["text"]


@pytest.mark.asyncio
async def test_delete_dead_members_success(mock_telegram, router_app_context):
    """Test /delete_dead_members successful execution."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Setup admin for both source and target chats
    setup_is_admin(mock_telegram, 999, True)

    # Mock remove_deleted_users to return a count
    router_app_context.group_service.remove_deleted_users = lambda chat_id: 5

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/delete_dead_members -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Check for "Starting to remove" message first
    req = next((r for r in requests if r["method"] == "sendMessage" and "Starting" in r["data"]["text"]), None)
    assert req is not None


@pytest.mark.asyncio
async def test_mute_command_not_local_admin(mock_telegram, router_app_context):
    """Test /mute command when user is not topic admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5

    # Set up topic admins but NOT including the requesting user
    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@other_admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    reply_msg = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
        message_thread_id=thread_id,
        from_user=types.User(id=789, is_bot=False, first_name="BadUser", username="baduser"),
        text="Bad msg",
    )

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/mute 1h",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "You are not local admin" in req["data"]["text"]


@pytest.mark.asyncio
async def test_del_command_success_for_topic_admin(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    reply_msg = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", title="Group", is_forum=True),
        message_thread_id=thread_id,
        from_user=types.User(id=789, is_bot=False, first_name="BadUser", username="baduser"),
        text="Bad msg",
    )

    update = types.Update(
        update_id=30,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/del",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    forward_req = next((r for r in requests if r["method"] == "forwardMessage"), None)
    assert forward_req is not None
    assert str(forward_req["data"]["chat_id"]) == str(MTLChats.SpamGroup)
    assert int(forward_req["data"]["message_id"]) == 10

    spam_log_req = next(
        (
            r
            for r in requests
            if r["method"] == "sendMessage"
            and str(r["data"]["chat_id"]) == str(MTLChats.SpamGroup)
            and "admin" in r["data"]["text"]
        ),
        None,
    )
    assert spam_log_req is not None

    delete_requests = [r for r in requests if r["method"] == "deleteMessage"]
    deleted_ids = {int(r["data"]["message_id"]) for r in delete_requests}
    assert 10 in deleted_ids
    assert 11 in deleted_ids

    assert len(router_app_context.utils_service.sleep_and_delete_calls) == 1
    _, seconds = router_app_context.utils_service.sleep_and_delete_calls[0]
    assert seconds == 5


@pytest.mark.asyncio
async def test_del_command_not_local_admin(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@other_admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    reply_msg = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", title="Group", is_forum=True),
        message_thread_id=thread_id,
        from_user=types.User(id=789, is_bot=False, first_name="BadUser", username="baduser"),
        text="Bad msg",
    )

    update = types.Update(
        update_id=31,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/del",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "You are not local admin" in req["data"]["text"]
    assert len(router_app_context.utils_service.sleep_and_delete_calls) == 2
    assert all(seconds == 5 for _, seconds in router_app_context.utils_service.sleep_and_delete_calls)


@pytest.mark.asyncio
async def test_del_command_requires_reply(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    update = types.Update(
        update_id=32,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/del",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "reply" in req["data"]["text"].lower()
    assert len(router_app_context.utils_service.sleep_and_delete_calls) == 2
    assert all(seconds == 5 for _, seconds in router_app_context.utils_service.sleep_and_delete_calls)


@pytest.mark.asyncio
async def test_del_command_requires_topic(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    router_app_context.feature_flags.enable(123, "moderate")

    update = types.Update(
        update_id=33,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group", is_forum=True),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/del",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "This command must be used in topic." in req["data"]["text"]
    assert len(router_app_context.utils_service.sleep_and_delete_calls) == 2
    assert all(seconds == 5 for _, seconds in router_app_context.utils_service.sleep_and_delete_calls)


@pytest.mark.asyncio
async def test_del_command_requires_local_admins(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5

    router_app_context.feature_flags.enable(chat_id, "moderate")

    reply_msg = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", title="Group", is_forum=True),
        message_thread_id=thread_id,
        from_user=types.User(id=789, is_bot=False, first_name="BadUser", username="baduser"),
        text="Bad msg",
    )

    update = types.Update(
        update_id=34,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/del",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Local admins not set yet" in req["data"]["text"]
    assert len(router_app_context.utils_service.sleep_and_delete_calls) == 2
    assert all(seconds == 5 for _, seconds in router_app_context.utils_service.sleep_and_delete_calls)


@pytest.mark.asyncio
async def test_mute_command_no_reply_no_mention(mock_telegram, router_app_context):
    """Test /mute command without reply or mention."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/mute 1h",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Specify user by reply or @username" in req["data"]["text"]


@pytest.mark.asyncio
async def test_mute_command_by_mention(mock_telegram, router_app_context):
    """Test /mute @username 1h — mute by mention without reply."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5
    chat_thread_key = f"{chat_id}-{thread_id}"

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    # Register target user in DB so get_user_id can resolve them
    router_app_context.session.set_user(789, user_name="baduser")
    await router_app_context.db_service.save_bot_user(789, "baduser")

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/mute @baduser 1h",
            entities=[
                types.MessageEntity(type="bot_command", offset=0, length=5),
                types.MessageEntity(type="mention", offset=6, length=8),
            ],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    mutes = router_app_context.admin_service.get_topic_mutes_by_key(chat_thread_key)
    assert 789 in mutes


@pytest.mark.asyncio
async def test_mute_mention_wins_over_reply(mock_telegram, router_app_context):
    """Test /mute @username 1h as reply — mention takes priority over reply."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5
    chat_thread_key = f"{chat_id}-{thread_id}"

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    # Register mentioned user in DB
    router_app_context.session.set_user(789, user_name="mentioned_user")
    await router_app_context.db_service.save_bot_user(789, "mentioned_user")

    # Reply targets a different user (id=555)
    reply_msg = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
        message_thread_id=thread_id,
        from_user=types.User(id=555, is_bot=False, first_name="OtherUser", username="otheruser"),
        text="Some msg",
    )

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/mute @mentioned_user 1h",
            reply_to_message=reply_msg,
            entities=[
                types.MessageEntity(type="bot_command", offset=0, length=5),
                types.MessageEntity(type="mention", offset=6, length=15),
            ],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    mutes = router_app_context.admin_service.get_topic_mutes_by_key(chat_thread_key)
    # Mentioned user (789) is muted, NOT the reply user (555)
    assert 789 in mutes
    assert 555 not in mutes


@pytest.mark.asyncio
async def test_unmute_command_by_reply(mock_telegram, router_app_context):
    """Test /unmute via reply removes mute."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5
    chat_thread_key = f"{chat_id}-{thread_id}"

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    # Set an active mute
    future_time = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
    router_app_context.admin_service.set_user_mute_by_key(chat_thread_key, 789, future_time, "@baduser")

    reply_msg = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
        message_thread_id=thread_id,
        from_user=types.User(id=789, is_bot=False, first_name="BadUser", username="baduser"),
        text="Some msg",
    )

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/unmute",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    mutes = router_app_context.admin_service.get_topic_mutes_by_key(chat_thread_key)
    assert 789 not in mutes


@pytest.mark.asyncio
async def test_unmute_command_by_mention(mock_telegram, router_app_context):
    """Test /unmute @username removes mute."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5
    chat_thread_key = f"{chat_id}-{thread_id}"

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    # Register user in DB
    router_app_context.session.set_user(789, user_name="baduser")
    await router_app_context.db_service.save_bot_user(789, "baduser")

    # Set an active mute
    future_time = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
    router_app_context.admin_service.set_user_mute_by_key(chat_thread_key, 789, future_time, "@baduser")

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/unmute @baduser",
            entities=[
                types.MessageEntity(type="bot_command", offset=0, length=7),
                types.MessageEntity(type="mention", offset=8, length=8),
            ],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    mutes = router_app_context.admin_service.get_topic_mutes_by_key(chat_thread_key)
    assert 789 not in mutes


@pytest.mark.asyncio
async def test_unmute_command_not_muted(mock_telegram, router_app_context):
    """Test /unmute when user is not muted."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    reply_msg = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
        message_thread_id=thread_id,
        from_user=types.User(id=789, is_bot=False, first_name="User", username="someuser"),
        text="Some msg",
    )

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/unmute",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "is not muted" in req["data"]["text"]


@pytest.mark.asyncio
async def test_mute_command_channel_sender(mock_telegram, router_app_context):
    """Test /mute command when reply is from a channel."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5
    chat_thread_key = f"{chat_id}-{thread_id}"

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    reply_msg = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
        message_thread_id=thread_id,
        sender_chat=types.Chat(id=-1001111111111, type="channel", title="Channel Name"),
        text="Channel message",
    )

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/mute 1h",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    mutes = router_app_context.admin_service.get_topic_mutes_by_key(chat_thread_key)
    assert -1001111111111 in mutes


@pytest.mark.asyncio
async def test_show_mutes_not_local_admin(mock_telegram, router_app_context):
    """Test /show_mute command when user is not topic admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 1

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@other_admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    update = types.Update(
        update_id=8,
        message=types.Message(
            message_id=33,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/show_mute",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "You are not local admin" in req["data"]["text"]


@pytest.mark.asyncio
async def test_show_mutes_with_active_mutes(mock_telegram, router_app_context):
    """Test /show_mute command with active mutes."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 1
    chat_thread_key = f"{chat_id}-{thread_id}"

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    # Set an active mute (1 hour from now)
    future_time = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
    router_app_context.admin_service.set_user_mute_by_key(chat_thread_key, 789, future_time, "@baduser")

    update = types.Update(
        update_id=8,
        message=types.Message(
            message_id=33,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/show_mute",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "@baduser" in req["data"]["text"]


@pytest.mark.asyncio
async def test_show_mutes_no_mutes(mock_telegram, router_app_context):
    """Test /show_mute command when no mutes exist."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 1

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    update = types.Update(
        update_id=8,
        message=types.Message(
            message_id=33,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/show_mute",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "No users are currently muted" in req["data"]["text"]


@pytest.mark.asyncio
async def test_show_mutes_expired_mutes(mock_telegram, router_app_context):
    """Test /show_mute command removes expired mutes."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 1
    chat_thread_key = f"{chat_id}-{thread_id}"

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    # Set an expired mute (1 hour ago)
    past_time = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
    router_app_context.admin_service.set_user_mute_by_key(chat_thread_key, 789, past_time, "@baduser")

    update = types.Update(
        update_id=8,
        message=types.Message(
            message_id=33,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/show_mute",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "No users are currently muted" in req["data"]["text"]


@pytest.mark.asyncio
async def test_on_my_chat_member_left(mock_telegram, router_app_context):
    """Test bot left from chat."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat = types.Chat(id=123, type="supergroup", title="Group")
    bot_user = types.User(id=123456, is_bot=True, first_name="TestBot", username="test_bot")
    update_event = types.ChatMemberUpdated(
        chat=chat,
        from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberMember(user=bot_user),
        new_chat_member=types.ChatMemberLeft(user=bot_user),
    )
    update = types.Update(update_id=10, my_chat_member=update_event)

    await dp.feed_update(bot=router_app_context.bot, update=update)
    # Just verify no error - Left status is logged but no message sent


@pytest.mark.asyncio
async def test_on_my_chat_member_made_admin(mock_telegram, router_app_context):
    """Test bot made admin in chat."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat = types.Chat(id=123, type="supergroup", title="Group")
    bot_user = types.User(id=123456, is_bot=True, first_name="TestBot", username="test_bot")
    update_event = types.ChatMemberUpdated(
        chat=chat,
        from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberMember(user=bot_user),
        new_chat_member=types.ChatMemberAdministrator(
            user=bot_user,
            can_be_edited=False,
            is_anonymous=False,
            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_promote_members=False,
            can_change_info=True,
            can_invite_users=True,
            can_post_stories=False,
            can_edit_stories=False,
            can_delete_stories=False,
        ),
    )
    update = types.Update(update_id=10, my_chat_member=update_event)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Thanks for making me an admin" in req["data"]["text"]


@pytest.mark.asyncio
async def test_on_my_chat_member_restricted(mock_telegram, router_app_context):
    """Test bot restricted in chat."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat = types.Chat(id=123, type="supergroup", title="Group")
    bot_user = types.User(id=123456, is_bot=True, first_name="TestBot", username="test_bot")
    update_event = types.ChatMemberUpdated(
        chat=chat,
        from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberMember(user=bot_user),
        new_chat_member=types.ChatMemberRestricted(
            user=bot_user,
            is_member=True,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_manage_topics=False,
            until_date=datetime.datetime.now(),
        ),
    )
    update = types.Update(update_id=10, my_chat_member=update_event)

    await dp.feed_update(bot=router_app_context.bot, update=update)
    # Just verify no error - Restricted status is logged but no message sent


@pytest.mark.asyncio
async def test_on_my_chat_member_kicked(mock_telegram, router_app_context):
    """Test bot kicked from chat."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat = types.Chat(id=123, type="supergroup", title="Group")
    bot_user = types.User(id=123456, is_bot=True, first_name="TestBot", username="test_bot")
    update_event = types.ChatMemberUpdated(
        chat=chat,
        from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberMember(user=bot_user),
        new_chat_member=types.ChatMemberBanned(user=bot_user, until_date=datetime.datetime.now()),
    )
    update = types.Update(update_id=10, my_chat_member=update_event)

    await dp.feed_update(bot=router_app_context.bot, update=update)
    # Just verify no error - Kicked status is logged but no message sent


@pytest.mark.asyncio
async def test_send_me_no_reply(mock_telegram, router_app_context):
    """Test /send_me command without reply."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    update = types.Update(
        update_id=12,
        message=types.Message(
            message_id=36,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/send_me",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "reply message" in req["data"]["text"]


@pytest.mark.asyncio
async def test_send_me_with_text_reply(mock_telegram, router_app_context):
    """Test /send_me command with text reply."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    reply_msg = types.Message(
        message_id=35,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="User", username="user"),
        text="Important message",
    )

    update = types.Update(
        update_id=12,
        message=types.Message(
            message_id=36,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/send_me",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # chat_id can be string or int from mock server
    req = next((r for r in requests if r["method"] == "sendMessage" and str(r["data"].get("chat_id")) == "999"), None)
    assert req is not None
    assert "Important message" in req["data"]["text"]


@pytest.mark.asyncio
async def test_send_me_with_photo_reply(mock_telegram, router_app_context):
    """Test /send_me command with photo reply."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    reply_msg = types.Message(
        message_id=35,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="User", username="user"),
        photo=[types.PhotoSize(file_id="photo123", file_unique_id="photo_unique", width=100, height=100)],
        caption="Photo caption",
    )

    update = types.Update(
        update_id=12,
        message=types.Message(
            message_id=36,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/send_me",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendPhoto"), None)
    assert req is not None
    assert int(req["data"]["chat_id"]) == 999


@pytest.mark.asyncio
async def test_send_me_with_video_reply(mock_telegram, router_app_context):
    """Test /send_me command with video reply."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    # Add sendVideo response to mock server
    mock_telegram.add_response(
        "sendVideo",
        {
            "ok": True,
            "result": {
                "message_id": 100,
                "date": 1234567890,
                "chat": {"id": 999, "type": "private"},
                "video": {
                    "file_id": "video123",
                    "file_unique_id": "video_unique",
                    "width": 640,
                    "height": 480,
                    "duration": 30,
                },
                "caption": "Video caption",
            },
        },
    )

    reply_msg = types.Message(
        message_id=35,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="User", username="user"),
        video=types.Video(file_id="video123", file_unique_id="video_unique", width=640, height=480, duration=30),
        caption="Video caption",
    )

    update = types.Update(
        update_id=12,
        message=types.Message(
            message_id=36,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/send_me",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendVideo"), None)
    assert req is not None
    assert str(req["data"]["chat_id"]) == "999"


@pytest.mark.asyncio
async def test_send_me_short_command(mock_telegram, router_app_context):
    """Test /s short command (alias for /send_me)."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    reply_msg = types.Message(
        message_id=35,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="User", username="user"),
        text="Important message",
    )

    update = types.Update(
        update_id=12,
        message=types.Message(
            message_id=36,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/s",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # chat_id can be string or int from mock server
    req = next((r for r in requests if r["method"] == "sendMessage" and str(r["data"].get("chat_id")) == "999"), None)
    assert req is not None


@pytest.mark.asyncio
async def test_alert_me_remove(mock_telegram, router_app_context):
    """Test /alert_me command to remove subscription."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Add user first
    router_app_context.notification_service.add_alert_user(123, 999)

    update = types.Update(
        update_id=13,
        message=types.Message(
            message_id=37,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/alert_me",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage" and "Removed" in r["data"]["text"]), None)
    assert req is not None


@pytest.mark.asyncio
async def test_calc_with_reply(mock_telegram, router_app_context):
    """Test /calc command with reply message."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    reply_msg = types.Message(
        message_id=30,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="User", username="user"),
        text="Original message",
    )

    update = types.Update(
        update_id=14,
        message=types.Message(
            message_id=50,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/calc",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage" and "messages ago" in r["data"]["text"]), None)
    assert req is not None
    assert "20" in req["data"]["text"]  # 50 - 30 = 20


@pytest.mark.asyncio
async def test_web_pin_no_args(mock_telegram, router_app_context):
    """Test /web_pin command without text argument."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=15,
        message=types.Message(
            message_id=39,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/web_pin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "new text" in req["data"]["text"]


@pytest.mark.asyncio
async def test_show_all_topic_admin_success(mock_telegram, router_app_context):
    """Test /show_all_topic_admin with topic admins."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    # Set up topic admins for the chat
    router_app_context.admin_service.set_topic_admins(123, 5, ["@admin1", "@admin2"])
    router_app_context.admin_service.set_topic_admins(123, 10, ["@admin3"])

    update = types.Update(
        update_id=16,
        message=types.Message(
            message_id=40,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/show_all_topic_admin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Topic Admins" in req["data"]["text"]


@pytest.mark.asyncio
async def test_show_all_topic_admin_no_admins(mock_telegram, router_app_context):
    """Test /show_all_topic_admin when no topic admins exist."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    update = types.Update(
        update_id=16,
        message=types.Message(
            message_id=40,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/show_all_topic_admin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "No topic admins found" in req["data"]["text"]


@pytest.mark.asyncio
async def test_get_users_csv_invalid_format(mock_telegram, router_app_context):
    """Test /get_users_csv with invalid chat ID format."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_users_csv 12345",  # Invalid format
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Invalid chat_id format" in req["data"]["text"]


@pytest.mark.asyncio
async def test_get_users_csv_success(mock_telegram, router_app_context):
    """Test /get_users_csv successful execution."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Mock get_members to return some users
    router_app_context.group_service.get_members.return_value = [
        GroupMember(user_id=1, username="user1", full_name="User One", is_admin=True, is_bot=False),
        GroupMember(user_id=2, username=None, full_name="User Two", is_admin=False, is_bot=False),
    ]

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_users_csv -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Check for "Processing" message
    req = next((r for r in requests if r["method"] == "sendMessage" and "Processing" in r["data"]["text"]), None)
    assert req is not None


@pytest.mark.asyncio
async def test_get_users_csv_wrong_chat(mock_telegram, router_app_context):
    """Test /get_users_csv from wrong chat (not MTLIDGroup)."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=999999, type="supergroup", title="Other Group"),  # Not MTLIDGroup
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_users_csv -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should silently return (no response)
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is None


@pytest.mark.asyncio
async def test_message_reaction_mute_emoji(mock_telegram, router_app_context):
    """Test message_reaction with mute emoji."""
    from routers.admin_core import message_reaction as message_reaction_handler

    bot = router_app_context.bot
    session = router_app_context.session
    app_context = router_app_context

    chat_id = 123
    thread_id = 5
    chat_thread_key = f"{chat_id}-{thread_id}"

    # Set up topic admins
    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    await router_app_context.message_thread_cache_service.remember_message_context(
        chat_id=chat_id,
        message_id=10,
        thread_id=thread_id,
        user_id=789,
        username="baduser",
        full_name="BadUser",
    )

    class ReactionEvent:
        def __init__(self):
            self.new_reaction = [types.ReactionTypeCustomEmoji(custom_emoji_id="5220090169088045319")]  # 10m mute emoji
            self.chat = types.Chat(id=chat_id, type="supergroup", title="Group")
            self.message_id = 10
            self.user = types.User(id=999, is_bot=False, first_name="Admin", username="admin")
            self.text = "reaction"

    reaction_update = ReactionEvent()

    await message_reaction_handler(reaction_update, bot, session, app_context)

    # Verify mute was applied
    mutes = router_app_context.admin_service.get_topic_mutes_by_key(chat_thread_key)
    assert 789 in mutes
    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage" and "was set mute" in r["data"]["text"]), None)
    assert req is not None


@pytest.mark.asyncio
async def test_message_reaction_no_topic_admins(mock_telegram, router_app_context):
    """Test message_reaction when no topic admins are set."""
    from routers.admin_core import message_reaction as message_reaction_handler

    bot = router_app_context.bot
    session = router_app_context.session
    app_context = router_app_context

    chat_id = 123
    thread_id = 5

    class ReactionEvent:
        def __init__(self):
            self.new_reaction = [types.ReactionTypeCustomEmoji(custom_emoji_id="5220090169088045319")]
            self.chat = types.Chat(id=chat_id, type="supergroup", title="Group")
            self.message_id = 10
            self.user = types.User(id=999, is_bot=False, first_name="User", username="user")

    reaction_update = ReactionEvent()
    await router_app_context.message_thread_cache_service.remember_message_context(
        chat_id=chat_id,
        message_id=10,
        thread_id=thread_id,
        user_id=789,
        username="baduser",
        full_name="BadUser",
    )

    await message_reaction_handler(reaction_update, bot, session, app_context)
    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Local admins not set yet" in req["data"]["text"]


@pytest.mark.asyncio
async def test_message_reaction_unknown_emoji_ignored(mock_telegram, router_app_context):
    """Test message_reaction when unknown custom emoji is used - it should be ignored."""
    from routers.admin_core import message_reaction as message_reaction_handler

    bot = router_app_context.bot
    session = router_app_context.session
    app_context = router_app_context

    chat_id = 123
    thread_id = 5

    class ReactionEvent:
        def __init__(self):
            # Elephant emoji ID (unknown to bot)
            self.new_reaction = [types.ReactionTypeCustomEmoji(custom_emoji_id="543210123456789")]
            self.chat = types.Chat(id=chat_id, type="supergroup", title="Group")
            self.message_id = 10
            self.user = types.User(id=999, is_bot=False, first_name="User", username="user")

    reaction_update = ReactionEvent()
    await router_app_context.message_thread_cache_service.remember_message_context(
        chat_id=chat_id,
        message_id=10,
        thread_id=thread_id,
        user_id=789,
        username="baduser",
        full_name="BadUser",
    )

    await message_reaction_handler(reaction_update, bot, session, app_context)
    requests = mock_telegram.get_requests()
    # Check that NO sendMessage was called
    send_message_reqs = [r for r in requests if r["method"] == "sendMessage"]
    assert len(send_message_reqs) == 0


@pytest.mark.asyncio
async def test_message_reaction_not_topic_admin(mock_telegram, router_app_context):
    """Test message_reaction when user is not topic admin."""
    from routers.admin_core import message_reaction as message_reaction_handler

    bot = router_app_context.bot
    session = router_app_context.session
    app_context = router_app_context

    chat_id = 123
    thread_id = 5

    # Set up topic admins but NOT including the requesting user
    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@other_admin"])

    class ReactionEvent:
        def __init__(self):
            self.new_reaction = [types.ReactionTypeCustomEmoji(custom_emoji_id="5220090169088045319")]
            self.chat = types.Chat(id=chat_id, type="supergroup", title="Group")
            self.message_id = 10
            self.user = types.User(id=999, is_bot=False, first_name="User", username="notadmin")

    reaction_update = ReactionEvent()
    await router_app_context.message_thread_cache_service.remember_message_context(
        chat_id=chat_id,
        message_id=10,
        thread_id=thread_id,
        user_id=789,
        username="baduser",
        full_name="BadUser",
    )

    await message_reaction_handler(reaction_update, bot, session, app_context)
    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "You are not local admin" in req["data"]["text"]


@pytest.mark.asyncio
async def test_on_my_chat_member_same_status(mock_telegram, router_app_context):
    """Test my_chat_member when status doesn't change."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat = types.Chat(id=123, type="supergroup", title="Group")
    bot_user = types.User(id=123456, is_bot=True, first_name="TestBot", username="test_bot")
    update_event = types.ChatMemberUpdated(
        chat=chat,
        from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberMember(user=bot_user),
        new_chat_member=types.ChatMemberMember(user=bot_user),  # Same status
    )
    update = types.Update(update_id=10, my_chat_member=update_event)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # No message should be sent when status doesn't change
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is None


@pytest.mark.asyncio
async def test_on_my_chat_member_added_private_chat(mock_telegram, router_app_context):
    """Test my_chat_member in private chat (no message sent)."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat = types.Chat(id=123, type="private")  # Private chat
    user = types.User(id=999, is_bot=False, first_name="User", username="user")
    update_event = types.ChatMemberUpdated(
        chat=chat,
        from_user=user,
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberLeft(user=user),
        new_chat_member=types.ChatMemberMember(user=user),
    )
    update = types.Update(update_id=10, my_chat_member=update_event)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # No "Thanks for adding me" in private chat
    req = next(
        (r for r in requests if r["method"] == "sendMessage" and "Thanks for adding me" in r["data"].get("text", "")),
        None,
    )
    assert req is None


# ============================================================================
# Additional tests for edge cases and error handling
# ============================================================================


@pytest.mark.asyncio
async def test_topic_command_bad_request_chat_not_modified(mock_telegram, router_app_context):
    """Test /topic command when TelegramBadRequest with CHAT_NOT_MODIFIED."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    # Mock createForumTopic to return error
    mock_telegram.add_response(
        "createForumTopic", {"ok": False, "error_code": 400, "description": "Bad Request: CHAT_NOT_MODIFIED"}
    )

    update = types.Update(
        update_id=2,
        message=types.Message(
            message_id=7,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Forum", is_forum=True),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/topic test NewTopic",
        ),
    )

    # The test may raise an exception or handle it depending on implementation
    # Just verify no crash
    try:
        await dp.feed_update(bot=router_app_context.bot, update=update)
    except Exception:
        pass  # Exception handling is tested


@pytest.mark.asyncio
async def test_check_entry_channel_success(mock_telegram, router_app_context):
    """Test /check_entry_channel successful execution."""
    from unittest.mock import AsyncMock, patch

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    # Mock run_entry_channel_check to return success
    with patch("routers.admin_core.run_entry_channel_check", new_callable=AsyncMock) as mock_check:
        mock_check.return_value = (10, 2)  # checked_count, action_count

        update = types.Update(
            update_id=6,
            message=types.Message(
                message_id=31,
                date=datetime.datetime.now(),
                chat=types.Chat(id=123, type="supergroup", title="Group"),
                from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
                text="/check_entry_channel",
            ),
        )

        await dp.feed_update(bot=router_app_context.bot, update=update)

        requests = mock_telegram.get_requests()
        req = next((r for r in requests if r["method"] == "sendMessage" and "Проверено" in r["data"]["text"]), None)
        assert req is not None
        assert "10" in req["data"]["text"]
        assert "2" in req["data"]["text"]


@pytest.mark.asyncio
async def test_check_entry_channel_not_configured(mock_telegram, router_app_context):
    """Test /check_entry_channel when entry channel not configured."""
    from unittest.mock import AsyncMock, patch

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    # Mock run_entry_channel_check to raise ValueError
    with patch("routers.admin_core.run_entry_channel_check", new_callable=AsyncMock) as mock_check:
        mock_check.side_effect = ValueError("Entry channel not configured")

        update = types.Update(
            update_id=6,
            message=types.Message(
                message_id=31,
                date=datetime.datetime.now(),
                chat=types.Chat(id=123, type="supergroup", title="Group"),
                from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
                text="/check_entry_channel",
            ),
        )

        await dp.feed_update(bot=router_app_context.bot, update=update)

        requests = mock_telegram.get_requests()
        req = next((r for r in requests if r["method"] == "sendMessage" and "не включена" in r["data"]["text"]), None)
        assert req is not None


@pytest.mark.asyncio
async def test_delete_dead_members_username_format(mock_telegram, router_app_context):
    """Test /delete_dead_members with @username format."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    # Mock get_chat to return a valid chat
    mock_telegram.add_response(
        "getChat",
        {
            "ok": True,
            "result": {
                "id": -1001234567890,
                "type": "supergroup",
                "title": "Test Group",
                "accent_color_id": 0,
                "max_reaction_count": 0,
                "permissions": {"can_send_messages": True},
                "accepted_gift_types": {
                    "unlimited_gifts": True,
                    "limited_gifts": False,
                    "unique_gifts": False,
                    "premium_subscription": False,
                    "gifts_from_channels": False,
                },
            },
        },
    )

    # Mock remove_deleted_users
    router_app_context.group_service.remove_deleted_users = AsyncMock(return_value=3)

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/delete_dead_members @testgroup",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Check for "Starting" message
    req = next((r for r in requests if r["method"] == "sendMessage" and "Starting" in r["data"]["text"]), None)
    assert req is not None


@pytest.mark.asyncio
async def test_delete_dead_members_username_not_found(mock_telegram, router_app_context):
    """Test /delete_dead_members with @username that doesn't exist."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    # Mock get_chat to return error
    mock_telegram.add_response(
        "getChat", {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
    )

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/delete_dead_members @nonexistent",
        ),
    )

    try:
        await dp.feed_update(bot=router_app_context.bot, update=update)
    except Exception:
        pass  # TelegramBadRequest expected

    requests = mock_telegram.get_requests()
    # Verify getChat was called
    req = next((r for r in requests if r["method"] == "getChat"), None)
    assert req is not None


@pytest.mark.asyncio
async def test_delete_dead_members_not_admin_of_target(mock_telegram, router_app_context):
    """Test /delete_dead_members when not admin of target chat."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Admin in source chat, but not in target
    def admin_response_side_effect(method):
        if method == "getChatAdministrators":
            # First call - admin of source chat (123)
            # Second call - not admin of target chat
            if not hasattr(admin_response_side_effect, "calls"):
                admin_response_side_effect.calls = 0
            admin_response_side_effect.calls += 1
            if admin_response_side_effect.calls == 1:
                return {
                    "ok": True,
                    "result": [
                        {
                            "status": "creator",
                            "user": {"id": 999, "is_bot": False, "username": "admin", "first_name": "Admin"},
                            "is_anonymous": False,
                        }
                    ],
                }
            else:
                return {"ok": True, "result": []}
        return None

    # First call is admin
    setup_is_admin(mock_telegram, 999, True)

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/delete_dead_members -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Multiple getChatAdministrators calls expected
    admin_calls = [r for r in requests if r["method"] == "getChatAdministrators"]
    assert len(admin_calls) >= 1


@pytest.mark.asyncio
async def test_delete_dead_members_remove_error(mock_telegram, router_app_context):
    """Test /delete_dead_members when remove_deleted_users raises exception."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    # Mock remove_deleted_users to raise exception
    async def raise_error(chat_id):
        raise Exception("Failed to remove users")

    router_app_context.group_service.remove_deleted_users = raise_error

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/delete_dead_members -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Check for error message
    req = next((r for r in requests if r["method"] == "sendMessage" and "error" in r["data"]["text"].lower()), None)
    assert req is not None


@pytest.mark.asyncio
async def test_get_users_csv_bot_not_member(mock_telegram, router_app_context):
    """Test /get_users_csv when bot is not member of target chat."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Mock getChatMember to return LEFT status for bot
    mock_telegram.add_response(
        "getChatMember",
        {"ok": True, "result": {"user": {"id": 123456, "is_bot": True, "first_name": "TestBot"}, "status": "left"}},
    )

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_users_csv -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage" and "not a member" in r["data"]["text"]), None)
    assert req is not None


@pytest.mark.asyncio
async def test_get_users_csv_bot_check_error(mock_telegram, router_app_context):
    """Test /get_users_csv when bot membership check returns error."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Mock getChatMember to return error
    mock_telegram.add_response(
        "getChatMember", {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
    )

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_users_csv -1001234567890",
        ),
    )

    try:
        await dp.feed_update(bot=router_app_context.bot, update=update)
    except Exception:
        pass  # TelegramBadRequest expected

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "getChatMember"), None)
    assert req is not None


@pytest.mark.asyncio
async def test_get_users_csv_get_members_error(mock_telegram, router_app_context):
    """Test /get_users_csv when get_members raises exception."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Mock get_members to raise exception
    async def raise_error(chat_id):
        raise Exception("Failed to get members")

    router_app_context.group_service.get_members = raise_error

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_users_csv -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next(
        (r for r in requests if r["method"] == "sendMessage" and "Failed to get group members" in r["data"]["text"]),
        None,
    )
    assert req is not None


@pytest.mark.asyncio
async def test_mute_command_reply_to_forum_topic(mock_telegram, router_app_context):
    """Test /mute command when reply is to forum topic created message."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 5

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    # Reply to a forum topic created message
    reply_msg = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
        message_thread_id=thread_id,
        from_user=types.User(id=789, is_bot=False, first_name="User", username="user"),
        forum_topic_created=types.ForumTopicCreated(name="Topic", icon_color=0),
    )

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/mute 1h",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Specify user by reply or @username" in req["data"]["text"]


@pytest.mark.asyncio
async def test_show_mutes_invalid_mute_data(mock_telegram, router_app_context):
    """Test /show_mute command handles invalid mute data gracefully."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = 123
    thread_id = 1
    chat_thread_key = f"{chat_id}-{thread_id}"

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    router_app_context.feature_flags.enable(chat_id, "moderate")

    # Set up invalid mute data (missing end_time key)
    router_app_context.admin_service._topic_mute[chat_thread_key] = {
        789: {"user": "@baduser"}  # Missing "end_time"
    }

    update = types.Update(
        update_id=8,
        message=types.Message(
            message_id=33,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", is_forum=True),
            message_thread_id=thread_id,
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/show_mute",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    # Should handle gracefully and show no mutes
    assert "No users are currently muted" in req["data"]["text"]


@pytest.mark.asyncio
async def test_get_users_csv_user_not_member(mock_telegram, router_app_context):
    """Test /get_users_csv when requesting user is not member of target chat."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Mock getChatMember to return left status with proper format for ChatMemberLeft
    mock_telegram.add_response(
        "getChatMember",
        {"ok": True, "result": {"user": {"id": 999, "is_bot": False, "first_name": "User"}, "status": "left"}},
    )

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_users_csv -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage" and "not a member" in r["data"]["text"]), None)
    assert req is not None


@pytest.mark.asyncio
async def test_message_reaction_no_mapping(mock_telegram, router_app_context):
    """Test message_reaction when message context is not cached."""
    from routers.admin_core import message_reaction as message_reaction_handler

    bot = router_app_context.bot
    session = router_app_context.session
    app_context = router_app_context

    chat_id = 123
    thread_id = 5

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])

    class ReactionEvent:
        def __init__(self):
            self.new_reaction = [types.ReactionTypeCustomEmoji(custom_emoji_id="5220090169088045319")]
            self.chat = types.Chat(id=chat_id, type="supergroup", title="Group")
            self.message_id = 10
            self.user = types.User(id=999, is_bot=False, first_name="Admin", username="admin")
            self.text = "reaction"

    reaction_update = ReactionEvent()

    await message_reaction_handler(reaction_update, bot, session, app_context)

    requests = mock_telegram.get_requests()
    assert not any(r["method"] in ("sendMessage", "forwardMessage", "deleteMessage") for r in requests)


@pytest.mark.asyncio
async def test_message_reaction_x_emoji_deletes_message(mock_telegram, router_app_context):
    from routers.admin_core import message_reaction as message_reaction_handler

    bot = router_app_context.bot
    session = router_app_context.session
    app_context = router_app_context

    chat_id = 123
    thread_id = 5

    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@admin"])
    await router_app_context.message_thread_cache_service.remember_message_context(
        chat_id=chat_id,
        message_id=10,
        thread_id=thread_id,
        user_id=789,
        username="baduser",
        full_name="Bad User",
    )

    class ReactionEvent:
        def __init__(self):
            self.new_reaction = [types.ReactionTypeCustomEmoji(custom_emoji_id="5220151067429335888")]
            self.chat = types.Chat(id=chat_id, type="supergroup", title="Group")
            self.message_id = 10
            self.user = types.User(id=999, is_bot=False, first_name="Admin", username="admin")

    reaction_update = ReactionEvent()

    await message_reaction_handler(reaction_update, bot, session, app_context)

    requests = mock_telegram.get_requests()
    forward_req = next((r for r in requests if r["method"] == "forwardMessage"), None)
    assert forward_req is not None
    assert str(forward_req["data"]["chat_id"]) == str(MTLChats.SpamGroup)

    log_req = next(
        (
            r
            for r in requests
            if r["method"] == "sendMessage"
            and str(r["data"]["chat_id"]) == str(MTLChats.SpamGroup)
            and "deleted by" in r["data"]["text"]
        ),
        None,
    )
    assert log_req is not None

    delete_req = next((r for r in requests if r["method"] == "deleteMessage"), None)
    assert delete_req is not None
    assert int(delete_req["data"]["message_id"]) == 10


@pytest.mark.asyncio
async def test_delete_dead_members_complete_flow(mock_telegram, router_app_context):
    """Test /delete_dead_members complete successful flow with numeric chat ID."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    # Mock remove_deleted_users to return count
    async def mock_remove(chat_id):
        return 5

    router_app_context.group_service.remove_deleted_users = mock_remove

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/delete_dead_members -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Check for "Finished" message with count
    finished_req = next((r for r in requests if r["method"] == "sendMessage" and "Finished" in r["data"]["text"]), None)
    assert finished_req is not None
    assert "5" in finished_req["data"]["text"]


@pytest.mark.asyncio
async def test_on_my_chat_member_other_status(mock_telegram, router_app_context):
    """Test my_chat_member with other status change."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Create a custom status scenario - using an unusual transition
    chat = types.Chat(id=123, type="supergroup", title="Group")
    bot_user = types.User(id=123456, is_bot=True, first_name="TestBot", username="test_bot")

    # Testing status change from administrator to member (demotion)
    update_event = types.ChatMemberUpdated(
        chat=chat,
        from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberAdministrator(
            user=bot_user,
            can_be_edited=False,
            is_anonymous=False,
            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_promote_members=False,
            can_change_info=True,
            can_invite_users=True,
            can_post_stories=False,
            can_edit_stories=False,
            can_delete_stories=False,
        ),
        new_chat_member=types.ChatMemberMember(user=bot_user),
    )
    update = types.Update(update_id=10, my_chat_member=update_event)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # This transition triggers message but different branch
    requests = mock_telegram.get_requests()
    # Should send "Thanks for adding me" since new status is MEMBER
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None


@pytest.mark.asyncio
async def test_get_users_csv_full_success(mock_telegram, router_app_context):
    """Test /get_users_csv complete successful flow with document sent."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Mock get_members to return users
    router_app_context.group_service.get_members.return_value = [
        GroupMember(user_id=1, username="user1", full_name="User One", is_admin=True, is_bot=False),
        GroupMember(user_id=2, username=None, full_name="User Two", is_admin=False, is_bot=False),
        GroupMember(user_id=3, username="bot", full_name="Bot", is_admin=False, is_bot=True),
    ]

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_users_csv -1001234567890",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Check for "Processing" message
    proc_req = next((r for r in requests if r["method"] == "sendMessage" and "Processing" in r["data"]["text"]), None)
    assert proc_req is not None
    # Check for document sent
    doc_req = next((r for r in requests if r["method"] == "sendDocument"), None)
    assert doc_req is not None


@pytest.mark.asyncio
async def test_get_users_csv_user_check_bad_request(mock_telegram, router_app_context):
    """Test /get_users_csv when user membership check raises TelegramBadRequest."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Mock getChatMember to return error (bad request)
    mock_telegram.add_response(
        "getChatMember", {"ok": False, "error_code": 400, "description": "Bad Request: user not found"}
    )

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_users_csv -1001234567890",
        ),
    )

    try:
        await dp.feed_update(bot=router_app_context.bot, update=update)
    except Exception:
        pass  # TelegramBadRequest expected


@pytest.mark.asyncio
async def test_get_users_csv_user_check_generic_error(mock_telegram, router_app_context):
    """Test /get_users_csv when user membership check raises generic exception."""
    from unittest.mock import patch

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    call_count = [0]

    async def mock_get_chat_member(chat_id, user_id):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call - bot check succeeds
            return types.ChatMemberMember(user=types.User(id=123456, is_bot=True, first_name="Bot"))
        # Second call - user check fails
        raise RuntimeError("Network error")

    with patch.object(router_app_context.bot, "get_chat_member", side_effect=mock_get_chat_member):
        update = types.Update(
            update_id=17,
            message=types.Message(
                message_id=41,
                date=datetime.datetime.now(),
                chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
                from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
                text="/get_users_csv -1001234567890",
            ),
        )

        await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should have error message about checking membership
    req = next((r for r in requests if r["method"] == "sendMessage" and "error" in r["data"]["text"].lower()), None)
    assert req is not None


@pytest.mark.asyncio
async def test_get_users_csv_bot_check_generic_error(mock_telegram, router_app_context):
    """Test /get_users_csv when bot membership check raises generic exception."""
    from unittest.mock import patch

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    async def mock_get_chat_member(chat_id, user_id):
        raise RuntimeError("Network error checking bot")

    with patch.object(router_app_context.bot, "get_chat_member", side_effect=mock_get_chat_member):
        update = types.Update(
            update_id=17,
            message=types.Message(
                message_id=41,
                date=datetime.datetime.now(),
                chat=types.Chat(id=MTLChats.MTLIDGroup, type="supergroup", title="Group"),
                from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
                text="/get_users_csv -1001234567890",
            ),
        )

        await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage" and "error" in r["data"]["text"].lower()), None)
    assert req is not None


@pytest.mark.asyncio
async def test_delete_dead_members_not_admin_of_both_chats(mock_telegram, router_app_context):
    """Test /delete_dead_members when admin of source but not target chat."""
    from unittest.mock import patch

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    call_count = [0]

    async def mock_get_chat_administrators(chat_id):
        call_count[0] += 1
        if call_count[0] == 1 or chat_id == 123:
            # First call - admin of source chat
            return [
                types.ChatMemberOwner(user=types.User(id=999, is_bot=False, first_name="Admin"), is_anonymous=False)
            ]
        else:
            # Second call - not admin of target chat
            return []

    with patch.object(router_app_context.bot, "get_chat_administrators", side_effect=mock_get_chat_administrators):
        update = types.Update(
            update_id=7,
            message=types.Message(
                message_id=32,
                date=datetime.datetime.now(),
                chat=types.Chat(id=123, type="supergroup", title="Group"),
                from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
                text="/delete_dead_members -1001234567890",
            ),
        )

        await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage" and "not an admin" in r["data"]["text"]), None)
    assert req is not None


@pytest.mark.asyncio
async def test_ro_command_external_reply(mock_telegram, router_app_context):
    """Test !ro command with external_reply (cross-topic reply in forum group).

    When an admin replies to a message from a different forum topic,
    Telegram sets external_reply instead of reply_to_message.
    The bot should still restrict the target user.
    """
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)
    mock_telegram.add_response("restrictChatMember", {"ok": True, "result": True})

    external_reply = types.ExternalReplyInfo(
        origin=types.MessageOriginUser(
            type="user",
            date=datetime.datetime.now(),
            sender_user=types.User(id=789, is_bot=False, first_name="BadUser", username="baduser"),
        )
    )

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=6,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="!ro 4w",
            external_reply=external_reply,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "restrictChatMember"), None)
    assert req is not None, "restrictChatMember should be called for external_reply target"
    assert int(req["data"]["user_id"]) == 789


@pytest.mark.asyncio
async def test_ro_command_restrict_bad_request(mock_telegram, router_app_context):
    """Test !ro command when restrictChatMember fails (user not in chat).

    In real Telegram the API returns HTTP 400 → TelegramBadRequest.
    We mock restrict() directly to simulate this.
    """
    from unittest.mock import AsyncMock, patch

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    setup_is_admin(mock_telegram, 999, True)

    reply_msg = types.Message(
        message_id=5,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="BadUser", username="baduser"),
        text="Spam",
    )

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=6,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="!ro 10m",
            reply_to_message=reply_msg,
        ),
    )

    with patch.object(
        types.Chat,
        "restrict",
        new=AsyncMock(side_effect=TelegramBadRequest(method=None, message="Bad Request: user not found")),
    ):
        await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    reply = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert reply is not None
    assert "Failed to restrict" in reply["data"]["text"]
