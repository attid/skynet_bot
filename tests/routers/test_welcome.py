import datetime
import json
import pytest
from aiogram import types

from routers.welcome import router as welcome_router, CaptchaCallbackData, EmojiCaptchaCallbackData, JoinCallbackData
from tests.conftest import RouterTestMiddleware
from other.constants import MTLChats, BotValueTypes

# --- Existing Tests (Router Integration) ---


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if welcome_router.parent_router:
        welcome_router._parent_router = None


@pytest.mark.asyncio
async def test_set_welcome_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup", title="Test Chat"),
            from_user=types.User(id=123456, is_bot=False, first_name="Admin", username="admin"),
            text="/set_welcome Hello $$USER$$",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify config_service was updated (DI service interface)
    assert router_app_context.config_service.get_welcome_message(MTLChats.TestGroup) == "Hello $$USER$$"

    # Verify reply
    requests = mock_telegram.get_requests()
    assert any("Added" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_new_chat_member_welcome(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    # Set welcome message via DI service
    router_app_context.config_service.set_welcome_message(MTLChats.TestGroup, "Welcome $$USER$$!")

    # Mocks
    user = types.User(id=123, is_bot=False, first_name="Joiner", username="joiner")
    router_app_context.antispam_service.combo_check_spammer.return_value = False
    router_app_context.antispam_service.lols_check_spammer.return_value = False
    router_app_context.group_service.enforce_entry_channel.return_value = (True, None)
    router_app_context.config_service.set_user_status(user.id, 0)

    event = types.ChatMemberUpdated(
        chat=types.Chat(id=MTLChats.TestGroup, type="supergroup", title="Test Chat"),
        from_user=user,
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberLeft(user=user),
        new_chat_member=types.ChatMemberMember(user=user),
    )

    update = types.Update(update_id=2, chat_member=event)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Note: ChatsRepository(session).add_user_to_chat is now called directly, not config_service
    # Verify welcome message was sent
    requests = mock_telegram.get_requests()
    assert any("Welcome" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_new_chat_member_with_selfmod_skips_captcha(mock_telegram, router_app_context):
    """When selfmod is enabled, new joiners get a vote instead of captcha."""
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = MTLChats.TestGroup
    router_app_context.feature_flags.enable(chat_id, "selfmod")
    # Set a welcome message that should NOT be sent (selfmod replaces captcha+welcome flow)
    router_app_context.config_service.set_welcome_message(chat_id, "Welcome $$USER$$!")

    user = types.User(id=8888, is_bot=False, first_name="Joiner", username="joiner")
    router_app_context.antispam_service.combo_check_spammer.return_value = False
    router_app_context.antispam_service.lols_check_spammer.return_value = False
    router_app_context.group_service.enforce_entry_channel.return_value = (True, None)
    router_app_context.config_service.set_user_status(user.id, 0)

    event = types.ChatMemberUpdated(
        chat=types.Chat(id=chat_id, type="supergroup", title="Test Chat"),
        from_user=user,
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberLeft(user=user),
        new_chat_member=types.ChatMemberMember(user=user),
    )

    await dp.feed_update(bot=router_app_context.bot, update=types.Update(update_id=42, chat_member=event))

    requests = mock_telegram.get_requests()
    methods = [r["method"] for r in requests]
    # restrict_chat_member is called by begin_join_vote
    assert "restrictChatMember" in methods
    # The "Welcome ..." captcha message must NOT appear
    welcome_texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert not any("Welcome Joiner" in t for t in welcome_texts), "Captcha welcome should be skipped under selfmod"
    # A vote message was posted instead
    assert any("wants to join" in t for t in welcome_texts)


@pytest.mark.asyncio
async def test_stop_exchange_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])

    router_app_context.stellar_service.stop_all_exchange.return_value = None

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=3,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup", title="Test Chat"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/stop_exchange",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.stop_all_exchange.called
    requests = mock_telegram.get_requests()
    assert any("Was stop" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_join_request(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_join_request.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    # Configure notification_service (DI) instead of global_data.notify_join
    router_app_context.notification_service.set_join_notify(MTLChats.TestGroup, "123456")

    update = types.Update(
        update_id=4,
        chat_join_request=types.ChatJoinRequest(
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup", title="Test Chat"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            user_chat_id=999,
            date=datetime.datetime.now(),
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("Новый участник" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_cq_join(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    cb_data = JoinCallbackData(user_id=1, chat_id=MTLChats.TestGroup, can_join=True).pack()

    update = types.Update(
        update_id=5,
        callback_query=types.CallbackQuery(
            id="cb1",
            chat_instance="ci1",
            from_user=types.User(id=123456, is_bot=False, first_name="Admin", username="admin"),
            message=types.Message(
                message_id=10, date=datetime.datetime.now(), chat=types.Chat(id=123, type="supergroup"), text="Join req"
            ),
            data=cb_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "approveChatJoinRequest" for r in requests)
    assert any("✅" in r["data"]["text"] for r in requests if r["method"] == "answerCallbackQuery")


# --- Additional Router Integration Tests (No Fake Bot/Message) ---


def build_chat_member_update(user, chat_id=-1001, update_id=200):
    event = types.ChatMemberUpdated(
        chat=types.Chat(id=chat_id, type="supergroup", title="Test Chat"),
        from_user=user,
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberLeft(user=user),
        new_chat_member=types.ChatMemberMember(user=user),
    )
    return types.Update(update_id=update_id, chat_member=event)


def _can_send_messages_value(req_data: dict) -> object:
    permissions = req_data.get("permissions")
    if isinstance(permissions, str):
        permissions = json.loads(permissions)
    if not isinstance(permissions, dict):
        raise AssertionError(f"Unexpected permissions payload type: {type(permissions)!r}")
    return permissions["can_send_messages"]


@pytest.mark.asyncio
async def test_cas_spam_ban(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    router_app_context.antispam_service.combo_check_spammer.return_value = True
    user = types.User(id=123, is_bot=False, first_name="Test", username="testuser")
    update = build_chat_member_update(user, chat_id=-1001, update_id=201)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "banChatMember" for r in requests)
    cas_report = next(
        (r for r in requests if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(MTLChats.SpamGroup)),
        None,
    )
    assert cas_report is not None
    assert "CAS ban" in cas_report["data"]["text"]
    assert "Причина:" in cas_report["data"]["text"]


@pytest.mark.asyncio
async def test_lols_spam_ban(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    router_app_context.antispam_service.lols_check_spammer.return_value = True
    user = types.User(id=123, is_bot=False, first_name="Test", username="testuser")
    update = build_chat_member_update(user, chat_id=-1002, update_id=202)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "banChatMember" for r in requests)
    lols_report = next(
        (r for r in requests if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(MTLChats.SpamGroup)),
        None,
    )
    assert lols_report is not None
    assert "LOLS base" in lols_report["data"]["text"]
    assert "Причина:" in lols_report["data"]["text"]


@pytest.mark.asyncio
async def test_forbidden_name_ban(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    bad_user = types.User(id=666, is_bot=False, first_name="ЧВК ВАГНЕР", username="badguy")
    update = build_chat_member_update(bad_user, chat_id=-1003, update_id=203)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "banChatMember" for r in requests)
    forbidden_report = next(
        (r for r in requests if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(MTLChats.SpamGroup)),
        None,
    )
    assert forbidden_report is not None
    assert "запрещенного никнейма" in forbidden_report["data"]["text"]
    assert "Причина:" in forbidden_report["data"]["text"]


@pytest.mark.asyncio
async def test_existing_banned_user(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    user = types.User(id=777, is_bot=False, first_name="Test", username="testuser")
    # Set user as banned (user_type=2) in the shared session
    router_app_context.session.set_user(user.id, user_type=2, user_name="testuser")
    update = build_chat_member_update(user, chat_id=-1004, update_id=204)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "banChatMember" for r in requests)
    # Message goes to SpamGroup, not the chat, and includes unban moderation artifact
    spam_report = next(
        (r for r in requests if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(MTLChats.SpamGroup)),
        None,
    )
    assert spam_report is not None
    assert "was banned" in spam_report["data"]["text"]
    assert "SpamStatus.BAD (db)" in spam_report["data"]["text"]
    assert "unban" in str(spam_report["data"].get("reply_markup", ""))


@pytest.mark.asyncio
async def test_manual_kicked_by_regular_admin_sends_spam_report(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1002042
    kicked_user = types.User(id=888777, is_bot=False, first_name="Victim", username="victim")
    admin_user = types.User(id=321654, is_bot=False, first_name="Moderator", username="moderator")

    router_app_context.admin_service.set_skynet_admins([])
    router_app_context.admin_service.set_chat_admins(chat_id, [admin_user.id])
    router_app_context.group_service.check_membership.return_value = (False, None)

    event = types.ChatMemberUpdated(
        chat=types.Chat(id=chat_id, type="supergroup", title="Manual Ban Chat"),
        from_user=admin_user,
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberMember(user=kicked_user),
        new_chat_member=types.ChatMemberBanned(user=kicked_user, until_date=datetime.datetime.now()),
    )

    await dp.feed_update(bot=router_app_context.bot, update=types.Update(update_id=205, chat_member=event))

    requests = mock_telegram.get_requests()
    spam_report = next(
        (r for r in requests if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(MTLChats.SpamGroup)),
        None,
    )
    assert spam_report is not None
    assert "Причина:" in spam_report["data"]["text"]
    assert "Banned manually by chat admin" in spam_report["data"]["text"]
    assert "Кем:" in spam_report["data"]["text"]


@pytest.mark.asyncio
async def test_auto_ban_does_not_emit_followup_manual_log_from_bot(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1002043
    user = types.User(id=909090, is_bot=False, first_name="Echo", username="echo_agent")
    bot_user = types.User(id=router_app_context.bot.id, is_bot=True, first_name="SkyNet", username="myMTLbot")

    router_app_context.session.set_user(user.id, user_type=2, user_name="echo_agent")

    join_event = types.ChatMemberUpdated(
        chat=types.Chat(id=chat_id, type="supergroup", title="Auto Ban Chat"),
        from_user=bot_user,
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberLeft(user=user),
        new_chat_member=types.ChatMemberMember(user=user),
    )
    kicked_event = types.ChatMemberUpdated(
        chat=types.Chat(id=chat_id, type="supergroup", title="Auto Ban Chat"),
        from_user=bot_user,
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberMember(user=user),
        new_chat_member=types.ChatMemberBanned(user=user, until_date=datetime.datetime.now()),
    )

    await dp.feed_update(bot=router_app_context.bot, update=types.Update(update_id=206, chat_member=join_event))
    await dp.feed_update(bot=router_app_context.bot, update=types.Update(update_id=207, chat_member=kicked_event))

    spam_reports = [
        r
        for r in mock_telegram.get_requests()
        if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(MTLChats.SpamGroup)
    ]
    assert len(spam_reports) == 1
    assert "SpamStatus.BAD (db)" in spam_reports[0]["data"]["text"]
    assert "Banned manually by chat admin" not in spam_reports[0]["data"]["text"]


@pytest.mark.asyncio
async def test_manual_kicked_by_other_bot_still_sends_spam_report(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1002044
    kicked_user = types.User(id=100200, is_bot=False, first_name="Victim", username="victim")
    other_bot = types.User(id=999999001, is_bot=True, first_name="HelperBot", username="helper_bot")

    event = types.ChatMemberUpdated(
        chat=types.Chat(id=chat_id, type="supergroup", title="Bot Admin Chat"),
        from_user=other_bot,
        date=datetime.datetime.now(),
        old_chat_member=types.ChatMemberMember(user=kicked_user),
        new_chat_member=types.ChatMemberBanned(user=kicked_user, until_date=datetime.datetime.now()),
    )

    await dp.feed_update(bot=router_app_context.bot, update=types.Update(update_id=208, chat_member=event))

    requests = mock_telegram.get_requests()
    spam_report = next(
        (r for r in requests if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(MTLChats.SpamGroup)),
        None,
    )
    assert spam_report is not None
    assert "Banned manually by chat admin" in spam_report["data"]["text"]
    assert "@helper_bot" in spam_report["data"]["text"]


@pytest.mark.asyncio
async def test_entry_channel_enforcement_fail(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1005
    user = types.User(id=888, is_bot=False, first_name="Test", username="testuser")
    # Set entry_channel via config_service (DI)
    router_app_context.config_service._bot_values[(chat_id, "entry_channel")] = -100999
    router_app_context.group_service.enforce_entry_channel.return_value = (False, "Join channel")
    update = build_chat_member_update(user, chat_id=chat_id, update_id=205)

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert not router_app_context.config_service.add_user_to_chat.called
    requests = mock_telegram.get_requests()
    assert not any(r["method"] == "sendMessage" for r in requests)


@pytest.mark.asyncio
async def test_welcome_message_simple(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1006
    user = types.User(id=123, is_bot=False, first_name="Test", username="testuser")
    # Set welcome message via DI service
    router_app_context.config_service.set_welcome_message(chat_id, "Hello $$USER$$!")

    update = build_chat_member_update(user, chat_id=chat_id, update_id=206)
    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next(
        (r for r in requests if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(chat_id)), None
    )
    assert msg_req is not None
    assert "$$USER$$" not in msg_req["data"]["text"]
    assert len(router_app_context.utils_service.sleep_and_delete_calls) == 1


@pytest.mark.asyncio
async def test_welcome_captcha(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1007
    user = types.User(id=123, is_bot=False, first_name="Test", username="testuser")
    # Set welcome message and captcha via DI services
    router_app_context.config_service.set_welcome_message(chat_id, "Welcome")
    router_app_context.feature_flags.enable(chat_id, "captcha")
    router_app_context.config_service.set_welcome_button(chat_id, "Click me")

    update = build_chat_member_update(user, chat_id=chat_id, update_id=207)
    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    restrict_req = next((r for r in requests if r["method"] == "restrictChatMember"), None)
    assert restrict_req is not None
    assert str(restrict_req["data"]["chat_id"]) == str(chat_id)
    assert str(restrict_req["data"]["user_id"]) == str(user.id)
    can_send_messages = _can_send_messages_value(restrict_req["data"])
    assert can_send_messages in (False, "false", "False", 0, "0")
    msg_req = next(
        (r for r in requests if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(chat_id)), None
    )
    assert msg_req is not None
    assert msg_req["data"].get("reply_markup") is not None


@pytest.mark.asyncio
async def test_auto_all_manager_add(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1008
    user = types.User(id=123, is_bot=False, first_name="Test", username="testuser")
    # Enable auto_all via DI service
    router_app_context.feature_flags.enable(chat_id, "auto_all")
    # Set up existing members in the shared session
    router_app_context.session.set_bot_config(chat_id, BotValueTypes.All, '["@existing"]')

    update = build_chat_member_update(user, chat_id=chat_id, update_id=208)
    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify the session now has the updated members list
    # ConfigRepository._prepare_chat_value parses JSON strings to Python objects
    saved_value = router_app_context.session.get_bot_config(chat_id, BotValueTypes.All)
    # saved_value can be a list (after _prepare_chat_value) or a string
    if isinstance(saved_value, str):
        members = json.loads(saved_value)
    else:
        members = saved_value if saved_value else []
    assert "@testuser" in members
    assert "@existing" in members


@pytest.mark.asyncio
async def test_welcome_emoji_captcha(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1009
    user = types.User(id=123, is_bot=False, first_name="Test", username="testuser")
    # Set welcome message and captcha via DI services
    router_app_context.config_service.set_welcome_message(chat_id, "Click the $$COLOR$$ button")
    router_app_context.feature_flags.enable(chat_id, "captcha")

    update = build_chat_member_update(user, chat_id=chat_id, update_id=209)
    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    msg_req = next(
        (r for r in requests if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(chat_id)), None
    )
    assert msg_req is not None
    assert "$$COLOR$$" not in msg_req["data"]["text"]
    assert msg_req["data"].get("reply_markup") is not None


@pytest.mark.asyncio
async def test_auto_all_no_username(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.chat_member.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1010
    user = types.User(id=777, is_bot=False, first_name="NoUser", username=None)
    # Enable auto_all via DI service
    router_app_context.feature_flags.enable(chat_id, "auto_all")

    update = build_chat_member_update(user, chat_id=chat_id, update_id=210)
    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify the "dont have username" message was sent
    requests = mock_telegram.get_requests()
    assert any("dont have username" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_cq_captcha_restores_permissions(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1011
    user_id = 123

    # Callback data must match user_id
    cb_data = CaptchaCallbackData(answer=user_id).pack()

    update = types.Update(
        update_id=211,
        callback_query=types.CallbackQuery(
            id="cb_captcha",
            chat_instance="ci_captcha",
            from_user=types.User(id=user_id, is_bot=False, first_name="User", username="user"),
            message=types.Message(
                message_id=11,
                date=datetime.datetime.now(),
                chat=types.Chat(id=chat_id, type="supergroup", title="Test Chat"),
                text="Welcome",
            ),
            data=cb_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()

    # Verify restrictChatMember was called
    restrict_req = next((r for r in requests if r["method"] == "restrictChatMember"), None)
    assert restrict_req is not None
    assert int(restrict_req["data"]["user_id"]) == user_id
    assert int(restrict_req["data"]["chat_id"]) == chat_id
    can_send_messages = _can_send_messages_value(restrict_req["data"])
    assert can_send_messages in (True, "true", "True", 1, "1")

    # Verify until_date is present
    # Aiogram converts timedelta to timestamp (int)
    until_date = restrict_req["data"].get("until_date")
    assert until_date is not None
    assert int(until_date) > datetime.datetime.now().timestamp()


@pytest.mark.asyncio
async def test_cq_emoji_captcha_wrong_answer_edits_message_with_contact(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(welcome_router)

    chat_id = -1012
    user_id = 123

    cb_data = EmojiCaptchaCallbackData(user_id=user_id, square="🟥", num=1001).pack()

    update = types.Update(
        update_id=212,
        callback_query=types.CallbackQuery(
            id="cb_emoji_captcha_wrong",
            chat_instance="ci_emoji_captcha_wrong",
            from_user=types.User(id=user_id, is_bot=False, first_name="User", username="user"),
            message=types.Message(
                message_id=12,
                date=datetime.datetime.now(),
                chat=types.Chat(id=chat_id, type="supergroup", title="Test Chat"),
                text=(
                    "Welcome. Read the rules.\n\n"
                    "Подтвердите, что вы не бот — нажмите на кнопку 🔴\n"
                    "Confirm that you are not a bot — click on the button 🔴\n"
                    "Potvrdite da niste bot — kliknite na gumb 🔴"
                ),
            ),
            data=cb_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()

    answer_req = next((r for r in requests if r["method"] == "answerCallbackQuery"), None)
    assert answer_req is not None
    assert answer_req["data"]["text"] == "Wrong answer"
    assert answer_req["data"]["show_alert"] in (True, "true", "True", 1, "1")

    edit_req = next((r for r in requests if r["method"] == "editMessageText"), None)
    assert edit_req is not None
    assert "Welcome. Read the rules." in edit_req["data"]["text"]
    assert "Подтвердите, что вы не бот" not in edit_req["data"]["text"]
    assert "Confirm that you are not a bot" not in edit_req["data"]["text"]
    assert "Potvrdite da niste bot" not in edit_req["data"]["text"]
    assert "🔴" not in edit_req["data"]["text"]
    assert "Ответ неверный" in edit_req["data"]["text"]
    assert "Wrong answer" in edit_req["data"]["text"]
    assert "@mtl_helper_bot" in edit_req["data"]["text"]
    assert "reply_markup" not in edit_req["data"] or edit_req["data"]["reply_markup"] in (None, "null")

    assert not any(r["method"] == "restrictChatMember" for r in requests)
