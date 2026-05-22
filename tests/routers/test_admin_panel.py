"""Tests for admin_panel.py router."""

import pytest
import datetime
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from routers.admin_panel import (
    router as admin_panel_router,
    AdminCallback,
    AdminPanelStates,
    chat_list_kb,
    chat_menu_kb,
    feature_flags_kb,
    welcome_kb,
    mark_chat_inaccessible,
    async_mark_chat_inaccessible,
    is_chat_accessible,
    unmark_chat_accessible,
    async_unmark_chat_accessible,
    load_inaccessible_chats,
    notify_owner_about_settings_change,
    _inaccessible_chats,
    _chat_titles,
    _chat_owners,
)
from other.constants import BotValueTypes
from tests.conftest import RouterTestMiddleware


@pytest.fixture(autouse=True)
async def cleanup_router():
    """Ensure router is detached and caches cleared after each test."""
    _inaccessible_chats.clear()
    _chat_titles.clear()
    _chat_owners.clear()
    yield
    if admin_panel_router.parent_router:
        admin_panel_router._parent_router = None
    _inaccessible_chats.clear()
    _chat_titles.clear()
    _chat_owners.clear()


# ============ Unit Tests: Helper Functions ============


class TestInaccessibleChats:
    def test_mark_chat_inaccessible(self):
        """Test marking chat as inaccessible."""
        assert is_chat_accessible(123)
        mark_chat_inaccessible(123)
        assert not is_chat_accessible(123)

    def test_unmark_chat_accessible(self):
        """Test unmarking chat as accessible."""
        mark_chat_inaccessible(123)
        assert not is_chat_accessible(123)
        unmark_chat_accessible(123)
        assert is_chat_accessible(123)

    def test_load_inaccessible_chats(self):
        """Test loading inaccessible chats from list."""
        load_inaccessible_chats([100, 200, 300])
        assert not is_chat_accessible(100)
        assert not is_chat_accessible(200)
        assert not is_chat_accessible(300)
        assert is_chat_accessible(400)

    def test_load_clears_previous(self):
        """Test that loading clears previous data."""
        mark_chat_inaccessible(999)
        load_inaccessible_chats([100])
        assert is_chat_accessible(999)
        assert not is_chat_accessible(100)

    @pytest.mark.asyncio
    async def test_async_mark_chat_inaccessible_persists(self, router_app_context):
        """Test async marking persists inaccessible chats through db_service."""
        await async_mark_chat_inaccessible(123, router_app_context)

        assert not is_chat_accessible(123)
        persisted = await router_app_context.db_service.load_bot_value(0, BotValueTypes.Inaccessible, "[]")
        assert "123" in persisted

    @pytest.mark.asyncio
    async def test_async_unmark_chat_accessible_persists(self, router_app_context):
        """Test async unmarking persists inaccessible chats through db_service."""
        mark_chat_inaccessible(123)

        await async_unmark_chat_accessible(123, router_app_context)

        assert is_chat_accessible(123)
        persisted = await router_app_context.db_service.load_bot_value(0, BotValueTypes.Inaccessible, "[]")
        assert "123" not in persisted


# ============ Unit Tests: Keyboard Builders ============


