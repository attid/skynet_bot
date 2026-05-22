import pytest
import datetime
from aiogram import types

from routers.multi_handler import router as multi_router, on_startup
from tests.conftest import RouterTestMiddleware
from other.constants import BotValueTypes, MTLChats


@pytest.fixture(autouse=True)
async def cleanup_router(router_app_context):
    yield
    if multi_router.parent_router:
        multi_router._parent_router = None
    # Clean up DI services
    router_app_context.feature_flags._features.clear()
    router_app_context.admin_service._skynet_admins.clear()
    router_app_context.admin_service._topic_admins.clear()


@pytest.mark.asyncio
async def test_universal_command_toggle(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(multi_router)

    # default mock_telegram admin is user_id=123456
    # Pre-add to list to test removal using DI service
    router_app_context.feature_flags.enable(MTLChats.TestGroup, "reply_only")

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=123456, is_bot=False, first_name="Admin", username="admin"),
            text="/set_reply_only",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify removal using DI service
    assert not router_app_context.feature_flags.is_enabled(MTLChats.TestGroup, "reply_only")
    assert await router_app_context.db_service.load_bot_value(MTLChats.TestGroup, 2, None) is None

    requests = mock_telegram.get_requests()
    assert any("Removed" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_list_command_add(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(multi_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])

    update = types.Update(
        update_id=2,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/add_skynet_admin @new_admin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Check admin_service for the new admin
    assert "@new_admin" in router_app_context.admin_service.get_skynet_admins()
    assert "@new_admin" in await router_app_context.db_service.load_bot_value(0, BotValueTypes.SkynetAdmins, "[]")

    requests = mock_telegram.get_requests()
    assert any("Added" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_topic_admin_management(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(multi_router)

    # default mock_telegram admin is user_id=123456

    chat_id = MTLChats.TestGroup
    thread_id = 5
    chat_thread_key = f"{chat_id}-{thread_id}"

    # Clean up before test using DI service
    all_topic_admins = router_app_context.admin_service.get_all_topic_admins()
    if chat_thread_key in all_topic_admins:
        del all_topic_admins[chat_thread_key]
        router_app_context.admin_service.load_topic_admins(all_topic_admins)

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=3,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
            message_thread_id=thread_id,
            from_user=types.User(id=123456, is_bot=False, first_name="Admin", username="admin"),
            text="/add_topic_admin @topicadmin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify added using DI service
    all_topic_admins = router_app_context.admin_service.get_all_topic_admins()
    assert chat_thread_key in all_topic_admins
    assert "@topicadmin" in all_topic_admins[chat_thread_key]
    assert "@topicadmin" in await router_app_context.db_service.load_bot_value(0, BotValueTypes.TopicAdmins, "{}")

    requests = mock_telegram.get_requests()
    assert any("Added at this thread" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_show_topic_admin_allows_topic_admin(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(multi_router)

    chat_id = MTLChats.TestGroup
    thread_id = 5
    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@topicadmin", "@otheradmin"])

    update = types.Update(
        update_id=4,
        message=types.Message(
            message_id=4,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
            message_thread_id=thread_id,
            from_user=types.User(id=777, is_bot=False, first_name="Topic", username="topicadmin"),
            text="/show_topic_admin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        "Items in this thread: @topicadmin @otheradmin" in r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_show_topic_admin_denies_non_topic_admin(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(multi_router)

    chat_id = MTLChats.TestGroup
    thread_id = 5
    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@topicadmin"])

    update = types.Update(
        update_id=5,
        message=types.Message(
            message_id=5,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
            message_thread_id=thread_id,
            from_user=types.User(id=778, is_bot=False, first_name="User", username="regularuser"),
            text="/show_topic_admin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("You are not admin." in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_add_topic_admin_still_denies_topic_admin_without_chat_admin_rights(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(multi_router)

    chat_id = MTLChats.TestGroup
    thread_id = 5
    router_app_context.admin_service.set_topic_admins(chat_id, thread_id, ["@topicadmin"])

    update = types.Update(
        update_id=6,
        message=types.Message(
            message_id=6,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
            message_thread_id=thread_id,
            from_user=types.User(id=779, is_bot=False, first_name="Topic", username="topicadmin"),
            text="/add_topic_admin @newtopicadmin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("You are not admin." in r["data"]["text"] for r in requests if r["method"] == "sendMessage")
    assert router_app_context.admin_service.get_topic_admins(chat_id, thread_id) == ["@topicadmin"]


@pytest.mark.asyncio
async def test_on_startup_triggers_loads(monkeypatch):
    """Test that on_startup calls command_config_loads with app_context."""
    called_with = []

    async def fake_command_config_loads(app_context=None):
        called_with.append(app_context)

    monkeypatch.setattr("routers.multi_handler.command_config_loads", fake_command_config_loads)

    # Create fake dispatcher with app_context
    fake_app_context = object()  # Any truthy object
    fake_dispatcher = {"app_context": fake_app_context}

    await on_startup(fake_dispatcher)

    # Verify command_config_loads was called with the app_context
    assert len(called_with) == 1
    assert called_with[0] is fake_app_context
