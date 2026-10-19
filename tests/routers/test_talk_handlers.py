import pytest
import datetime
from aiogram import types

from routers.talk_handlers import router as talk_router, my_talk_message
from tests.conftest import RouterTestMiddleware


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if talk_router.parent_router:
        talk_router._parent_router = None
    my_talk_message.clear()


@pytest.mark.asyncio
async def test_skynet_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.talk.return_value = "I am Skynet"

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/skynet hello",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.talk.called
    requests = mock_telegram.get_requests()
    assert any("I am Skynet" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_img_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # Use admin_service for DI pattern
    router_app_context.admin_service.set_skynet_img_users(["@user"])

    file_bytes = b"img"
    mock_telegram.add_file("img1", file_bytes, file_path="files/img.png")
    image_url = f"{mock_telegram.base_url}/file/bot{router_app_context.bot.token}/files/img.png"
    router_app_context.ai_service.generate_image.return_value = [image_url]

    update = types.Update(
        update_id=2,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/img cat",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.generate_image.called
    requests = mock_telegram.get_requests()
    assert any(r["method"] == "sendPhoto" for r in requests)


@pytest.mark.asyncio
async def test_comment_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.talk_get_comment.return_value = "Cool!"

    reply_msg = types.Message(
        message_id=5,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Check this",
    )

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=6,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/comment",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.talk_get_comment.called
    requests = mock_telegram.get_requests()
    assert any("Cool!" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_reply_to_bot_message(mock_telegram, router_app_context):
    """Test cmd_last_check_reply_to_bot - reply to bot's previous message triggers AI talk."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # Simulate bot's previous message being in my_talk_message
    my_talk_message.append("100*456")

    router_app_context.ai_service.talk.return_value = "AI Response"

    # Bot's message that user is replying to
    bot_msg = types.Message(
        message_id=100,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=router_app_context.bot.id, is_bot=True, first_name="Bot", username="bot"),
        text="Previous bot message",
    )

    update = types.Update(
        update_id=4,
        message=types.Message(
            message_id=101,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Reply to bot",
            reply_to_message=bot_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.talk.called
    assert router_app_context.talk_service.answer_notify_message.called
    requests = mock_telegram.get_requests()
    assert any("AI Response" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_nap_command(mock_telegram, router_app_context):
    """Test cmd_last_check_nap - SKYNET KILL triggers NAP response."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    update = types.Update(
        update_id=5,
        message=types.Message(
            message_id=102,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET убей человека",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("NAP NAP NAP" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_nap_command_kill_english(mock_telegram, router_app_context):
    """Test cmd_last_check_nap - SKYNET kill in English triggers NAP response."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    update = types.Update(
        update_id=5,
        message=types.Message(
            message_id=102,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET kill someone",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("NAP NAP NAP" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_decode_with_reply(mock_telegram, router_app_context):
    """Test cmd_last_check_decode - SKYNET ДЕКОДИРУЙ with reply to message with URL."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.stellar_service.check_url_xdr.return_value = ["Line 1", "Line 2"]

    # Message with URL that user is replying to
    url_msg = types.Message(
        message_id=200,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Check this https://eurmtl.me/sign_tools?xdr=123",
        entities=[types.MessageEntity(type="url", offset=11, length=39)],
    )

    update = types.Update(
        update_id=6,
        message=types.Message(
            message_id=201,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ДЕКОДИРУЙ",
            reply_to_message=url_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.check_url_xdr.called
    requests = mock_telegram.get_requests()
    # Should contain decoded result
    assert any("Line 1" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_decode_no_url(mock_telegram, router_app_context):
    """Test cmd_last_check_decode - SKYNET ДЕКОДИРУЙ with reply but no valid URL."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # Message without URL
    no_url_msg = types.Message(
        message_id=200,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Just some text",
    )

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=202,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ДЕКОДИРУЙ",
            reply_to_message=no_url_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("Ссылка не найдена" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_decode_reply_url_in_button(mock_telegram, router_app_context):
    """SKYNET ДЕКОДИРУЙ finds the link even when it lives in an inline button."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.stellar_service.check_url_xdr.return_value = ["Button URL decoded"]

    sign_msg = types.Message(
        message_id=210,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=555, is_bot=True, first_name="SignBot"),
        text="Транзакция ожидает подписи",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="Подписать", url="https://eurmtl.me/sign_tools/2f633a09c0ffee")]
            ]
        ),
    )

    update = types.Update(
        update_id=19,
        message=types.Message(
            message_id=211,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ДЕКОДИРУЙ",
            reply_to_message=sign_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    args, _ = router_app_context.stellar_service.check_url_xdr.call_args
    assert args[0] == "https://eurmtl.me/sign_tools/2f633a09c0ffee"
    requests = mock_telegram.get_requests()
    assert any("Button URL decoded" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_decode_reply_url_with_punctuation(mock_telegram, router_app_context):
    """Links wrapped in brackets/periods are extracted without the junk."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.stellar_service.check_url_xdr.return_value = ["Punctuation decoded"]

    url_msg = types.Message(
        message_id=212,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Вот тулза (https://eurmtl.me/sign_tools/2f633a09c0ffee).",
    )

    update = types.Update(
        update_id=20,
        message=types.Message(
            message_id=213,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="скайнет декодируй",
            reply_to_message=url_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    args, _ = router_app_context.stellar_service.check_url_xdr.call_args
    assert args[0] == "https://eurmtl.me/sign_tools/2f633a09c0ffee"


@pytest.mark.asyncio
async def test_skynet_decode_shows_failure_reason(mock_telegram, router_app_context):
    """Decode failure is reported with its real reason, not a silent stub."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.stellar_service.check_url_xdr.side_effect = Exception("tool is gone")

    url_msg = types.Message(
        message_id=214,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="https://eurmtl.me/sign_tools/2f633a09c0ffee",
    )

    update = types.Update(
        update_id=21,
        message=types.Message(
            message_id=215,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ДЕКОДИРУЙ",
            reply_to_message=url_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        "Не смог декодировать: Exception: tool is gone" in r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_skynet_remind_command(mock_telegram, router_app_context):
    """Test cmd_last_check_remind - SKYNET НАПОМНИ triggers remind."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    update = types.Update(
        update_id=8,
        message=types.Message(
            message_id=300,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET НАПОМНИ про подпись",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.talk_service.remind.called


@pytest.mark.asyncio
async def test_skynet_task_command(mock_telegram, router_app_context):
    """Test cmd_last_check_task - SKYNET задач triggers AI task analysis."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.add_task_to_google.return_value = "Task added successfully"

    update = types.Update(
        update_id=9,
        message=types.Message(
            message_id=400,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET задача: сделать что-то важное",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.add_task_to_google.called
    requests = mock_telegram.get_requests()
    # First message is "Анализирую задачу...", then result, then delete
    assert any("Task added successfully" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_task_with_reply(mock_telegram, router_app_context):
    """Test cmd_last_check_task - SKYNET задач with reply includes reply context."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.add_task_to_google.return_value = "Task created"

    reply_msg = types.Message(
        message_id=399,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Original task description",
    )

    update = types.Update(
        update_id=10,
        message=types.Message(
            message_id=400,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET задача",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.add_task_to_google.called
    # Check that the call includes reply message info
    call_args = router_app_context.ai_service.add_task_to_google.call_args
    msg_content = call_args[0][0]
    assert "other" in msg_content  # reply username should be included


@pytest.mark.asyncio
async def test_skynet_horoscope_command(mock_telegram, router_app_context):
    """Test cmd_last_check_horoscope - SKYNET гороскоп returns horoscope."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.set_horoscope(["*Овен*: Отличный день!", "*Телец*: Все будет хорошо!"])

    update = types.Update(
        update_id=11,
        message=types.Message(
            message_id=500,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET гороскоп",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Response should contain horoscope text
    assert any("Овен" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")
    assert any("Телец" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_update_not_admin(mock_telegram, router_app_context):
    """Test cmd_last_check_update - non-admin gets rejection message."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # User is NOT a skynet admin
    router_app_context.admin_service.set_skynet_admins([])

    update = types.Update(
        update_id=12,
        message=types.Message(
            message_id=600,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ОБНОВИ ОТЧЕТ",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_update_guarantors(mock_telegram, router_app_context):
    """Test cmd_last_check_update - admin can update guarantors report."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # User IS a skynet admin
    router_app_context.admin_service.set_skynet_admins(["@user"])

    update = types.Update(
        update_id=13,
        message=types.Message(
            message_id=601,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ОБНОВИ ГАРАНТОВ",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.report_service.update_guarantors_report.called
    requests = mock_telegram.get_requests()
    assert any("запустила обновление" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")
    assert any("Обновление завершено" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_update_mm(mock_telegram, router_app_context):
    """Test cmd_last_check_update - admin can update MM report."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.admin_service.set_skynet_admins(["@user"])

    update = types.Update(
        update_id=14,
        message=types.Message(
            message_id=602,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ОБНОВИ MM",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.report_service.update_mmwb_report.called


@pytest.mark.asyncio
async def test_private_message_with_telegram_link(mock_telegram, router_app_context):
    """Test handle_private_message_links - private message with t.me link."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    update = types.Update(
        update_id=15,
        message=types.Message(
            message_id=700,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Check this link: https://t.me/testgroup/123",
            entities=[types.MessageEntity(type="url", offset=17, length=28)],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should try to get chat info and respond with link info
    assert any(r["method"] == "getChat" for r in requests)


@pytest.mark.asyncio
async def test_private_message_with_text_link(mock_telegram, router_app_context):
    """Test handle_private_message_links - private message with text_link entity."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    update = types.Update(
        update_id=16,
        message=types.Message(
            message_id=701,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Click here",
            entities=[types.MessageEntity(type="text_link", offset=0, length=10, url="https://t.me/testgroup/456")],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should try to get chat info
    assert any(r["method"] == "getChat" for r in requests)


@pytest.mark.asyncio
async def test_private_message_without_telegram_link(mock_telegram, router_app_context):
    """Test handle_private_message_links - private message with non-telegram link is ignored."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=702,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Check this: https://example.com/page",
            entities=[types.MessageEntity(type="url", offset=12, length=24)],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should NOT respond with "Найдены ссылки" since it's not a telegram link
    assert not any(
        "Найдены ссылки" in r.get("data", {}).get("text", "") for r in requests if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_skynet_decode_with_pinned_url(mock_telegram, router_app_context):
    """Test cmd_last_check_decode - SKYNET ДЕКОДИРУЙ without reply uses pinned URL."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    from other.constants import BotValueTypes

    # Set up pinned URL in the database service used by the handler
    await router_app_context.db_service.save_bot_value(
        456, BotValueTypes.PinnedUrl, "https://eurmtl.me/sign_tools?xdr=pinned"
    )
    router_app_context.stellar_service.check_url_xdr.return_value = ["Pinned XDR decoded"]

    update = types.Update(
        update_id=18,
        message=types.Message(
            message_id=800,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET decode",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.check_url_xdr.called
    args, _ = router_app_context.stellar_service.check_url_xdr.call_args
    assert args[0] == "https://eurmtl.me/sign_tools?xdr=pinned"
    requests = mock_telegram.get_requests()
    assert any("Pinned XDR decoded" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_reply_to_bot_non_tracked_message(mock_telegram, router_app_context):
    """Test cmd_last_check_reply_to_bot - reply to bot message not in my_talk_message."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # my_talk_message is empty - no previous bot messages tracked

    # Bot's message that user is replying to
    bot_msg = types.Message(
        message_id=100,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=router_app_context.bot.id, is_bot=True, first_name="Bot", username="bot"),
        text="Some bot message",
    )

    update = types.Update(
        update_id=19,
        message=types.Message(
            message_id=101,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Reply to bot",
            reply_to_message=bot_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # talk should NOT be called since message is not in my_talk_message
    assert not router_app_context.ai_service.talk.called
    # But answer_notify_message should still be called
    assert router_app_context.talk_service.answer_notify_message.called


@pytest.mark.asyncio
async def test_skynet_cyrillic_prefix(mock_telegram, router_app_context):
    """Test handlers work with Cyrillic СКАЙНЕТ prefix."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    update = types.Update(
        update_id=20,
        message=types.Message(
            message_id=900,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="СКАЙНЕТ УБЕЙ кого-нибудь",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("NAP NAP NAP" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_img_command_not_allowed(mock_telegram, router_app_context):
    """Test cmd_img - user not in img users list gets rejection."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # User is NOT in the allowed list
    router_app_context.admin_service.set_skynet_img_users([])

    update = types.Update(
        update_id=21,
        message=types.Message(
            message_id=1001,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/img cat",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        "Только в канале фракции Киберократии" in r["data"]["text"] for r in requests if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_comment_command_no_reply(mock_telegram, router_app_context):
    """Test cmd_comment - without reply_to_message."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    update = types.Update(
        update_id=22,
        message=types.Message(
            message_id=1002,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/comment",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("А чего комментировать то?" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_comment_command_with_caption(mock_telegram, router_app_context):
    """Test cmd_comment - reply to message with caption (not text)."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.talk_get_comment.return_value = "Nice photo!"

    # Message with caption (like a photo message)
    reply_msg = types.Message(
        message_id=5,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        caption="Photo caption here",
    )

    update = types.Update(
        update_id=23,
        message=types.Message(
            message_id=1003,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/comment",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.talk_get_comment.called
    # Verify it was called with the caption
    call_args = router_app_context.ai_service.talk_get_comment.call_args
    assert call_args[0][1] == "Photo caption here"


@pytest.mark.asyncio
async def test_skynet_update_bim(mock_telegram, router_app_context):
    """Test cmd_last_check_update - admin can update BIM data."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.admin_service.set_skynet_admins(["@user"])

    update = types.Update(
        update_id=24,
        message=types.Message(
            message_id=1004,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ОБНОВИ BIM",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.report_service.update_bim_data.called


@pytest.mark.asyncio
async def test_skynet_update_donate(mock_telegram, router_app_context):
    """Test cmd_last_check_update - admin can update donate report."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.admin_service.set_skynet_admins(["@user"])

    update = types.Update(
        update_id=25,
        message=types.Message(
            message_id=1005,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ОБНОВИ donate",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.report_service.update_donate_report.called


@pytest.mark.asyncio
async def test_skynet4_in_non_cyber_group(mock_telegram, router_app_context):
    """Test cmd_last_check_p - SKYNET 4 (with space) outside CyberGroup gets rejection."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # The check is: len(message.text) > 7 and message.text[7] == '4'
    # "SKYNET 4" has '4' at index 7
    update = types.Update(
        update_id=26,
        message=types.Message(
            message_id=1006,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),  # Not CyberGroup
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET 4 hello",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        "Только в канале фракции Киберократии" in r["data"].get("text", "")
        for r in requests
        if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_skynet_talk_with_reply_context(mock_telegram, router_app_context):
    """Test cmd_last_check_p - SKYNET with reply includes reply context."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.talk.return_value = "Response with context"

    reply_msg = types.Message(
        message_id=1099,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Original message context",
    )

    update = types.Update(
        update_id=27,
        message=types.Message(
            message_id=1100,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET what about this?",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.talk.called
    call_args = router_app_context.ai_service.talk.call_args
    msg_content = call_args[0][1]
    # Should include both original message and the reply
    assert "Original message context" in msg_content
    assert "what about this?" in msg_content


@pytest.mark.asyncio
async def test_skynet_talk_with_googleit(mock_telegram, router_app_context):
    """Test cmd_last_check_p - SKYNET with загугли keyword."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.talk.return_value = "Search result"

    update = types.Update(
        update_id=28,
        message=types.Message(
            message_id=1101,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET загугли про погоду",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.talk.called
    call_args = router_app_context.ai_service.talk.call_args
    # Should pass googleit=True
    assert call_args[1].get("googleit") is True


@pytest.mark.asyncio
async def test_skynet_talk_connection_error(mock_telegram, router_app_context):
    """Test cmd_last_check_p - AI service returns None (connection error)."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.talk.return_value = None

    update = types.Update(
        update_id=29,
        message=types.Message(
            message_id=1102,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET hello",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("connection error" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_decode_with_text_link_entity(mock_telegram, router_app_context):
    """Test cmd_last_check_decode - decode with text_link entity in reply."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.stellar_service.check_url_xdr.return_value = ["Decoded from link"]

    # Message with text_link entity
    url_msg = types.Message(
        message_id=200,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Click here to sign",
        entities=[
            types.MessageEntity(type="text_link", offset=0, length=18, url="https://eurmtl.me/sign_tools?xdr=abc123")
        ],
    )

    update = types.Update(
        update_id=30,
        message=types.Message(
            message_id=1200,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ДЕКОДИРУЙ",
            reply_to_message=url_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.check_url_xdr.called


@pytest.mark.asyncio
async def test_skynet_decode_with_non_matching_url(mock_telegram, router_app_context):
    """Test cmd_last_check_decode - decode with URL that doesn't match eurmtl.me."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # Message with URL that is NOT eurmtl.me
    url_msg = types.Message(
        message_id=200,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Check this",
        entities=[types.MessageEntity(type="url", offset=0, length=10, url="https://example.com/something")],
    )

    update = types.Update(
        update_id=31,
        message=types.Message(
            message_id=1201,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ДЕКОДИРУЙ",
            reply_to_message=url_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("Ссылка не найдена" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_private_link_with_found_links_response(mock_telegram, router_app_context):
    """Test handle_private_message_links - verifies 'Найдены ссылки' response."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    update = types.Update(
        update_id=32,
        message=types.Message(
            message_id=1300,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Look at https://t.me/c/1234567890/100",
            entities=[types.MessageEntity(type="url", offset=8, length=31)],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should respond with found links
    assert any("Найдены ссылки" in r.get("data", {}).get("text", "") for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_in_group_adds_to_my_talk_message(mock_telegram, router_app_context):
    """Test cmd_last_check_p - bot response in group is tracked in my_talk_message."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.talk.return_value = "Group response"

    update = types.Update(
        update_id=33,
        message=types.Message(
            message_id=1400,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET hello there",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Check that the response message was added to my_talk_message
    assert len(my_talk_message) > 0
    assert any("456" in msg for msg in my_talk_message)


@pytest.mark.asyncio
async def test_register_handlers_function():
    """Test register_handlers function."""
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from routers.talk_handlers import register_handlers

    dp = Dispatcher(storage=MemoryStorage())

    # Call register_handlers
    register_handlers(dp, None)

    # Verify the router was included
    assert talk_router in dp.sub_routers


@pytest.mark.asyncio
async def test_skynet_private_message_does_not_track(mock_telegram, router_app_context):
    """Test cmd_last_check_p - private chat messages are not tracked in my_talk_message."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    my_talk_message.clear()  # Ensure clean state

    router_app_context.ai_service.talk.return_value = "Private response"

    update = types.Update(
        update_id=34,
        message=types.Message(
            message_id=1500,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET hello",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # In private chat, message should NOT be added to my_talk_message
    # (since the handler checks chat.type != PRIVATE for tracking)
    assert len(my_talk_message) == 0


@pytest.mark.asyncio
async def test_skynet4_in_cyber_group(mock_telegram, router_app_context):
    """Test cmd_last_check_p - SKYNET 4 (with space) in CyberGroup enables gpt4 mode."""
    from other.constants import MTLChats

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.talk.return_value = "GPT4 response"

    # The check is: len(message.text) > 7 and message.text[7] == '4'
    # "SKYNET 4" has '4' at index 7
    update = types.Update(
        update_id=35,
        message=types.Message(
            message_id=1600,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.CyberGroup, type="supergroup", title="Cyber Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET 4 hello",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.talk.called
    call_args = router_app_context.ai_service.talk.call_args
    # Third positional argument should be True for gpt4
    assert call_args[0][2] is True


@pytest.mark.asyncio
async def test_reply_to_bot_markdown_fallback(mock_telegram, router_app_context):
    """Test cmd_last_check_reply_to_bot - fallback when markdown fails."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # Simulate bot's previous message being in my_talk_message
    my_talk_message.append("100*456")

    # Return text with markdown that might cause issues
    router_app_context.ai_service.talk.return_value = "Response with *unclosed markdown"

    # Bot's message that user is replying to
    bot_msg = types.Message(
        message_id=100,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=router_app_context.bot.id, is_bot=True, first_name="Bot", username="bot"),
        text="Previous bot message",
    )

    update = types.Update(
        update_id=36,
        message=types.Message(
            message_id=1700,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Reply to bot",
            reply_to_message=bot_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.talk.called
    requests = mock_telegram.get_requests()
    assert any("unclosed markdown" in r["data"].get("text", "") for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_markdown_fallback(mock_telegram, router_app_context):
    """Test cmd_last_check_p - fallback when markdown parsing fails."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # Return text that might cause markdown issues
    router_app_context.ai_service.talk.return_value = "Code: `unclosed backtick"

    update = types.Update(
        update_id=37,
        message=types.Message(
            message_id=1800,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET test",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should still get the message even if markdown fails
    assert any("unclosed backtick" in r["data"].get("text", "") for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_update_report(mock_telegram, router_app_context):
    """Test cmd_last_check_update - admin can update main report."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.admin_service.set_skynet_admins(["@user"])

    update = types.Update(
        update_id=38,
        message=types.Message(
            message_id=1900,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ОБНОВИ ОТЧЕТ",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.report_service.update_main_report.called
    requests = mock_telegram.get_requests()
    assert any("запустила обновление" in r["data"].get("text", "") for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_skynet_update_report_english(mock_telegram, router_app_context):
    """Test cmd_last_check_update - admin can update report using English keyword."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.admin_service.set_skynet_admins(["@user"])

    update = types.Update(
        update_id=39,
        message=types.Message(
            message_id=2000,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ОБНОВИ report",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.report_service.update_main_report.called


@pytest.mark.asyncio
async def test_decode_with_url_in_text(mock_telegram, router_app_context):
    """Test cmd_last_check_decode - decode with eurmtl.me URL directly in text."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.stellar_service.check_url_xdr.return_value = ["Direct URL decoded"]

    # Message with URL directly in text
    url_msg = types.Message(
        message_id=2001,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Sign here: https://eurmtl.me/sign_tools?xdr=direct",
    )

    update = types.Update(
        update_id=40,
        message=types.Message(
            message_id=2002,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET ДЕКОДИРУЙ",
            reply_to_message=url_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.check_url_xdr.called


@pytest.mark.asyncio
async def test_img_command_in_cyber_group(mock_telegram, router_app_context):
    """Test cmd_img - works in CyberGroup regardless of user list."""
    from other.constants import MTLChats

    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # User is NOT in the allowed list, but is in CyberGroup
    router_app_context.admin_service.set_skynet_img_users([])

    file_bytes = b"img"
    mock_telegram.add_file("img1", file_bytes, file_path="files/img.png")
    image_url = f"{mock_telegram.base_url}/file/bot{router_app_context.bot.token}/files/img.png"
    router_app_context.ai_service.generate_image.return_value = [image_url]

    update = types.Update(
        update_id=41,
        message=types.Message(
            message_id=2100,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.CyberGroup, type="supergroup", title="Cyber Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/img cyber cat",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.ai_service.generate_image.called
    requests = mock_telegram.get_requests()
    assert any(r["method"] == "sendPhoto" for r in requests)


@pytest.mark.asyncio
async def test_private_link_telegram_bad_request(mock_telegram, router_app_context):
    """Test handle_private_message_links - handles TelegramBadRequest error."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # Configure mock to return error for getChat
    mock_telegram.add_response(
        "getChat", {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
    )

    update = types.Update(
        update_id=42,
        message=types.Message(
            message_id=2200,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Check https://t.me/c/999999999/123",
            entities=[types.MessageEntity(type="url", offset=6, length=30)],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should still try to process the link
    assert any(r["method"] == "getChat" for r in requests)


@pytest.mark.asyncio
async def test_is_skynet_img_user_helper():
    """Test _is_skynet_img_user helper function."""
    from routers.talk_handlers import _is_skynet_img_user
    from tests.fakes import FakeAdminService

    # Create a simple app_context mock
    class MockAppContext:
        def __init__(self):
            self.admin_service = FakeAdminService()

    app_ctx = MockAppContext()
    app_ctx.admin_service.set_skynet_img_users(["@testuser"])

    # Test allowed user
    assert _is_skynet_img_user("testuser", app_ctx) is True
    assert _is_skynet_img_user("@testuser", app_ctx) is True

    # Test not allowed user
    assert _is_skynet_img_user("otheruser", app_ctx) is False


@pytest.mark.asyncio
async def test_skyuser_is_skynet_admin():
    """Test SkyUser.is_skynet_admin helper behavior."""
    from services.skyuser import SkyUser
    from tests.fakes import FakeAdminService

    class MockAppContext:
        def __init__(self):
            self.admin_service = FakeAdminService()

    app_ctx = MockAppContext()
    app_ctx.admin_service.set_skynet_admins(["@testuser"])

    skyuser = SkyUser(
        user_id=1,
        username="testuser",
        chat_id=1,
        sender_chat_id=None,
        bot=None,
        app_context=app_ctx,
    )

    assert skyuser.is_skynet_admin() is True

    app_ctx.admin_service.set_skynet_admins([])
    assert skyuser.is_skynet_admin() is False


@pytest.mark.asyncio
async def test_is_skynet_img_user_no_admin_service():
    """Test _is_skynet_img_user raises ValueError when admin_service missing."""
    from routers.talk_handlers import _is_skynet_img_user
    import pytest as pt

    class MockAppContext:
        def __init__(self):
            self.admin_service = None

    with pt.raises(ValueError, match="app_context with admin_service required"):
        _is_skynet_img_user("user", MockAppContext())

    with pt.raises(ValueError, match="app_context with admin_service required"):
        _is_skynet_img_user("user", None)


@pytest.mark.asyncio
async def test_skyuser_is_skynet_admin_no_admin_service():
    """Test SkyUser.is_skynet_admin raises ValueError when admin_service missing."""
    from services.skyuser import SkyUser
    import pytest as pt

    class MockAppContext:
        def __init__(self):
            self.admin_service = None

    skyuser = SkyUser(
        user_id=1,
        username="testuser",
        chat_id=1,
        sender_chat_id=None,
        bot=None,
        app_context=MockAppContext(),
    )

    with pt.raises(ValueError, match="app_context with admin_service required"):
        skyuser.is_skynet_admin()

    skyuser_no_ctx = SkyUser(
        user_id=1,
        username="testuser",
        chat_id=1,
        sender_chat_id=None,
        bot=None,
        app_context=None,
    )

    with pt.raises(ValueError, match="app_context with admin_service required"):
        skyuser_no_ctx.is_skynet_admin()


@pytest.mark.asyncio
async def test_private_message_non_entity(mock_telegram, router_app_context):
    """Test handle_private_message_links - message with other entity types."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # Message with non-url entity (e.g., mention)
    update = types.Update(
        update_id=43,
        message=types.Message(
            message_id=2300,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Hello @someone",
            entities=[types.MessageEntity(type="mention", offset=6, length=8)],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should NOT try to process non-URL entities
    assert not any(
        "Найдены ссылки" in r.get("data", {}).get("text", "") for r in requests if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_private_message_url_not_telegram(mock_telegram, router_app_context):
    """Test handle_private_message_links - URL entity that's not t.me."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    update = types.Update(
        update_id=44,
        message=types.Message(
            message_id=2400,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Check https://google.com/search",
            entities=[types.MessageEntity(type="url", offset=6, length=25)],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should NOT respond since URL is not t.me
    assert not any(
        "Найдены ссылки" in r.get("data", {}).get("text", "") for r in requests if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_decode_with_multiple_url_entities(mock_telegram, router_app_context):
    """Test cmd_last_check_decode - decode with multiple URL entities, only one valid."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.stellar_service.check_url_xdr.return_value = ["Found valid URL"]

    # Message with multiple URLs, only one is eurmtl.me
    url_msg = types.Message(
        message_id=2500,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Links: https://example.com and https://eurmtl.me/sign_tools?xdr=valid",
        entities=[
            types.MessageEntity(type="url", offset=7, length=20),
            types.MessageEntity(type="url", offset=32, length=42),
        ],
    )

    update = types.Update(
        update_id=45,
        message=types.Message(
            message_id=2501,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="SKYNET decode",
            reply_to_message=url_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.check_url_xdr.called


@pytest.mark.asyncio
async def test_comment_delete_fails(mock_telegram, router_app_context):
    """Test cmd_comment - message.delete() raises exception but comment still works."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    router_app_context.ai_service.talk_get_comment.return_value = "Nice comment!"

    # Make deleteMessage fail
    mock_telegram.add_response(
        "deleteMessage", {"ok": False, "error_code": 400, "description": "message can't be deleted"}
    )

    reply_msg = types.Message(
        message_id=3000,
        date=datetime.datetime.now(),
        chat=types.Chat(id=456, type="supergroup", title="Group"),
        from_user=types.User(id=789, is_bot=False, first_name="Other", username="other"),
        text="Some text to comment on",
    )

    update = types.Update(
        update_id=46,
        message=types.Message(
            message_id=3001,
            date=datetime.datetime.now(),
            chat=types.Chat(id=456, type="supergroup", title="Group"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="/comment",
            reply_to_message=reply_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Comment should still be posted even if delete failed
    assert router_app_context.ai_service.talk_get_comment.called
    requests = mock_telegram.get_requests()
    assert any("Nice comment!" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_private_link_with_thread_name(mock_telegram, router_app_context, monkeypatch):
    """Test handle_private_message_links - telegram link with thread_name."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # Mock pyro_update_msg_info to set thread_name
    async def mock_pyro_update(msg_info):
        msg_info.thread_name = "Test Topic"
        msg_info.chat_name = "Test Chat"

    import routers.talk_handlers

    monkeypatch.setattr(routers.talk_handlers, "pyro_update_msg_info", mock_pyro_update)

    update = types.Update(
        update_id=47,
        message=types.Message(
            message_id=3100,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Check this: https://t.me/c/1234567890/999",
            entities=[types.MessageEntity(type="url", offset=12, length=32)],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should contain thread_name in response
    send_messages = [r for r in requests if r["method"] == "sendMessage"]
    assert len(send_messages) > 0
    assert any("Топик" in r["data"]["text"] and "Test Topic" in r["data"]["text"] for r in send_messages)


@pytest.mark.asyncio
async def test_private_link_with_message_text_preview(mock_telegram, router_app_context, monkeypatch):
    """Test handle_private_message_links - telegram link with message_text creates preview button."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(talk_router)

    # Mock pyro_update_msg_info to set message_text
    async def mock_pyro_update(msg_info):
        msg_info.message_text = "This is the message content"
        msg_info.chat_name = "Test Chat"

    import routers.talk_handlers

    monkeypatch.setattr(routers.talk_handlers, "pyro_update_msg_info", mock_pyro_update)

    # Mock miniapps.create_uuid_page
    from unittest.mock import Mock

    mock_page = Mock()
    mock_page.url = "https://telegra.ph/preview-123"

    async def mock_create_page(msg_info):
        return mock_page

    monkeypatch.setattr(routers.talk_handlers.miniapps, "create_uuid_page", mock_create_page)

    update = types.Update(
        update_id=48,
        message=types.Message(
            message_id=3200,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="private"),
            from_user=types.User(id=123, is_bot=False, first_name="User", username="user"),
            text="Check this: https://t.me/c/1234567890/888",
            entities=[types.MessageEntity(type="url", offset=12, length=32)],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    send_messages = [r for r in requests if r["method"] == "sendMessage"]
    assert len(send_messages) > 0
    # Should have reply_markup with buttons
    assert any("reply_markup" in r["data"] for r in send_messages)
    # Should have "предпросмотр сообщений" text
    assert any("предпросмотр" in r["data"]["text"] for r in send_messages)