class TestChatListKb:
    def test_empty_list(self):
        """Test keyboard with empty chat list."""
        kb = chat_list_kb([])
        assert len(kb.inline_keyboard) == 0

    def test_single_chat(self):
        """Test keyboard with single chat."""
        chats = [(-100123, "Test Chat")]
        kb = chat_list_kb(chats)
        assert len(kb.inline_keyboard) == 1
        assert kb.inline_keyboard[0][0].text == "Test Chat"

    def test_title_truncation(self):
        """Test that long titles are truncated."""
        chats = [(-100123, "This is a very long chat title that should be truncated")]
        kb = chat_list_kb(chats)
        assert kb.inline_keyboard[0][0].text == "This is a very long ..."

    def test_pagination_not_shown_for_few_chats(self):
        """Test no pagination for chats less than page size."""
        chats = [(i, f"Chat {i}") for i in range(5)]
        kb = chat_list_kb(chats)
        # Only chat buttons, no navigation
        assert len(kb.inline_keyboard) == 5

    def test_pagination_shown_for_many_chats(self):
        """Test pagination shown when chats exceed page size."""
        chats = [(i, f"Chat {i}") for i in range(15)]
        kb = chat_list_kb(chats, page=0)
        # 10 chats + 1 navigation row
        assert len(kb.inline_keyboard) == 11
        # Last row is navigation
        nav_row = kb.inline_keyboard[-1]
        # First page: no prev, has page counter, has next
        assert len(nav_row) == 2  # page counter + next
        assert "1/2" in nav_row[0].text
        assert "Next" in nav_row[1].text

    def test_pagination_second_page(self):
        """Test pagination on second page."""
        chats = [(i, f"Chat {i}") for i in range(15)]
        kb = chat_list_kb(chats, page=1)
        # 5 chats + 1 navigation row
        assert len(kb.inline_keyboard) == 6
        nav_row = kb.inline_keyboard[-1]
        # Last page: has prev, has page counter, no next
        assert len(nav_row) == 2  # prev + page counter
        assert "Prev" in nav_row[0].text
        assert "2/2" in nav_row[1].text

    def test_pagination_middle_page(self):
        """Test pagination on middle page."""
        chats = [(i, f"Chat {i}") for i in range(25)]
        kb = chat_list_kb(chats, page=1)
        nav_row = kb.inline_keyboard[-1]
        # Middle page: prev + counter + next
        assert len(nav_row) == 3
        assert "Prev" in nav_row[0].text
        assert "2/3" in nav_row[1].text
        assert "Next" in nav_row[2].text

    def test_page_bounds_check(self):
        """Test that invalid page numbers are bounded."""
        chats = [(i, f"Chat {i}") for i in range(15)]
        # Page too high
        kb = chat_list_kb(chats, page=100)
        nav_row = kb.inline_keyboard[-1]
        assert "2/2" in nav_row[1].text  # Should be on last page

        # Negative page
        kb = chat_list_kb(chats, page=-5)
        nav_row = kb.inline_keyboard[-1]
        assert "1/2" in nav_row[0].text  # Should be on first page


class TestChatMenuKb:
    def test_menu_buttons(self):
        """Test chat menu has all expected buttons."""
        kb = chat_menu_kb(-100123)
        texts = [row[0].text for row in kb.inline_keyboard]
        assert "Feature Flags" in texts
        assert "Welcome Settings" in texts
        assert "Remove Dead Users" in texts
        assert "<< Back" in texts


class TestFeatureFlagsKb:
    def test_all_features_for_regular_admin(self, router_app_context):
        """Test skynet-only features are hidden from regular admins."""
        kb = feature_flags_kb(-100123, router_app_context.feature_flags, is_skynet_admin=False)
        # 15 total - 2 skynet-only (full_data, listen) = 13 features + 1 back = 14 rows
        assert len(kb.inline_keyboard) == 14
        all_text = " ".join(row[0].text for row in kb.inline_keyboard)
        assert "Full Data" not in all_text
        assert "Listen" not in all_text
        assert "Notify Join" in all_text
        assert "Self-Moderation" in all_text

    def test_all_features_for_skynet_admin(self, router_app_context):
        """Test skynet admins see all features including skynet-only."""
        kb = feature_flags_kb(-100123, router_app_context.feature_flags, is_skynet_admin=True)
        # 15 features + 1 back button = 16 rows
        assert len(kb.inline_keyboard) == 16
        all_text = " ".join(row[0].text for row in kb.inline_keyboard)
        assert "Full Data" in all_text
        assert "Listen" in all_text
        assert "Notify Join" in all_text

    def test_feature_status_display(self, router_app_context):
        """Test feature status is displayed correctly."""
        chat_id = -100123
        router_app_context.feature_flags.enable(chat_id, "captcha")

        kb = feature_flags_kb(chat_id, router_app_context.feature_flags, is_skynet_admin=True)
        # Find captcha row
        captcha_row = next(row for row in kb.inline_keyboard if "Captcha" in row[0].text)
        assert "🟢 Captcha" == captcha_row[0].text
        assert "🟢" == captcha_row[1].text


class TestWelcomeKb:
    def test_welcome_buttons(self):
        """Test welcome keyboard has all expected buttons."""
        kb = welcome_kb(-100123)
        # First row has 2 buttons
        assert len(kb.inline_keyboard[0]) == 2
        assert "Edit Message" in kb.inline_keyboard[0][0].text
        assert "Edit Button" in kb.inline_keyboard[0][1].text
        assert "Delete Welcome" in kb.inline_keyboard[1][0].text
        assert "<< Back" in kb.inline_keyboard[2][0].text


