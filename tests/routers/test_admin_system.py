import pytest
import os
import hashlib
from unittest.mock import AsyncMock
from pathlib import Path
from aiohttp import web
from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from routers.admin_system import router as admin_router
from tests.conftest import RouterTestMiddleware, get_free_port
from tests.fakes import FakeAsyncMethod
from other.constants import BotValueTypes, MTLChats
import datetime


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if admin_router.parent_router:
        admin_router._parent_router = None

    # Cleanup state
    pass
    if "skynet.log" in os.listdir("."):
        # We might have created it. But avoid deleting real logs if running on real env.
        # Check if size is small (dummy)
        if os.path.exists("skynet.log") and os.path.getsize("skynet.log") < 100:
            os.remove("skynet.log")


@pytest.fixture
async def mock_eurmtl_bot_confirm(monkeypatch):
    class EurmtlMockState:
        def __init__(self):
            self.requests = []
            self.status = 200
            self.response = {"ok": True}

    state = EurmtlMockState()
    port = get_free_port()
    routes = web.RouteTableDef()

    @routes.post("/login/bot/confirm")
    async def confirm(request):
        body = await request.json()
        state.requests.append(
            {
                "method": "POST",
                "path": request.path,
                "headers": dict(request.headers),
                "json": body,
            }
        )
        return web.json_response(state.response, status=state.status)

    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", port)
    await site.start()
    monkeypatch.setenv("EURMTL_BOT_CONFIRM_URL", f"http://localhost:{port}/login/bot/confirm")

    yield state

    await runner.cleanup()


@pytest.mark.asyncio
async def test_sha256_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    test_str = "test_string"
    expected_hash = hashlib.sha256(test_str.encode()).hexdigest()

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text=f"/sha256 {test_str}",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert expected_hash in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_log_command(mock_telegram, router_app_context):
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # create dummy log file
    with open("skynet.log", "w") as f:
        f.write("dummy log content")

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=3,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/log",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    doc_req = next((r for r in requests if r["method"] == "sendDocument"), None)
    assert doc_req is not None