# ============ Integration Tests: Command Handlers ============


def setup_admin_response(mock_server, user_id, is_admin=True):
    """Helper to set up getChatAdministrators response."""
    if is_admin:
        result = [
            {
                "status": "creator",
                "user": {"id": user_id, "is_bot": False, "username": "admin", "first_name": "Admin"},
                "is_anonymous": False,
            }
        ]
    else:
        result = []
    mock_server.add_response("getChatAdministrators", {"ok": True, "result": result})


@pytest.mark.asyncio
async def test_cmd_admin_no_chats(mock_telegram, router_app_context):
    """Test /admin command when user has no admin chats."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    user_id = 12345
    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=user_id, type="private"),
            from_user=types.User(id=user_id, is_bot=False, first_name="User"),
            text="/admin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    send_msg = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert send_msg is not None
    assert "not an admin" in send_msg["data"]["text"]


@pytest.mark.asyncio
async def test_cmd_admin_with_chats(mock_telegram, router_app_context):
    """Test /admin command when user has admin chats."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    user_id = 12345
    chat_id = -100999

    # Set up admin data
    router_app_context.admin_service.set_chat_admins(chat_id, [user_id])

    # Mock getChat response
    mock_telegram.add_response(
        "getChat",
        {
            "ok": True,
            "result": {
                "id": chat_id,
                "type": "supergroup",
                "title": "Test Group",
                "accent_color_id": 0,
                "max_reaction_count": 0,
                "permissions": {},
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

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=user_id, type="private"),
            from_user=types.User(id=user_id, is_bot=False, first_name="User"),
            text="/admin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    send_msg = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert send_msg is not None
    assert "Select a chat" in send_msg["data"]["text"]
    assert "reply_markup" in send_msg["data"]


@pytest.mark.asyncio
async def test_cmd_admin_reload_in_group(mock_telegram, router_app_context):
    """Test /admin command in group reloads admin list."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    user_id = 12345
    chat_id = -100999

    setup_admin_response(mock_telegram, user_id, True)

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup", title="Group"),
            from_user=types.User(id=user_id, is_bot=False, first_name="Admin"),
            text="/admin",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Check that admin list was updated
    assert router_app_context.admin_service.is_chat_admin(chat_id, user_id)

    # Check reply sent
    requests = mock_telegram.get_requests()
    send_msg = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert send_msg is not None
    assert send_msg["data"]["text"] == "OK"


# ============ Integration Tests: Callback Handlers ============


@pytest.mark.asyncio
async def test_cb_noop(mock_telegram, router_app_context):
    """Test noop callback just answers."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    user_id = 12345
    callback_data = AdminCallback(action="noop").pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=user_id, is_bot=False, first_name="User"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=user_id, type="private"), text="text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    answer = next((r for r in requests if r["method"] == "answerCallbackQuery"), None)
    assert answer is not None


@pytest.mark.asyncio
async def test_cb_show_chat_list_pagination(mock_telegram, router_app_context):
    """Test pagination in chat list callback."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    user_id = 12345
    # Set up 15 chats (2 pages)
    for i in range(15):
        chat_id = -100000 - i
        router_app_context.admin_service.set_chat_admins(chat_id, [user_id])
        _chat_titles[chat_id] = f"Chat {i}"

    callback_data = AdminCallback(action="list", page=1).pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=user_id, is_bot=False, first_name="User"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=user_id, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    edit_msg = next((r for r in requests if r["method"] == "editMessageText"), None)
    assert edit_msg is not None
    assert "15 total" in edit_msg["data"]["text"]


@pytest.mark.asyncio
async def test_cb_show_chat_menu(mock_telegram, router_app_context):
    """Test showing chat menu callback."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    user_id = 12345
    chat_id = -100999

    setup_admin_response(mock_telegram, user_id, True)
    _chat_titles[chat_id] = "Test Chat"

    callback_data = AdminCallback(action="menu", chat_id=chat_id).pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=user_id, is_bot=False, first_name="User"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=user_id, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    edit_msg = next((r for r in requests if r["method"] == "editMessageText"), None)
    assert edit_msg is not None
    assert "Settings: Test Chat" in edit_msg["data"]["text"]


@pytest.mark.asyncio
async def test_cb_show_chat_menu_not_admin(mock_telegram, router_app_context):
    """Test chat menu shows error when user not admin."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    user_id = 12345
    chat_id = -100999

    setup_admin_response(mock_telegram, user_id, False)

    callback_data = AdminCallback(action="menu", chat_id=chat_id).pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=user_id, is_bot=False, first_name="User"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=user_id, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    answer = next((r for r in requests if r["method"] == "answerCallbackQuery"), None)
    assert answer is not None
    assert "not an admin" in answer["data"].get("text", "")


@pytest.mark.asyncio
async def test_cb_toggle_feature(mock_telegram, router_app_context):
    """Test toggling a feature flag."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100999
    _chat_titles[chat_id] = "Test Chat"

    # Feature starts disabled
    assert not router_app_context.feature_flags.is_enabled(chat_id, "captcha")

    callback_data = AdminCallback(action="toggle", chat_id=chat_id, param="captcha").pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=12345, is_bot=False, first_name="User"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=12345, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Feature should now be enabled
    assert router_app_context.feature_flags.is_enabled(chat_id, "captcha")
    assert await router_app_context.db_service.load_bot_value(chat_id, BotValueTypes.Captcha, None) == "1"

    requests = mock_telegram.get_requests()
    answer = next((r for r in requests if r["method"] == "answerCallbackQuery"), None)
    assert answer is not None
    assert "enabled" in answer["data"].get("text", "")


@pytest.mark.asyncio
async def test_cb_toggle_skynet_feature_blocked_for_regular_admin(mock_telegram, router_app_context):
    """Test that regular admin cannot toggle skynet-only feature (full_data)."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100999
    _chat_titles[chat_id] = "Test Chat"

    # User without skynet admin rights
    callback_data = AdminCallback(action="toggle", chat_id=chat_id, param="full_data").pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=12345, is_bot=False, first_name="User", username="regularuser"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=12345, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Feature should NOT be toggled
    assert not router_app_context.feature_flags.is_enabled(chat_id, "full_data")

    requests = mock_telegram.get_requests()
    answer = next((r for r in requests if r["method"] == "answerCallbackQuery"), None)
    assert answer is not None
    assert "skynet admins" in answer["data"].get("text", "").lower()


@pytest.mark.asyncio
async def test_cb_toggle_skynet_feature_allowed_for_skynet_admin(mock_telegram, router_app_context):
    """Test that skynet admin can toggle skynet-only feature (full_data)."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100999
    _chat_titles[chat_id] = "Test Chat"

    # Register user as skynet admin
    router_app_context.admin_service.add_skynet_admin("@skyadmin")

    callback_data = AdminCallback(action="toggle", chat_id=chat_id, param="full_data").pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=12345, is_bot=False, first_name="SkyAdmin", username="skyadmin"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=12345, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Feature should be toggled
    assert router_app_context.feature_flags.is_enabled(chat_id, "full_data")

    requests = mock_telegram.get_requests()
    answer = next((r for r in requests if r["method"] == "answerCallbackQuery"), None)
    assert answer is not None
    assert "enabled" in answer["data"].get("text", "")


@pytest.mark.asyncio
async def test_cb_toggle_notify_join_syncs_notification_service(mock_telegram, router_app_context):
    """Test that toggling notify_join syncs with notification_service."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100999
    _chat_titles[chat_id] = "Test Chat"

    # Verify notification_service starts with no join notify
    assert not router_app_context.notification_service.is_join_notify_enabled(chat_id)

    # Enable notify_join via toggle
    callback_data = AdminCallback(action="toggle", chat_id=chat_id, param="notify_join").pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=12345, is_bot=False, first_name="User"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=12345, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Feature flag should be enabled
    assert router_app_context.feature_flags.is_enabled(chat_id, "notify_join")
    # Notification service should be synced
    assert router_app_context.notification_service.is_join_notify_enabled(chat_id)

    # Now toggle again to disable
    callback_data = AdminCallback(action="toggle", chat_id=chat_id, param="notify_join").pack()

    update = types.Update(
        update_id=2,
        callback_query=types.CallbackQuery(
            id="cb2",
            from_user=types.User(id=12345, is_bot=False, first_name="User"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=12345, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Both should be disabled
    assert not router_app_context.feature_flags.is_enabled(chat_id, "notify_join")
    assert not router_app_context.notification_service.is_join_notify_enabled(chat_id)


@pytest.mark.asyncio
async def test_cb_show_welcome_settings(mock_telegram, router_app_context):
    """Test showing welcome settings."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100999
    _chat_titles[chat_id] = "Test Chat"
    router_app_context.config_service.set_welcome_message(chat_id, "Hello {name}!")
    router_app_context.config_service.set_welcome_button(chat_id, "Click me")

    callback_data = AdminCallback(action="welcome", chat_id=chat_id).pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=12345, is_bot=False, first_name="User"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=12345, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    edit_msg = next((r for r in requests if r["method"] == "editMessageText"), None)
    assert edit_msg is not None
    assert "Welcome Settings" in edit_msg["data"]["text"]
    assert "Hello {name}!" in edit_msg["data"]["text"]


@pytest.mark.asyncio
async def test_cb_delete_welcome(mock_telegram, router_app_context):
    """Test deleting welcome settings."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100999
    _chat_titles[chat_id] = "Test Chat"
    router_app_context.config_service.set_welcome_message(chat_id, "Hello!")
    router_app_context.config_service.set_welcome_button(chat_id, "Button")

    callback_data = AdminCallback(action="del", chat_id=chat_id, param="welcome").pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=12345, is_bot=False, first_name="User"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=12345, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Settings should be deleted
    assert router_app_context.config_service.get_welcome_message(chat_id) is None
    assert router_app_context.config_service.get_welcome_button(chat_id) is None
    assert await router_app_context.db_service.load_bot_value(chat_id, BotValueTypes.WelcomeMessage, None) is None
    assert await router_app_context.db_service.load_bot_value(chat_id, BotValueTypes.WelcomeButton, None) is None


@pytest.mark.asyncio
async def test_cb_feature_info(mock_telegram, router_app_context):
    """Test feature info popup."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    callback_data = AdminCallback(action="info", chat_id=-100999, param="captcha").pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=12345, is_bot=False, first_name="User"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1, date=datetime.datetime.now(), chat=types.Chat(id=12345, type="private"), text="old text"
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    answer = next((r for r in requests if r["method"] == "answerCallbackQuery"), None)
    assert answer is not None
    assert answer["data"].get("show_alert") in (True, "true")
    assert "Captcha" in answer["data"].get("text", "")


# ============ Integration Tests: FSM Handlers ============


@pytest.mark.asyncio
async def test_cmd_cancel_no_state(mock_telegram, router_app_context):
    """Test /cancel when no FSM state active."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    user_id = 12345
    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=user_id, type="private"),
            from_user=types.User(id=user_id, is_bot=False, first_name="User"),
            text="/cancel",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    send_msg = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert send_msg is not None
    assert "Nothing to cancel" in send_msg["data"]["text"]


@pytest.mark.asyncio
async def test_process_welcome_message(mock_telegram, router_app_context):
    """Test processing new welcome message."""
    from aiogram.fsm.storage.base import StorageKey

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    user_id = 12345
    chat_id = -100999
    _chat_titles[chat_id] = "Test Chat"

    # Create FSM context and set state
    storage = MemoryStorage()
    bot_id = router_app_context.bot.id
    state = FSMContext(storage=storage, key=StorageKey(bot_id=bot_id, chat_id=user_id, user_id=user_id))
    await state.set_state(AdminPanelStates.waiting_welcome_message)
    await state.update_data(edit_chat_id=chat_id)

    # Inject storage into dispatcher
    dp.fsm.storage = storage

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=user_id, type="private"),
            from_user=types.User(id=user_id, is_bot=False, first_name="User"),
            text="Welcome to our group, {name}!",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify message was saved
    saved = router_app_context.config_service.get_welcome_message(chat_id)
    assert saved == "Welcome to our group, {name}!"
    assert (
        await router_app_context.db_service.load_bot_value(chat_id, BotValueTypes.WelcomeMessage, None)
        == "Welcome to our group, {name}!"
    )


# ============ Tests: Owner Notification ============


def make_chat_response(chat_id, title="Test Chat"):
    """Helper to create getChat response."""
    return {
        "ok": True,
        "result": {
            "id": chat_id,
            "type": "supergroup",
            "title": title,
            "accent_color_id": 0,
            "max_reaction_count": 0,
            "permissions": {},
            "accepted_gift_types": {
                "unlimited_gifts": True,
                "limited_gifts": False,
                "unique_gifts": False,
                "premium_subscription": False,
                "gifts_from_channels": False,
            },
        },
    }


def make_admins_response(owner_id=None, admin_ids=None):
    """Helper to create getChatAdministrators response with owner and optional admins."""
    result = []
    if owner_id:
        result.append(
            {
                "status": "creator",
                "user": {"id": owner_id, "is_bot": False, "first_name": "Owner"},
                "is_anonymous": False,
            }
        )
    if admin_ids:
        for aid in admin_ids:
            result.append(
                {
                    "status": "administrator",
                    "user": {"id": aid, "is_bot": False, "first_name": f"Admin{aid}"},
                    "is_anonymous": False,
                    "can_be_edited": False,
                    "can_manage_chat": True,
                    "can_change_info": False,
                    "can_delete_messages": False,
                    "can_invite_users": False,
                    "can_restrict_members": False,
                    "can_pin_messages": False,
                    "can_promote_members": False,
                    "can_manage_video_chats": False,
                    "can_post_stories": False,
                    "can_edit_stories": False,
                    "can_delete_stories": False,
                }
            )
    return {"ok": True, "result": result}


@pytest.mark.asyncio
async def test_notify_owner_sends_message(mock_telegram, router_app_context):
    """Test that owner notification sends a message to the owner."""
    bot = router_app_context.bot
    chat_id = -100999
    admin_id = 12345
    owner_id = 67890

    # Mock getChat and getChatAdministrators
    mock_telegram.add_response("getChat", make_chat_response(chat_id, "Test Chat"))
    mock_telegram.add_response("getChatAdministrators", make_admins_response(owner_id, [admin_id]))

    admin_user = types.User(id=admin_id, is_bot=False, first_name="Admin", username="admin_user")
    await notify_owner_about_settings_change(bot, chat_id, admin_user, "Test change")

    requests = mock_telegram.get_requests()
    send_msg = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert send_msg is not None
    assert int(send_msg["data"]["chat_id"]) == owner_id
    assert "Test Chat" in send_msg["data"]["text"]
    assert "Test change" in send_msg["data"]["text"]
    assert "@admin_user" in send_msg["data"]["text"]


@pytest.mark.asyncio
async def test_notify_owner_skips_when_admin_is_owner(mock_telegram, router_app_context):
    """Test that notification is skipped when admin is the owner."""
    bot = router_app_context.bot
    chat_id = -100999
    owner_id = 12345  # Same as admin

    # Mock getChatAdministrators with owner = admin
    mock_telegram.add_response("getChatAdministrators", make_admins_response(owner_id))

    admin_user = types.User(id=owner_id, is_bot=False, first_name="Owner")
    await notify_owner_about_settings_change(bot, chat_id, admin_user, "Test change")

    requests = mock_telegram.get_requests()
    send_msg = next((r for r in requests if r["method"] == "sendMessage"), None)
    # No message should be sent
    assert send_msg is None


@pytest.mark.asyncio
async def test_notify_owner_skips_when_no_owner(mock_telegram, router_app_context):
    """Test that notification is skipped when chat has no owner."""
    bot = router_app_context.bot
    chat_id = -100999
    admin_id = 12345

    # Mock getChatAdministrators without owner
    mock_telegram.add_response("getChatAdministrators", make_admins_response(owner_id=None, admin_ids=[admin_id]))

    admin_user = types.User(id=admin_id, is_bot=False, first_name="Admin")
    await notify_owner_about_settings_change(bot, chat_id, admin_user, "Test change")

    requests = mock_telegram.get_requests()
    send_msg = next((r for r in requests if r["method"] == "sendMessage"), None)
    # No message should be sent
    assert send_msg is None


@pytest.mark.asyncio
async def test_notify_owner_handles_errors_gracefully(mock_telegram, router_app_context):
    """Test that errors when notifying owner don't break the flow."""
    bot = router_app_context.bot
    chat_id = -100999
    admin_id = 12345
    owner_id = 67890

    # Mock getChat and getChatAdministrators
    mock_telegram.add_response("getChat", make_chat_response(chat_id, "Test Chat"))
    mock_telegram.add_response("getChatAdministrators", make_admins_response(owner_id, [admin_id]))
    # Mock sendMessage to fail
    mock_telegram.add_response("sendMessage", {"ok": False, "error_code": 403, "description": "Forbidden"})

    admin_user = types.User(id=admin_id, is_bot=False, first_name="Admin")
    # Should not raise an exception
    await notify_owner_about_settings_change(bot, chat_id, admin_user, "Test change")


@pytest.mark.asyncio
async def test_notify_owner_caches_owner_id(mock_telegram, router_app_context):
    """Test that owner ID is cached after first lookup."""
    bot = router_app_context.bot
    chat_id = -100999
    admin_id = 12345
    owner_id = 67890

    # Mock getChat and getChatAdministrators
    mock_telegram.add_response("getChat", make_chat_response(chat_id, "Test Chat"))
    mock_telegram.add_response("getChatAdministrators", make_admins_response(owner_id, [admin_id]))

    admin_user = types.User(id=admin_id, is_bot=False, first_name="Admin")

    # First call should fetch from API
    await notify_owner_about_settings_change(bot, chat_id, admin_user, "Change 1")
    requests = mock_telegram.get_requests()
    assert len([r for r in requests if r["method"] == "getChatAdministrators"]) == 1

    # Second call should use cache (no new getChatAdministrators call)
    await notify_owner_about_settings_change(bot, chat_id, admin_user, "Change 2")
    requests = mock_telegram.get_requests()
    assert len([r for r in requests if r["method"] == "getChatAdministrators"]) == 1  # Still just 1

    # Verify owner is in cache
    assert _chat_owners[chat_id] == owner_id


@pytest.mark.asyncio
async def test_cb_toggle_feature_notifies_owner(mock_telegram, router_app_context):
    """Test that toggling a feature notifies the owner."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100999
    admin_id = 12345
    owner_id = 67890
    _chat_titles[chat_id] = "Test Chat"

    # Mock getChat and getChatAdministrators for notification
    mock_telegram.add_response("getChat", make_chat_response(chat_id, "Test Chat"))
    mock_telegram.add_response("getChatAdministrators", make_admins_response(owner_id, [admin_id]))

    callback_data = AdminCallback(action="toggle", chat_id=chat_id, param="captcha").pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=admin_id, is_bot=False, first_name="Admin"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1,
                date=datetime.datetime.now(),
                chat=types.Chat(id=admin_id, type="private"),
                text="old text",
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Find sendMessage to owner
    send_msgs = [r for r in requests if r["method"] == "sendMessage"]
    owner_msg = next((m for m in send_msgs if int(m["data"]["chat_id"]) == owner_id), None)
    assert owner_msg is not None
    assert "captcha" in owner_msg["data"]["text"]


@pytest.mark.asyncio
async def test_cb_delete_welcome_notifies_owner(mock_telegram, router_app_context):
    """Test that deleting welcome settings notifies the owner."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100999
    admin_id = 12345
    owner_id = 67890
    _chat_titles[chat_id] = "Test Chat"
    router_app_context.config_service.set_welcome_message(chat_id, "Hello!")

    # Mock getChat and getChatAdministrators for notification
    mock_telegram.add_response("getChat", make_chat_response(chat_id, "Test Chat"))
    mock_telegram.add_response("getChatAdministrators", make_admins_response(owner_id, [admin_id]))

    callback_data = AdminCallback(action="del", chat_id=chat_id, param="welcome").pack()

    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=admin_id, is_bot=False, first_name="Admin"),
            chat_instance="ci1",
            message=types.Message(
                message_id=1,
                date=datetime.datetime.now(),
                chat=types.Chat(id=admin_id, type="private"),
                text="old text",
            ),
            data=callback_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    send_msgs = [r for r in requests if r["method"] == "sendMessage"]
    owner_msg = next((m for m in send_msgs if int(m["data"]["chat_id"]) == owner_id), None)
    assert owner_msg is not None
    assert "приветствия" in owner_msg["data"]["text"]


# ============ Selfmod toggle / stats / reset ============


@pytest.mark.asyncio
async def test_cb_toggle_selfmod(mock_telegram, router_app_context):
    """Toggle the selfmod feature flag via /admin."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100888
    _chat_titles[chat_id] = "SelfMod Chat"
    assert not router_app_context.feature_flags.is_enabled(chat_id, "selfmod")

    cb = AdminCallback(action="toggle", chat_id=chat_id, param="selfmod").pack()
    update = types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb-sm-1",
            from_user=types.User(id=12345, is_bot=False, first_name="User"),
            chat_instance="ci",
            message=types.Message(
                message_id=1,
                date=datetime.datetime.now(),
                chat=types.Chat(id=12345, type="private"),
                text="x",
            ),
            data=cb,
        ),
    )
    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.feature_flags.is_enabled(chat_id, "selfmod")
    answer = next((r for r in mock_telegram.get_requests() if r["method"] == "answerCallbackQuery"), None)
    assert answer is not None
    assert "enabled" in answer["data"].get("text", "")


@pytest.mark.asyncio
async def test_cb_selfmod_stats_empty(mock_telegram, router_app_context):
    """Selfmod stats sub-page renders when there are no warnings."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100777
    _chat_titles[chat_id] = "EmptyChat"

    cb = AdminCallback(action="selfmod_stats", chat_id=chat_id).pack()
    update = types.Update(
        update_id=2,
        callback_query=types.CallbackQuery(
            id="cb-sm-stats",
            from_user=types.User(id=999, is_bot=False, first_name="Admin"),
            chat_instance="ci2",
            message=types.Message(
                message_id=2,
                date=datetime.datetime.now(),
                chat=types.Chat(id=12345, type="private"),
                text="x",
            ),
            data=cb,
        ),
    )
    await dp.feed_update(bot=router_app_context.bot, update=update)

    edits = [r for r in mock_telegram.get_requests() if r["method"] == "editMessageText"]
    assert edits
    assert any("No active warnings" in r["data"]["text"] for r in edits)