@pytest.mark.asyncio
async def test_ping_piro(mock_telegram, router_app_context):
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    router_app_context.group_service.ping_piro.return_value = None

    update = types.Update(
        update_id=6,
        message=types.Message(
            message_id=6,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/ping_piro",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.group_service.ping_piro.called


@pytest.mark.asyncio
async def test_check_gs_command(mock_telegram, router_app_context):
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    router_app_context.gspread_service.check_credentials.return_value = (True, "1")

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=7,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/check_gs",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "Google ключ: OK" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_grist_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Mock grist service
    router_app_context.grist_service.load_table_data.return_value = [
        {"user_id": MTLChats.ITolstov, "id": 1, "fields": {}}
    ]
    router_app_context.grist_service.patch_data.return_value = None

    update = types.Update(
        update_id=12,
        message=types.Message(
            message_id=12,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="User", username="user"),
            text="/grist",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "новый ключ" in msg_req["data"]["text"].lower()

    assert router_app_context.grist_service.patch_data.called


@pytest.mark.asyncio
async def test_update_mtlap(mock_telegram, router_app_context):
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Mock gspread and mtl services
    # Dummy data: Headers + 1 row
    # Headers must have len >= 15, index 1 = "TGID", index 14 = "SkyNet"
    headers = [""] * 20
    headers[1] = "TGID"
    headers[14] = "SkyNet"
    row = [""] * 20
    row[1] = "12345"

    router_app_context.gspread_service.get_all_mtlap.return_value = [headers, row, row]
    router_app_context.gspread_service.get_update_mtlap_skynet_row.return_value = None
    router_app_context.mtl_service.check_consul_mtla_chats.return_value = ["Chat updated"]

    update = types.Update(
        update_id=13,
        message=types.Message(
            message_id=13,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/update_mtlap",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Check for "Готово 1", "Chat updated", "Готово 2"
    messages = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert "Готово 1" in messages
    assert "Chat updated" in messages
    assert "Готово 2" in messages


@pytest.mark.asyncio
async def test_sha1_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    file_bytes = b"test"
    mock_telegram.add_file("1", file_bytes, file_path="files/test.txt")

    update = types.Update(
        update_id=8,
        message=types.Message(
            message_id=8,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            document=types.Document(
                file_id="1", file_unique_id="1", file_name="test.txt", file_size=len(file_bytes), mime_type="text/plain"
            ),
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "SHA-1" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_exit_command(mock_telegram, router_app_context):
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # First call sets state
    update = types.Update(
        update_id=4,
        message=types.Message(
            message_id=4,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/exit",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "боюсь" in msg_req["data"]["text"]

    # Second call triggers exit
    # We expect SystemExit
    with pytest.raises(SystemExit):
        await dp.feed_update(bot=router_app_context.bot, update=update)


@pytest.mark.asyncio
async def test_eurmtl_command(mock_telegram, router_app_context):
    """Test /eurmtl command shows login buttons."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=20,
        message=types.Message(
            message_id=20,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/eurmtl",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "log in" in msg_req["data"]["text"].lower()
    # Check that reply_markup contains buttons
    assert "reply_markup" in msg_req["data"]


@pytest.mark.asyncio
async def test_get_summary_not_admin(mock_telegram, router_app_context):
    """Test /summary command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=21,
        message=types.Message(
            message_id=21,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/summary",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not my admin" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_get_summary_not_listening(mock_telegram, router_app_context):
    """Test /summary command returns 'no messages' when listening is disabled."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Ensure listening is NOT enabled
    router_app_context.feature_flags.disable(123, "listen")

    update = types.Update(
        update_id=22,
        message=types.Message(
            message_id=22,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/summary",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "No messages" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_get_summary_uses_async_db_service(mock_telegram, router_app_context):
    """Test /summary command loads and persists summaries through db_service."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    chat_id = -1004242
    router_app_context.feature_flags.enable(chat_id, "listen")
    router_app_context.db_service.summarize_messages = FakeAsyncMethod(return_value=["summary text"])

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=401,
        message=types.Message(
            message_id=401,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/summary",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    router_app_context.db_service.summarize_messages.assert_awaited_once()
    args, _ = router_app_context.db_service.summarize_messages.call_args
    assert args[:2] == (chat_id, 0)
    requests = mock_telegram.get_requests()
    assert any(r["method"] == "sendMessage" and "summary text" in r["data"]["text"] for r in requests)


@pytest.mark.asyncio
async def test_sync_post_not_admin(mock_telegram, router_app_context):
    """Test /sync command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=23,
        message=types.Message(
            message_id=23,
            date=datetime.datetime.now(),
            chat=types.Chat(id=-100123456789, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/sync",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not admin" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_sync_post_no_reply(mock_telegram, router_app_context):
    """Test /sync command requires reply to a forwarded message."""
    # Make the user an admin via mock response with all required fields
    mock_telegram.add_response(
        "getChatAdministrators",
        {
            "ok": True,
            "result": [
                {
                    "status": "administrator",
                    "user": {"id": MTLChats.ITolstov, "is_bot": False, "first_name": "Admin", "username": "admin"},
                    "is_anonymous": False,
                    "can_be_edited": False,
                    "can_manage_chat": True,
                    "can_delete_messages": True,
                    "can_manage_video_chats": True,
                    "can_restrict_members": True,
                    "can_promote_members": False,
                    "can_change_info": True,
                    "can_invite_users": True,
                    "can_post_stories": False,
                    "can_edit_stories": False,
                    "can_delete_stories": False,
                }
            ],
        },
    )

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=24,
        message=types.Message(
            message_id=24,
            date=datetime.datetime.now(),
            chat=types.Chat(id=-100123456789, type="supergroup"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/sync",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "только посты" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_resync_post_not_admin(mock_telegram, router_app_context):
    """Test /resync command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=25,
        message=types.Message(
            message_id=25,
            date=datetime.datetime.now(),
            chat=types.Chat(id=-100123456789, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/resync",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not admin" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_resync_post_no_reply(mock_telegram, router_app_context):
    """Test /resync command requires reply to bot message."""
    mock_telegram.add_response(
        "getChatAdministrators",
        {
            "ok": True,
            "result": [
                {
                    "status": "administrator",
                    "user": {"id": MTLChats.ITolstov, "is_bot": False, "first_name": "Admin", "username": "admin"},
                    "is_anonymous": False,
                    "can_be_edited": False,
                    "can_manage_chat": True,
                    "can_delete_messages": True,
                    "can_manage_video_chats": True,
                    "can_restrict_members": True,
                    "can_promote_members": False,
                    "can_change_info": True,
                    "can_invite_users": True,
                    "can_post_stories": False,
                    "can_edit_stories": False,
                    "can_delete_stories": False,
                }
            ],
        },
    )

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=26,
        message=types.Message(
            message_id=26,
            date=datetime.datetime.now(),
            chat=types.Chat(id=-100123456789, type="supergroup"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/resync",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "ответить на сообщение" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_edited_channel_post(mock_telegram, router_app_context):
    """Test edited channel post updates synced messages."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.edited_channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    channel_id = -1001234567890
    post_id = 100

    # Set up sync state in bot_state_service
    sync_data = {
        str(post_id): [
            {"chat_id": -100987654321, "message_id": 50, "url": f"https://t.me/c/{str(channel_id)[4:]}/{post_id}"}
        ]
    }
    router_app_context.bot_state_service.set_sync_state(str(channel_id), sync_data)

    update = types.Update(
        update_id=27,
        edited_channel_post=types.Message(
            message_id=post_id,
            date=datetime.datetime.now(),
            chat=types.Chat(id=channel_id, type="channel"),
            text="Updated post text",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    edit_req = next((r for r in requests if r["method"] == "editMessageText"), None)
    assert edit_req is not None
    assert "Updated post text" in edit_req["data"]["text"]


@pytest.mark.asyncio
async def test_edited_channel_post_removes_stale_sync_on_telegram_error(mock_telegram, router_app_context):
    """Test edited channel post removes stale sync record when target message is not found."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.edited_channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    channel_id = -1001234567890
    post_id = 100

    sync_data = {
        str(post_id): [
            {"chat_id": -100987654321, "message_id": 50, "url": f"https://t.me/c/{str(channel_id)[4:]}/{post_id}"}
        ]
    }
    router_app_context.bot_state_service.set_sync_state(str(channel_id), sync_data)

    router_app_context.bot.edit_message_text = AsyncMock(
        side_effect=TelegramBadRequest(method=None, message="Bad Request: message to edit not found")
    )

    update = types.Update(
        update_id=127,
        edited_channel_post=types.Message(
            message_id=post_id,
            date=datetime.datetime.now(),
            chat=types.Chat(id=channel_id, type="channel"),
            text="Updated post text",
        ),
    )

    # Should not raise — stale record is removed instead
    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify the stale record was cleaned up from sync state
    updated_sync = router_app_context.bot_state_service.get_sync_state(str(channel_id), {})
    assert str(post_id) not in updated_sync
    persisted_sync = await router_app_context.db_service.load_bot_value(channel_id, BotValueTypes.Sync, "{}")
    assert persisted_sync == "{}"


@pytest.mark.asyncio
async def test_push_not_admin(mock_telegram, router_app_context):
    """Test /push command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=28,
        message=types.Message(
            message_id=28,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/push",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not my admin" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_push_no_reply(mock_telegram, router_app_context):
    """Test /push command requires reply to message with usernames."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=29,
        message=types.Message(
            message_id=29,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/push",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "в ответ на список" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_push_no_usernames(mock_telegram, router_app_context):
    """Test /push command requires usernames with @ in reply."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    reply_message = types.Message(
        message_id=28,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="private"),
        from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
        text="no usernames here",
    )

    update = types.Update(
        update_id=30,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/push",
            reply_to_message=reply_message,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "собаки" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_get_info_not_admin(mock_telegram, router_app_context):
    """Test /get_info command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=31,
        message=types.Message(
            message_id=31,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/get_info 12345",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not my admin" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_get_info_no_id(mock_telegram, router_app_context):
    """Test /get_info command requires user ID."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=32,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/get_info",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "числовой ID" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_get_info_success(mock_telegram, router_app_context):
    """Test /get_info command with valid user ID."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=33,
        message=types.Message(
            message_id=33,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/get_info 12345",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    # Should contain subscription status info
    assert "подписан" in msg_req["data"]["text"].lower() or "не подписан" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_get_info_from_helper_chat(mock_telegram, router_app_context):
    """Test /get_info command works from HelperChat without admin check."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=34,
        message=types.Message(
            message_id=34,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.HelperChat, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="normaluser"),
            text="/get_info 12345",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    # Should get info, not "not my admin" rejection
    assert "not my admin" not in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_get_info_with_prefix(mock_telegram, router_app_context):
    """Test /get_info command with #ID prefix."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=35,
        message=types.Message(
            message_id=35,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/get_info #ID12345",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    # Should work with #ID prefix
    assert "подписан" in msg_req["data"]["text"].lower() or "не подписан" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_get_info_invalid_id(mock_telegram, router_app_context):
    """Test /get_info command with non-numeric ID."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=36,
        message=types.Message(
            message_id=36,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/get_info notanumber",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "должен быть числом" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_check_gs_error(mock_telegram, router_app_context):
    """Test /check_gs command when credentials check fails."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    router_app_context.gspread_service.check_credentials.return_value = (False, "Auth error")

    update = types.Update(
        update_id=37,
        message=types.Message(
            message_id=37,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/check_gs",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "ошибка" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_grist_no_access(mock_telegram, router_app_context):
    """Test /grist command when user has no access."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Return empty list - user not found
    router_app_context.grist_service.load_table_data.return_value = []

    update = types.Update(
        update_id=38,
        message=types.Message(
            message_id=38,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/grist",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "нет доступа" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_grist_error(mock_telegram, router_app_context):
    """Test /grist command when grist service raises an error."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Raise an exception
    router_app_context.grist_service.load_table_data.side_effect = Exception("Grist error")

    update = types.Update(
        update_id=39,
        message=types.Message(
            message_id=39,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/grist",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "ошибка" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_update_mtlap_not_admin(mock_telegram, router_app_context):
    """Test /update_mtlap command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=40,
        message=types.Message(
            message_id=40,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/update_mtlap",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not my admin" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_update_mtlap_empty_table(mock_telegram, router_app_context):
    """Test /update_mtlap command with empty table."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    router_app_context.gspread_service.get_all_mtlap.return_value = []

    update = types.Update(
        update_id=41,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/update_mtlap",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "ошибка" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_update_mtlap_wrong_format(mock_telegram, router_app_context):
    """Test /update_mtlap command with wrong table format."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Wrong headers
    headers = ["A", "B", "C"]
    router_app_context.gspread_service.get_all_mtlap.return_value = [headers]

    update = types.Update(
        update_id=42,
        message=types.Message(
            message_id=42,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/update_mtlap",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "неверный формат" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_update_chats_info_not_admin(mock_telegram, router_app_context):
    """Test /update_chats_info command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=43,
        message=types.Message(
            message_id=43,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/update_chats_info",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not my admin" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_update_chats_info(mock_telegram, router_app_context):
    """Test /update_chats_info command updates chat info."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    router_app_context.group_service.get_members.return_value = []
    router_app_context.db_service.update_chat_info = FakeAsyncMethod()

    update = types.Update(
        update_id=44,
        message=types.Message(
            message_id=44,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/update_chats_info",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    messages = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("done" in m.lower() for m in messages)
    assert router_app_context.db_service.update_chat_info.call_count == 2


@pytest.mark.asyncio
async def test_sync_post_with_forward(mock_telegram, router_app_context):
    """Test /sync command with valid forwarded post."""
    # Make the user an admin
    mock_telegram.add_response(
        "getChatAdministrators",
        {
            "ok": True,
            "result": [
                {
                    "status": "administrator",
                    "user": {"id": MTLChats.ITolstov, "is_bot": False, "first_name": "Admin", "username": "admin"},
                    "is_anonymous": False,
                    "can_be_edited": False,
                    "can_manage_chat": True,
                    "can_delete_messages": True,
                    "can_manage_video_chats": True,
                    "can_restrict_members": True,
                    "can_promote_members": False,
                    "can_change_info": True,
                    "can_invite_users": True,
                    "can_post_stories": False,
                    "can_edit_stories": False,
                    "can_delete_stories": False,
                }
            ],
        },
    )

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    channel_id = -1001234567890
    forward_from_message_id = 100

    reply_message = types.Message(
        message_id=45,
        date=datetime.datetime.now(),
        chat=types.Chat(id=-100123456789, type="supergroup"),
        forward_from_chat=types.Chat(id=channel_id, type="channel", title="Test Channel"),
        forward_from_message_id=forward_from_message_id,
        text="Forwarded post text*",
    )

    update = types.Update(
        update_id=46,
        message=types.Message(
            message_id=46,
            date=datetime.datetime.now(),
            chat=types.Chat(id=-100123456789, type="supergroup"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/sync",
            reply_to_message=reply_message,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should have sent a new message (sync)
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    persisted_sync = await router_app_context.db_service.load_bot_value(channel_id, BotValueTypes.Sync, "{}")
    assert str(forward_from_message_id) in persisted_sync


@pytest.mark.asyncio
async def test_resync_existing_sync(mock_telegram, router_app_context):
    """Test /resync command when sync already exists."""
    mock_telegram.add_response(
        "getChatAdministrators",
        {
            "ok": True,
            "result": [
                {
                    "status": "administrator",
                    "user": {"id": MTLChats.ITolstov, "is_bot": False, "first_name": "Admin", "username": "admin"},
                    "is_anonymous": False,
                    "can_be_edited": False,
                    "can_manage_chat": True,
                    "can_delete_messages": True,
                    "can_manage_video_chats": True,
                    "can_restrict_members": True,
                    "can_promote_members": False,
                    "can_change_info": True,
                    "can_invite_users": True,
                    "can_post_stories": False,
                    "can_edit_stories": False,
                    "can_delete_stories": False,
                }
            ],
        },
    )

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = -100123456789
    channel_id = -1001234567890
    post_id = "100"
    bot_message_id = 50

    # Pre-set sync state with this message already synced
    sync_data = {
        post_id: [
            {"chat_id": chat_id, "message_id": bot_message_id, "url": f"https://t.me/c/{str(channel_id)[4:]}/{post_id}"}
        ]
    }
    router_app_context.bot_state_service.set_sync_state(str(channel_id), sync_data)

    # Create a reply markup with Edit button
    reply_markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Edit", url=f"https://t.me/c/{str(channel_id)[4:]}/{post_id}")]
        ]
    )

    reply_message = types.Message(
        message_id=bot_message_id,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup"),
        from_user=types.User(id=123456, is_bot=True, first_name="TestBot"),  # Bot message
        text="Synced message",
        reply_markup=reply_markup,
    )

    update = types.Update(
        update_id=47,
        message=types.Message(
            message_id=51,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/resync",
            reply_to_message=reply_message,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "уже существует" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_resync_no_keyboard(mock_telegram, router_app_context):
    """Test /resync command when message has no keyboard."""
    mock_telegram.add_response(
        "getChatAdministrators",
        {
            "ok": True,
            "result": [
                {
                    "status": "administrator",
                    "user": {"id": MTLChats.ITolstov, "is_bot": False, "first_name": "Admin", "username": "admin"},
                    "is_anonymous": False,
                    "can_be_edited": False,
                    "can_manage_chat": True,
                    "can_delete_messages": True,
                    "can_manage_video_chats": True,
                    "can_restrict_members": True,
                    "can_promote_members": False,
                    "can_change_info": True,
                    "can_invite_users": True,
                    "can_post_stories": False,
                    "can_edit_stories": False,
                    "can_delete_stories": False,
                }
            ],
        },
    )

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    reply_message = types.Message(
        message_id=50,
        date=datetime.datetime.now(),
        chat=types.Chat(id=-100123456789, type="supergroup"),
        from_user=types.User(id=123456, is_bot=True, first_name="TestBot"),  # Bot message
        text="Message without keyboard",
        # No reply_markup
    )

    update = types.Update(
        update_id=48,
        message=types.Message(
            message_id=51,
            date=datetime.datetime.now(),
            chat=types.Chat(id=-100123456789, type="supergroup"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/resync",
            reply_to_message=reply_message,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "не найдена клавиатура" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_edited_channel_post_no_sync(mock_telegram, router_app_context):
    """Test edited channel post when no sync exists."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.edited_channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    channel_id = -1001234567890
    post_id = 100

    # No sync state set

    update = types.Update(
        update_id=49,
        edited_channel_post=types.Message(
            message_id=post_id,
            date=datetime.datetime.now(),
            chat=types.Chat(id=channel_id, type="channel"),
            text="Updated post text",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should not have edited any messages
    edit_req = next((r for r in requests if r["method"] == "editMessageText"), None)
    assert edit_req is None


@pytest.mark.asyncio
async def test_test_command_not_admin(mock_telegram, router_app_context):
    """Test /test command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=50,
        message=types.Message(
            message_id=50,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/test",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "only for admins" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_err_command(mock_telegram, router_app_context):
    """Test /err command sends error log file."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Create dummy error log file
    with open("skynet.err", "w") as f:
        f.write("dummy error content")

    try:
        update = types.Update(
            update_id=51,
            message=types.Message(
                message_id=51,
                date=datetime.datetime.now(),
                chat=types.Chat(id=123, type="private"),
                from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
                text="/err",
            ),
        )

        await dp.feed_update(bot=router_app_context.bot, update=update)

        requests = mock_telegram.get_requests()
        doc_req = next((r for r in requests if r["method"] == "sendDocument"), None)
        assert doc_req is not None
    finally:
        if os.path.exists("skynet.err") and os.path.getsize("skynet.err") < 100:
            os.remove("skynet.err")


@pytest.mark.asyncio
async def test_err_command_file_not_found(mock_telegram, router_app_context):
    """Test /err command when error log file doesn't exist."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Ensure file doesn't exist
    if os.path.exists("skynet.err"):
        os.remove("skynet.err")

    update = types.Update(
        update_id=52,
        message=types.Message(
            message_id=52,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/err",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "не найден" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_err_command_not_admin(mock_telegram, router_app_context):
    """Test /err command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=53,
        message=types.Message(
            message_id=53,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/err",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not my admin" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_log_command_not_admin(mock_telegram, router_app_context):
    """Test /log command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=54,
        message=types.Message(
            message_id=54,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/log",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not my admin" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_ping_piro_not_admin(mock_telegram, router_app_context):
    """Test /ping_piro command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=55,
        message=types.Message(
            message_id=55,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/ping_piro",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not my admin" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_restart_command(mock_telegram, router_app_context):
    """Test /restart command sets state."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=56,
        message=types.Message(
            message_id=56,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/restart",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "боюсь" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_exit_command_not_admin(mock_telegram, router_app_context):
    """Test /exit command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=57,
        message=types.Message(
            message_id=57,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/exit",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not my admin" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_resync_post_success(mock_telegram, router_app_context):
    """Test /resync command successfully adds new sync."""
    mock_telegram.add_response(
        "getChatAdministrators",
        {
            "ok": True,
            "result": [
                {
                    "status": "administrator",
                    "user": {"id": MTLChats.ITolstov, "is_bot": False, "first_name": "Admin", "username": "admin"},
                    "is_anonymous": False,
                    "can_be_edited": False,
                    "can_manage_chat": True,
                    "can_delete_messages": True,
                    "can_manage_video_chats": True,
                    "can_restrict_members": True,
                    "can_promote_members": False,
                    "can_change_info": True,
                    "can_invite_users": True,
                    "can_post_stories": False,
                    "can_edit_stories": False,
                    "can_delete_stories": False,
                }
            ],
        },
    )

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = -100123456789
    channel_id = -1001234567890
    post_id = "100"
    bot_message_id = 50

    # Create a reply markup with Edit button
    reply_markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Edit", url=f"https://t.me/c/{str(channel_id)[4:]}/{post_id}")]
        ]
    )

    reply_message = types.Message(
        message_id=bot_message_id,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup"),
        from_user=types.User(id=123456, is_bot=True, first_name="TestBot"),  # Bot message
        text="Synced message",
        reply_markup=reply_markup,
    )

    update = types.Update(
        update_id=58,
        message=types.Message(
            message_id=51,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/resync",
            reply_to_message=reply_message,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "восстановлена" in msg_req["data"]["text"].lower()
    persisted_sync = await router_app_context.db_service.load_bot_value(channel_id, BotValueTypes.Sync, "{}")
    assert post_id in persisted_sync


@pytest.mark.asyncio
async def test_resync_invalid_url_format(mock_telegram, router_app_context):
    """Test /resync command with invalid URL format in button."""
    mock_telegram.add_response(
        "getChatAdministrators",
        {
            "ok": True,
            "result": [
                {
                    "status": "administrator",
                    "user": {"id": MTLChats.ITolstov, "is_bot": False, "first_name": "Admin", "username": "admin"},
                    "is_anonymous": False,
                    "can_be_edited": False,
                    "can_manage_chat": True,
                    "can_delete_messages": True,
                    "can_manage_video_chats": True,
                    "can_restrict_members": True,
                    "can_promote_members": False,
                    "can_change_info": True,
                    "can_invite_users": True,
                    "can_post_stories": False,
                    "can_edit_stories": False,
                    "can_delete_stories": False,
                }
            ],
        },
    )

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = -100123456789

    # Create a reply markup with Edit button but invalid URL
    reply_markup = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="Edit", url="https://example.com/invalid")]]
    )

    reply_message = types.Message(
        message_id=50,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup"),
        from_user=types.User(id=123456, is_bot=True, first_name="TestBot"),
        text="Synced message",
        reply_markup=reply_markup,
    )

    update = types.Update(
        update_id=59,
        message=types.Message(
            message_id=51,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/resync",
            reply_to_message=reply_message,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "неверный формат" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_resync_no_edit_button(mock_telegram, router_app_context):
    """Test /resync command when keyboard has no Edit button."""
    mock_telegram.add_response(
        "getChatAdministrators",
        {
            "ok": True,
            "result": [
                {
                    "status": "administrator",
                    "user": {"id": MTLChats.ITolstov, "is_bot": False, "first_name": "Admin", "username": "admin"},
                    "is_anonymous": False,
                    "can_be_edited": False,
                    "can_manage_chat": True,
                    "can_delete_messages": True,
                    "can_manage_video_chats": True,
                    "can_restrict_members": True,
                    "can_promote_members": False,
                    "can_change_info": True,
                    "can_invite_users": True,
                    "can_post_stories": False,
                    "can_edit_stories": False,
                    "can_delete_stories": False,
                }
            ],
        },
    )

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    chat_id = -100123456789

    # Create a reply markup without Edit button
    reply_markup = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="Other", url="https://example.com")]]
    )

    reply_message = types.Message(
        message_id=50,
        date=datetime.datetime.now(),
        chat=types.Chat(id=chat_id, type="supergroup"),
        from_user=types.User(id=123456, is_bot=True, first_name="TestBot"),
        text="Synced message",
        reply_markup=reply_markup,
    )

    update = types.Update(
        update_id=60,
        message=types.Message(
            message_id=51,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/resync",
            reply_to_message=reply_message,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "не найдена кнопка edit" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_edited_channel_post_with_star(mock_telegram, router_app_context):
    """Test edited channel post ending with * removes markup."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.edited_channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    channel_id = -1001234567890
    post_id = 100

    # Set up sync state
    sync_data = {
        str(post_id): [
            {"chat_id": -100987654321, "message_id": 50, "url": f"https://t.me/c/{str(channel_id)[4:]}/{post_id}"}
        ]
    }
    router_app_context.bot_state_service.set_sync_state(str(channel_id), sync_data)

    update = types.Update(
        update_id=61,
        edited_channel_post=types.Message(
            message_id=post_id,
            date=datetime.datetime.now(),
            chat=types.Chat(id=channel_id, type="channel"),
            text="Updated post text*",  # Ends with *
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    edit_req = next((r for r in requests if r["method"] == "editMessageText"), None)
    assert edit_req is not None
    # The text should have * removed
    assert edit_req["data"]["text"] == "Updated post text"


@pytest.mark.asyncio
async def test_eurmtl_via_deeplink(mock_telegram, router_app_context):
    """Test /start eurmtl deep link shows login buttons."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=62,
        message=types.Message(
            message_id=62,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/start eurmtl",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "log in" in msg_req["data"]["text"].lower()


@pytest.mark.asyncio
async def test_eurmtl_bot_login_deeplink_confirms_token(mock_telegram, router_app_context, mock_eurmtl_bot_confirm):
    """Test /start eurmtl_<token> confirms browser login through eurmtl.me."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=71,
        message=types.Message(
            message_id=71,
            date=datetime.datetime.fromtimestamp(1760000000),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(
                id=123456,
                is_bot=False,
                first_name="Name",
                last_name="Surname",
                username="user",
            ),
            text="/start eurmtl_login-token-123",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert len(mock_eurmtl_bot_confirm.requests) == 1
    confirm_req = mock_eurmtl_bot_confirm.requests[0]
    assert confirm_req["headers"]["Authorization"] == "Bearer test-eurmtl-key"
    assert confirm_req["json"] == {
        "token": "login-token-123",
        "id": 123456,
        "first_name": "Name",
        "last_name": "Surname",
        "username": "user",
        "photo_url": None,
        "auth_date": 1760000000,
    }

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "Вход подтвержден" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_eurmtl_bot_login_deeplink_reports_expired_link(
    mock_telegram, router_app_context, mock_eurmtl_bot_confirm
):
    """Test bot tells user to restart login when eurmtl.me rejects token."""
    mock_eurmtl_bot_confirm.status = 410
    mock_eurmtl_bot_confirm.response = {"error": "expired"}

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=72,
        message=types.Message(
            message_id=72,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123456, is_bot=False, first_name="Name", username="user"),
            text="/start eurmtl_expired-token",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert len(mock_eurmtl_bot_confirm.requests) == 1
    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "Ссылка устарела" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_eurmtl_bot_login_deeplink_without_user_does_not_confirm(
    mock_telegram, router_app_context, mock_eurmtl_bot_confirm
):
    """Test bot does not call eurmtl.me when Telegram user data is missing."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=73,
        message=types.Message(
            message_id=73,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            text="/start eurmtl_missing-user-token",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert mock_eurmtl_bot_confirm.requests == []
    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "Ссылка устарела" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_check_gs_not_admin(mock_telegram, router_app_context):
    """Test /check_gs command rejected for non-admin."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    update = types.Update(
        update_id=63,
        message=types.Message(
            message_id=63,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/check_gs",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "not my admin" in msg_req["data"]["text"]


@pytest.mark.asyncio
async def test_log_file_empty(mock_telegram, router_app_context):
    """Test /log command when log file is empty."""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(admin_router)

    # Create empty log file
    Path("skynet.log").touch()

    try:
        update = types.Update(
            update_id=64,
            message=types.Message(
                message_id=64,
                date=datetime.datetime.now(),
                chat=types.Chat(id=123, type="private"),
                from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
                text="/log",
            ),
        )

        await dp.feed_update(bot=router_app_context.bot, update=update)

        requests = mock_telegram.get_requests()
        msg_req = next((r for r in requests if r["method"] == "sendMessage"), None)
        assert msg_req is not None
        assert "пуст" in msg_req["data"]["text"].lower()
    finally:
        if os.path.exists("skynet.log") and os.path.getsize("skynet.log") == 0:
            os.remove("skynet.log")