@pytest.mark.asyncio
async def test_cb_selfmod_stats_lists_users(mock_telegram, router_app_context):
    """Selfmod stats sub-page lists users with active warnings."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    chat_id = -100766
    _chat_titles[chat_id] = "WarnChat"
    router_app_context.selfmod_service.set_warning_count(chat_id, 555, 2)

    cb = AdminCallback(action="selfmod_stats", chat_id=chat_id).pack()
    update = types.Update(
        update_id=3,
        callback_query=types.CallbackQuery(
            id="cb-sm-warn",
            from_user=types.User(id=999, is_bot=False, first_name="Admin"),
            chat_instance="ci3",
            message=types.Message(
                message_id=3,
                date=datetime.datetime.now(),
                chat=types.Chat(id=12345, type="private"),
                text="x",
            ),
            data=cb,
        ),
    )
    await dp.feed_update(bot=router_app_context.bot, update=update)

    edits = [r for r in mock_telegram.get_requests() if r["method"] == "editMessageText"]
    text = edits[-1]["data"]["text"]
    assert "555" in text
    assert "2 warning" in text


@pytest.mark.asyncio
async def test_cb_selfmod_reset(mock_telegram, router_app_context):
    """Resetting warnings clears the count and notifies SpamGroup."""
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_panel_router)

    from other.constants import MTLChats

    chat_id = -100755
    target_user_id = 4242
    _chat_titles[chat_id] = "ResetChat"
    router_app_context.selfmod_service.set_warning_count(chat_id, target_user_id, 3)

    cb = AdminCallback(action="selfmod_reset", chat_id=chat_id, param=str(target_user_id)).pack()
    update = types.Update(
        update_id=4,
        callback_query=types.CallbackQuery(
            id="cb-sm-reset",
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            chat_instance="ci4",
            message=types.Message(
                message_id=4,
                date=datetime.datetime.now(),
                chat=types.Chat(id=12345, type="private"),
                text="x",
            ),
            data=cb,
        ),
    )
    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert await router_app_context.selfmod_service.get_warnings(chat_id, target_user_id) == 0
    spam_msgs = [
        r
        for r in mock_telegram.get_requests()
        if r["method"] == "sendMessage" and r["data"].get("chat_id") in (str(MTLChats.SpamGroup), MTLChats.SpamGroup)
    ]
    assert any("warnings_reset" in m["data"]["text"] for m in spam_msgs)
