import pytest
import datetime
from aiogram import types

from routers.stellar import router as stellar_router
from tests.conftest import RouterTestMiddleware
from tests.fakes import FakeWebResponse
from other.constants import MTLChats


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if stellar_router.parent_router:
        stellar_router._parent_router = None
    pass


@pytest.mark.asyncio
async def test_fee_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.check_fee.return_value = "100-200 stroops"

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/fee",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "100-200 stroops" in req["data"]["text"]


@pytest.mark.asyncio
async def test_decode_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.decode_xdr.return_value = ["Decoded", "XDR"]

    update = types.Update(
        update_id=2,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/decode AAAA...",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("Decoded" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_show_bim_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.show_bim.return_value = "BIM Info"

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=3,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/show_bim",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "BIM Info" in req["data"]["text"]


@pytest.mark.asyncio
async def test_do_council(mock_telegram, router_app_context):
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    balances = [
        {"EURMTL": 6, "LABR": 0.2},
        {"LABR": 2},
    ]
    router_app_context.stellar_service.get_balances.side_effect = lambda *args, **kwargs: balances.pop(0)
    router_app_context.web_service.get.return_value = FakeWebResponse(
        {"distribution": {"GABC...": 10}, "xdr": "AAAA..."}
    )
    router_app_context.stellar_service.build_swap_xdr.return_value = "SWAP_XDR"
    router_app_context.stellar_service.sign.return_value = "SIGNED_XDR"
    router_app_context.stellar_service.async_submit.return_value = None

    update = types.Update(
        update_id=4,
        message=types.Message(
            message_id=4,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_council",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Check messages
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("Distribution" in t for t in texts)
    assert any("Work done" in t for t in texts)

    assert router_app_context.stellar_service.build_swap_xdr.called
    assert router_app_context.stellar_service.async_submit.called


@pytest.mark.asyncio
async def test_update_airdrops(mock_telegram, router_app_context):
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.report_service.update_airdrop.return_value = None

    update = types.Update(
        update_id=5,
        message=types.Message(
            message_id=5,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/update_airdrops",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.report_service.update_airdrop.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("Обновление завершено" in t for t in texts)


@pytest.mark.asyncio
async def test_check_bim(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.gspread_service.check_bim.return_value = "Check Result"

    update = types.Update(
        update_id=6,
        message=types.Message(
            message_id=6,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/check_bim",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Check Result" in req["data"]["text"]


@pytest.mark.asyncio
async def test_check_mtlap(mock_telegram, router_app_context):
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.find_public_key.return_value = "GABC..."
    router_app_context.stellar_service.check_mtlap.return_value = "MTLAP Info"

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=7,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/check_mtlap GABC...",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "MTLAP Info" in req["data"]["text"]


# ============================================================================
# Tests for decode command with URL
# ============================================================================


@pytest.mark.asyncio
async def test_decode_command_with_url(mock_telegram, router_app_context):
    """Test decode command when URL contains eurmtl.me"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.check_url_xdr.return_value = ["URL Decoded", "XDR"]

    update = types.Update(
        update_id=8,
        message=types.Message(
            message_id=8,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/decode https://eurmtl.me/sign_tools?xdr=AAAA",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("URL Decoded" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_decode_command_error(mock_telegram, router_app_context):
    """Test decode command handles errors gracefully"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.decode_xdr.side_effect = Exception("Decode error")

    update = types.Update(
        update_id=9,
        message=types.Message(
            message_id=9,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/decode INVALID_XDR",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Reply must carry the real failure reason instead of a generic "cannot parse" text
    assert any(
        "Не смог декодировать: Exception: Decode error" in r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_decode_command_with_url_uses_feature_flag(mock_telegram, router_app_context):
    """full_data must come from FeatureFlagsService (ConfigService has no such method)."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.feature_flags.set_feature(123, "full_data", True, persist=False)
    router_app_context.stellar_service.check_url_xdr.return_value = ["Flagged"]

    update = types.Update(
        update_id=30,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/decode https://eurmtl.me/sign_tools/2f633a09c0ffee",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.check_url_xdr.called
    args, kwargs = router_app_context.stellar_service.check_url_xdr.call_args
    assert args[0] == "https://eurmtl.me/sign_tools/2f633a09c0ffee"
    assert kwargs["full_data"] is True
    requests = mock_telegram.get_requests()
    assert any("Flagged" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_decode_command_without_argument(mock_telegram, router_app_context):
    """Bare /decode must not crash with IndexError, it should ask for an argument."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=31,
        message=types.Message(
            message_id=31,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/decode",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("Не вижу, что декодировать" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")
    assert not router_app_context.stellar_service.check_url_xdr.called
    assert not router_app_context.stellar_service.decode_xdr.called


@pytest.mark.asyncio
async def test_decode_command_reply_with_url(mock_telegram, router_app_context):
    """/decode as a reply to a message with a tool link decodes that link."""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.check_url_xdr.return_value = ["Replied"]

    url_msg = types.Message(
        message_id=32,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
        text="тулза: https://eurmtl.me/sign_tools/2f633a09c0ffee).",
    )

    update = types.Update(
        update_id=32,
        message=types.Message(
            message_id=33,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/decode",
            reply_to_message=url_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    args, _ = router_app_context.stellar_service.check_url_xdr.call_args
    assert args[0] == "https://eurmtl.me/sign_tools/2f633a09c0ffee"
    requests = mock_telegram.get_requests()
    assert any("Replied" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


# ============================================================================
# Tests for balance command
# ============================================================================


@pytest.mark.asyncio
async def test_show_balance_command(mock_telegram, router_app_context):
    """Test /balance command shows cash balance as image"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_cash_balance.return_value = "EURMTL: 100\nMTL: 50"

    update = types.Update(
        update_id=10,
        message=types.Message(
            message_id=10,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/balance",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.get_cash_balance.called
    requests = mock_telegram.get_requests()
    # Balance command sends a photo
    assert any(r["method"] == "sendPhoto" for r in requests)


# ============================================================================
# Tests for do_council command - non-admin rejection
# ============================================================================


@pytest.mark.asyncio
async def test_do_council_non_admin_rejected(mock_telegram, router_app_context):
    """Test /do_council rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=11,
        message=types.Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/do_council",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_do_council_low_balance(mock_telegram, router_app_context):
    """Test /do_council with low EURMTL balance"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"EURMTL": 0, "LABR": 1}  # Low balance

    update = types.Update(
        update_id=12,
        message=types.Message(
            message_id=12,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_council",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        "Low balance" in r["data"]["text"] or "can`t pay" in r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage"
    )


# ============================================================================
# Tests for do_bim command
# ============================================================================


@pytest.mark.asyncio
async def test_do_bim_non_admin_rejected(mock_telegram, router_app_context):
    """Test /do_bim rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=13,
        message=types.Message(
            message_id=13,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/do_bim",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_do_bim_low_balance(mock_telegram, router_app_context):
    """Test /do_bim with low EURMTL balance"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"EURMTL": 5}  # Low balance

    update = types.Update(
        update_id=14,
        message=types.Message(
            message_id=14,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_bim",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        "Low balance" in r["data"]["text"] or "can`t pay BIM" in r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_do_bim_success(mock_telegram, router_app_context):
    """Test /do_bim successful execution"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"EURMTL": 100}
    router_app_context.stellar_service.create_list.return_value = 1
    router_app_context.stellar_service.calc_bim_pays.return_value = [("addr1", 10)]
    router_app_context.stellar_service.gen_xdr.return_value = 0
    router_app_context.stellar_service.send_by_list_id.return_value = 0

    update = types.Update(
        update_id=15,
        message=types.Message(
            message_id=15,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_bim",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.create_list.called
    assert router_app_context.stellar_service.calc_bim_pays.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] in ("sendMessage", "editMessageText")]
    assert any("Work done" in t or "BDM" in t for t in texts)


# ============================================================================
# Tests for do_resend command
# ============================================================================


@pytest.mark.asyncio
async def test_do_resend_non_admin_rejected(mock_telegram, router_app_context):
    """Test /do_resend rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=16,
        message=types.Message(
            message_id=16,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/do_resend 123",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_do_resend_success(mock_telegram, router_app_context):
    """Test /do_resend successful execution"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.send_by_list_id.return_value = 0

    update = types.Update(
        update_id=17,
        message=types.Message(
            message_id=17,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_resend 123",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.send_by_list_id.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] in ("sendMessage", "editMessageText")]
    assert any("Work done" in t or "Resend" in t for t in texts)


# ============================================================================
# Tests for do_all command
# ============================================================================


@pytest.mark.asyncio
async def test_do_all_non_admin_rejected(mock_telegram, router_app_context):
    """Test /do_all rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=18,
        message=types.Message(
            message_id=18,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/do_all",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


# ============================================================================
# Tests for do_div command
# ============================================================================


@pytest.mark.asyncio
async def test_do_div_non_admin_rejected(mock_telegram, router_app_context):
    """Test /do_div rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=19,
        message=types.Message(
            message_id=19,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/do_div",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_do_div_low_balance(mock_telegram, router_app_context):
    """Test /do_div with low EURMTL balance"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"EURMTL": 5}

    update = types.Update(
        update_id=20,
        message=types.Message(
            message_id=20,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_div",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        "Low balance" in r["data"]["text"] or "can`t pay divs" in r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_do_div_success(mock_telegram, router_app_context):
    """Test /do_div successful execution"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"EURMTL": 100}
    router_app_context.stellar_service.create_list.return_value = 1
    router_app_context.stellar_service.calc_divs.return_value = [("addr1", 10)]
    router_app_context.stellar_service.gen_xdr.return_value = 0
    router_app_context.stellar_service.send_by_list_id.return_value = 0

    update = types.Update(
        update_id=21,
        message=types.Message(
            message_id=21,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_div",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.create_list.called
    assert router_app_context.stellar_service.calc_divs.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] in ("sendMessage", "editMessageText")]
    assert any("work done" in t.lower() for t in texts)


# ============================================================================
# Tests for do_sats_div command
# ============================================================================


@pytest.mark.asyncio
async def test_do_sats_div_non_admin_rejected(mock_telegram, router_app_context):
    """Test /do_sats_div rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=22,
        message=types.Message(
            message_id=22,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/do_sats_div",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_do_sats_div_low_balance(mock_telegram, router_app_context):
    """Test /do_sats_div with low SATSMTL balance"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"SATSMTL": 50}

    update = types.Update(
        update_id=23,
        message=types.Message(
            message_id=23,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_sats_div",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        "Low sats balance" in r["data"]["text"] or "can`t pay divs" in r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_do_sats_div_success(mock_telegram, router_app_context):
    """Test /do_sats_div successful execution"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"SATSMTL": 1000}
    router_app_context.stellar_service.create_list.return_value = 1
    router_app_context.stellar_service.calc_sats_divs.return_value = [("addr1", 10)]
    router_app_context.stellar_service.gen_xdr.return_value = 0
    router_app_context.stellar_service.send_by_list_id.return_value = 0

    update = types.Update(
        update_id=24,
        message=types.Message(
            message_id=24,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_sats_div",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.create_list.called
    assert router_app_context.stellar_service.calc_sats_divs.called


# ============================================================================
# Tests for do_usdm_div command
# ============================================================================


@pytest.mark.asyncio
async def test_do_usdm_div_non_admin_rejected(mock_telegram, router_app_context):
    """Test /do_usdm_div rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=25,
        message=types.Message(
            message_id=25,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/do_usdm_div",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_do_usdm_div_low_balance(mock_telegram, router_app_context):
    """Test /do_usdm_div with low USDM balance"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"USDM": 5}

    update = types.Update(
        update_id=26,
        message=types.Message(
            message_id=26,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_usdm_div",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        "Low usdm balance" in r["data"]["text"] or "can`t pay divs" in r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage"
    )


@pytest.mark.asyncio
async def test_do_usdm_div_success(mock_telegram, router_app_context):
    """Test /do_usdm_div successful execution"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"USDM": 100}
    router_app_context.stellar_service.create_list.return_value = 1
    router_app_context.stellar_service.calc_usdm_divs.return_value = [("addr1", 10)]
    router_app_context.stellar_service.gen_xdr.return_value = 0
    router_app_context.stellar_service.send_by_list_id.return_value = 0

    update = types.Update(
        update_id=27,
        message=types.Message(
            message_id=27,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_usdm_div",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.create_list.called
    assert router_app_context.stellar_service.calc_usdm_divs.called


# ============================================================================
# Tests for do_usdm_usdm_div_daily command
# ============================================================================


@pytest.mark.asyncio
async def test_do_usdm_usdm_div_non_admin_rejected(mock_telegram, router_app_context):
    """Test /do_usdm_usdm_div_daily rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=28,
        message=types.Message(
            message_id=28,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/do_usdm_usdm_div_daily",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_do_usdm_usdm_div_low_balance(mock_telegram, router_app_context):
    """Test /do_usdm_usdm_div_daily with low USDM balance"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"USDM": 50}

    update = types.Update(
        update_id=29,
        message=types.Message(
            message_id=29,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_usdm_usdm_div_daily",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any(
        "Low usdm balance" in r["data"]["text"] or "can`t pay divs" in r["data"]["text"]
        for r in requests
        if r["method"] == "sendMessage"
    )


# ============================================================================
# Tests for do_usdm_usdm_div_test command
# ============================================================================


@pytest.mark.asyncio
async def test_do_usdm_usdm_div_test_wrong_chat(mock_telegram, router_app_context):
    """Test /do_usdm_usdm_div_test rejects commands from wrong chat"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=30,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/do_usdm_usdm_div_test",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("Wrong chat" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_do_usdm_usdm_div_test_correct_chat(mock_telegram, router_app_context):
    """Test /do_usdm_usdm_div_test in correct chat"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.calc_usdm_usdm_divs.return_value = [["GCLQ...", 1000.0, 5.97, 5.97, 0]]

    update = types.Update(
        update_id=31,
        message=types.Message(
            message_id=31,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.USDMMGroup, type="supergroup", title="USDM Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/do_usdm_usdm_div_test 1000",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.calc_usdm_usdm_divs.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("current balance" in t or "pay from" in t for t in texts)


# ============================================================================
# Tests for get_vote_fund_xdr command
# ============================================================================


@pytest.mark.asyncio
async def test_get_vote_fund_xdr_with_arg(mock_telegram, router_app_context):
    """Test /get_vote_fund_xdr with address argument"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_new_vote_all_mtl.return_value = ["vote_xdr_123"]

    update = types.Update(
        update_id=32,
        message=types.Message(
            message_id=32,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_vote_fund_xdr GABC...",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.get_new_vote_all_mtl.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("vote_xdr" in t for t in texts)


@pytest.mark.asyncio
async def test_get_vote_fund_xdr_no_arg(mock_telegram, router_app_context):
    """Test /get_vote_fund_xdr without argument"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_new_vote_all_mtl.return_value = ["vote_xdr_for_fund"]

    update = types.Update(
        update_id=33,
        message=types.Message(
            message_id=33,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_vote_fund_xdr",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("Делаю транзакции" in t or "FUND" in t or "vote_xdr" in t for t in texts)


# ============================================================================
# Tests for get_btcmtl_xdr command
# ============================================================================


@pytest.mark.asyncio
async def test_get_btcmtl_xdr_with_args(mock_telegram, router_app_context):
    """Test /get_btcmtl_xdr with sum and address"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_btcmtl_xdr.return_value = "btcmtl_xdr_123"
    router_app_context.stellar_service.decode_xdr.return_value = ["Decoded BTCMTL XDR"]

    update = types.Update(
        update_id=34,
        message=types.Message(
            message_id=34,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_btcmtl_xdr 0.001 GABC...",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.get_btcmtl_xdr.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("btcmtl_xdr" in t or "Decoded" in t for t in texts)


@pytest.mark.asyncio
async def test_get_btcmtl_xdr_no_args(mock_telegram, router_app_context):
    """Test /get_btcmtl_xdr without arguments shows usage"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=35,
        message=types.Message(
            message_id=35,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_btcmtl_xdr",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("use" in t.lower() or "0.001" in t for t in texts)


# ============================================================================
# Tests for get_damircoin_xdr command
# ============================================================================


@pytest.mark.asyncio
async def test_get_damircoin_xdr_with_args(mock_telegram, router_app_context):
    """Test /get_damircoin_xdr with sum"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_damircoin_xdr.return_value = "damircoin_xdr_123"
    router_app_context.stellar_service.decode_xdr.return_value = ["Decoded DamirCoin XDR"]

    update = types.Update(
        update_id=36,
        message=types.Message(
            message_id=36,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_damircoin_xdr 123",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.get_damircoin_xdr.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("damircoin_xdr" in t or "Decoded" in t for t in texts)


@pytest.mark.asyncio
async def test_get_damircoin_xdr_no_args(mock_telegram, router_app_context):
    """Test /get_damircoin_xdr without arguments shows usage"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=37,
        message=types.Message(
            message_id=37,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_damircoin_xdr",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("use" in t.lower() or "123" in t for t in texts)


# ============================================================================
# Tests for get_agora_xdr command
# ============================================================================


@pytest.mark.asyncio
async def test_get_agora_xdr(mock_telegram, router_app_context):
    """Test /get_agora_xdr command"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_agora_xdr.return_value = "agora_xdr_123"
    router_app_context.stellar_service.decode_xdr.return_value = ["Decoded Agora XDR"]

    update = types.Update(
        update_id=38,
        message=types.Message(
            message_id=38,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_agora_xdr",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.get_agora_xdr.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("agora_xdr" in t or "Decoded" in t for t in texts)


# ============================================================================
# Tests for get_chicago_xdr command
# ============================================================================


@pytest.mark.asyncio
async def test_get_chicago_xdr(mock_telegram, router_app_context):
    """Test /get_chicago_xdr command"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_chicago_xdr.return_value = ["Chicago Info", "Details", "chicago_xdr"]
    router_app_context.stellar_service.decode_xdr.return_value = ["Decoded Chicago XDR"]

    update = types.Update(
        update_id=39,
        message=types.Message(
            message_id=39,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_chicago_xdr",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.get_chicago_xdr.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("Chicago" in t or "Decoded" in t for t in texts)


# ============================================================================
# Tests for get_toc_xdr command
# ============================================================================


@pytest.mark.asyncio
async def test_get_toc_xdr_with_args(mock_telegram, router_app_context):
    """Test /get_toc_xdr with sum"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_toc_xdr.return_value = "toc_xdr_123"
    router_app_context.stellar_service.decode_xdr.return_value = ["Decoded TOC XDR"]

    update = types.Update(
        update_id=40,
        message=types.Message(
            message_id=40,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_toc_xdr 123",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.get_toc_xdr.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("toc_xdr" in t or "Decoded" in t for t in texts)


@pytest.mark.asyncio
async def test_get_toc_xdr_no_args(mock_telegram, router_app_context):
    """Test /get_toc_xdr without arguments shows usage"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=41,
        message=types.Message(
            message_id=41,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_toc_xdr",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("use" in t.lower() or "123" in t for t in texts)


# ============================================================================
# Tests for update_airdrops command - non-admin
# ============================================================================


@pytest.mark.asyncio
async def test_update_airdrops_non_admin_rejected(mock_telegram, router_app_context):
    """Test /update_airdrops rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=42,
        message=types.Message(
            message_id=42,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/update_airdrops",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


# ============================================================================
# Tests for update_fest command
# ============================================================================


@pytest.mark.asyncio
async def test_update_fest(mock_telegram, router_app_context):
    """Test /update_fest command"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.report_service.update_fest.return_value = None

    update = types.Update(
        update_id=43,
        message=types.Message(
            message_id=43,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/update_fest",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.report_service.update_fest.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("Обновление завершено" in t or "обновление" in t.lower() for t in texts)


# ============================================================================
# Tests for show_data command
# ============================================================================


@pytest.mark.asyncio
async def test_show_data_with_address(mock_telegram, router_app_context):
    """Test /show_data with public key"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.show_data.return_value = ["Data field 1", "Data field 2"]

    update = types.Update(
        update_id=44,
        message=types.Message(
            message_id=44,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/show_data GABC...",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.show_data.called
    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("Data field" in t for t in texts)


@pytest.mark.asyncio
async def test_show_data_not_found(mock_telegram, router_app_context):
    """Test /show_data when data not found"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.show_data.return_value = []

    update = types.Update(
        update_id=45,
        message=types.Message(
            message_id=45,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/show_data GABC...",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("not found" in t.lower() for t in texts)


@pytest.mark.asyncio
async def test_show_data_no_args(mock_telegram, router_app_context):
    """Test /show_data without arguments shows usage"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=46,
        message=types.Message(
            message_id=46,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/show_data",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("Wrong format" in t or "public_key" in t for t in texts)


# ============================================================================
# Tests for check_bim command - admin with username arg
# ============================================================================


@pytest.mark.asyncio
async def test_check_bim_with_username_admin(mock_telegram, router_app_context):
    """Test /check_bim @username requires admin"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.gspread_service.check_bim.return_value = "BIM info for user"

    update = types.Update(
        update_id=47,
        message=types.Message(
            message_id=47,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/check_bim @someuser",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.gspread_service.check_bim.called
    args, kwargs = router_app_context.gspread_service.check_bim.call_args
    assert kwargs.get("user_id_or_name") == "someuser"


@pytest.mark.asyncio
async def test_check_bim_with_username_non_admin_rejected(mock_telegram, router_app_context):
    """Test /check_bim @username rejects non-admin"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=48,
        message=types.Message(
            message_id=48,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/check_bim @someuser",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


# ============================================================================
# Tests for check_mtlap command - edge cases
# ============================================================================


@pytest.mark.asyncio
async def test_check_mtlap_non_admin_rejected(mock_telegram, router_app_context):
    """Test /check_mtlap rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=49,
        message=types.Message(
            message_id=49,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/check_mtlap GABC...",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_check_mtlap_no_key_found(mock_telegram, router_app_context):
    """Test /check_mtlap when public key not found in message"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.find_public_key.return_value = None

    update = types.Update(
        update_id=50,
        message=types.Message(
            message_id=50,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/check_mtlap",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("Wrong format" in t for t in texts)


# ============================================================================
# Tests for update_bim1 command
# ============================================================================


@pytest.mark.asyncio
async def test_update_bim1_non_admin_rejected(mock_telegram, router_app_context):
    """Test /update_bim1 rejects non-admin users"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    update = types.Update(
        update_id=51,
        message=types.Message(
            message_id=51,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="notadmin"),
            text="/update_bim1",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert any("not my admin" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


# ============================================================================
# Tests for do_usdm_usdm_div_daily success case
# ============================================================================


@pytest.mark.asyncio
async def test_do_usdm_usdm_div_daily_success(mock_telegram, router_app_context):
    """Test /do_usdm_usdm_div_daily successful execution"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"USDM": 500}
    router_app_context.stellar_service.create_list.return_value = 1
    router_app_context.stellar_service.calc_usdm_daily.return_value = [("addr1", 10)]
    router_app_context.stellar_service.gen_xdr.return_value = 0
    router_app_context.stellar_service.send_by_list_id.return_value = 0

    update = types.Update(
        update_id=52,
        message=types.Message(
            message_id=52,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_usdm_usdm_div_daily",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.stellar_service.create_list.called
    assert router_app_context.stellar_service.calc_usdm_daily.called


# ============================================================================
# Tests for large XDR handling (file response)
# ============================================================================


@pytest.mark.asyncio
async def test_get_vote_fund_xdr_large_xdr(mock_telegram, router_app_context):
    """Test /get_vote_fund_xdr sends file for large XDR"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    # Create a large XDR string (> 4000 chars)
    large_xdr = "A" * 5000
    router_app_context.stellar_service.get_new_vote_all_mtl.return_value = [large_xdr]

    update = types.Update(
        update_id=53,
        message=types.Message(
            message_id=53,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_vote_fund_xdr GABC...",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Should send document for large XDR
    requests = mock_telegram.get_requests()
    assert any(r["method"] == "sendDocument" for r in requests)


# ============================================================================
# Tests for do_all success case
# ============================================================================


@pytest.mark.asyncio
async def test_do_all_success(mock_telegram, router_app_context):
    """Test /do_all calls div, sats_div, show_bim, and do_bim"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    # Setup all required returns for the combined command
    router_app_context.stellar_service.get_balances.return_value = {"EURMTL": 100, "SATSMTL": 1000}
    router_app_context.stellar_service.create_list.return_value = 1
    router_app_context.stellar_service.calc_divs.return_value = [("addr1", 10)]
    router_app_context.stellar_service.calc_sats_divs.return_value = [("addr1", 10)]
    router_app_context.stellar_service.calc_bim_pays.return_value = [("addr1", 10)]
    router_app_context.stellar_service.show_bim.return_value = "BIM info"
    router_app_context.stellar_service.gen_xdr.return_value = 0
    router_app_context.stellar_service.send_by_list_id.return_value = 0

    update = types.Update(
        update_id=54,
        message=types.Message(
            message_id=54,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_all",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Should have called multiple services
    assert router_app_context.stellar_service.calc_divs.called or router_app_context.stellar_service.get_balances.called


# ============================================================================
# Tests for chicago XDR with large response
# ============================================================================


@pytest.mark.asyncio
async def test_get_chicago_xdr_large(mock_telegram, router_app_context):
    """Test /get_chicago_xdr handles large XDR"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    large_xdr = "A" * 5000
    router_app_context.stellar_service.get_chicago_xdr.return_value = ["Info", large_xdr]
    router_app_context.stellar_service.decode_xdr.return_value = ["Decoded"]

    update = types.Update(
        update_id=55,
        message=types.Message(
            message_id=55,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_chicago_xdr",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    # Should contain link to eurmtl.me for large XDR
    assert any("eurmtl.me" in t or "Info" in t or "Decoded" in t for t in texts)


# ============================================================================
# Tests for update_bim1 success case
# ============================================================================


@pytest.mark.asyncio
async def test_update_bim1_success(mock_telegram, router_app_context):
    """Test /update_bim1 successful execution"""
    from tests.fakes import FakeGSpreadWorksheet, FakeGSpreadSpreadsheet

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    # Setup fake worksheet with test data
    worksheet = FakeGSpreadWorksheet(
        data=[
            ["Header1", "Header2", "Header3", "TelegramID"],
            ["Row1", "Data", "More", ""],
            ["Row2", "Data", "More", "12345"],
            ["Row3", "Data", "More", "67890"],
        ]
    )
    spreadsheet = FakeGSpreadSpreadsheet({"List": worksheet})
    router_app_context.gspread_service._agc_client.set_spreadsheet("MTL_BIM_register", spreadsheet)

    update = types.Update(
        update_id=56,
        message=types.Message(
            message_id=56,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/update_bim1",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("Done" in t for t in texts)


# ============================================================================
# Tests for check_mtlap with reply message
# ============================================================================


@pytest.mark.asyncio
async def test_check_mtlap_with_reply(mock_telegram, router_app_context):
    """Test /check_mtlap extracts key from reply message"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    # First call returns None (no key in main message), second returns key from reply
    call_count = [0]

    def find_key_side_effect(text):
        call_count[0] += 1
        if call_count[0] == 1:
            return None
        return "GFOUND..."

    router_app_context.stellar_service.find_public_key.side_effect = find_key_side_effect
    router_app_context.stellar_service.check_mtlap.return_value = "MTLAP from reply"

    reply_message = types.Message(
        message_id=100,
        date=datetime.datetime.now(),
        chat=types.Chat(id=123, type="supergroup", title="Group"),
        from_user=types.User(id=888, is_bot=False, first_name="Other"),
        text="Here is a key: GFOUND...",
    )

    update = types.Update(
        update_id=57,
        message=types.Message(
            message_id=57,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/check_mtlap",
            reply_to_message=reply_message,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    assert any("MTLAP from reply" in t for t in texts)


# ============================================================================
# Tests for register_handlers function
# ============================================================================


@pytest.mark.asyncio
async def test_register_handlers():
    """Test register_handlers function"""
    from aiogram import Dispatcher
    from routers.stellar import register_handlers

    # Create a mock dispatcher
    dp = Dispatcher()

    # This should not raise an error
    register_handlers(dp, None)

    # Router should be included (use sub_routers property)
    assert stellar_router in dp.sub_routers


# ============================================================================
# Tests for exception handling in transaction sending loops
# ============================================================================


@pytest.mark.asyncio
async def test_do_bim_with_send_error_recovery(mock_telegram, router_app_context):
    """Test /do_bim recovers from send errors"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"EURMTL": 100}
    router_app_context.stellar_service.create_list.return_value = 1
    router_app_context.stellar_service.calc_bim_pays.return_value = [("addr1", 10)]
    router_app_context.stellar_service.gen_xdr.return_value = 0

    # First call raises, second succeeds
    call_count = [0]

    async def send_side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("Network error")
        return 0

    router_app_context.stellar_service.send_by_list_id = type(router_app_context.stellar_service.send_by_list_id)(
        return_value=0, side_effect=send_side_effect
    )

    update = types.Update(
        update_id=59,
        message=types.Message(
            message_id=59,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_bim",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] in ("sendMessage", "editMessageText")]
    # Should show error message and eventually complete
    assert any("error" in t.lower() or "Work done" in t for t in texts)


@pytest.mark.asyncio
async def test_do_div_with_send_error_recovery(mock_telegram, router_app_context):
    """Test /do_div recovers from send errors"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    router_app_context.stellar_service.get_balances.return_value = {"EURMTL": 100}
    router_app_context.stellar_service.create_list.return_value = 1
    router_app_context.stellar_service.calc_divs.return_value = [("addr1", 10)]
    router_app_context.stellar_service.gen_xdr.return_value = 0

    # First call raises, subsequent succeed
    call_count = [0]

    async def send_side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("Network error")
        return 0

    router_app_context.stellar_service.send_by_list_id = type(router_app_context.stellar_service.send_by_list_id)(
        return_value=0, side_effect=send_side_effect
    )

    update = types.Update(
        update_id=60,
        message=types.Message(
            message_id=60,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_div",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] in ("sendMessage", "editMessageText")]
    # Should show error and eventually complete
    assert any("error" in t.lower() or "work done" in t.lower() for t in texts)


@pytest.mark.asyncio
async def test_do_resend_with_send_error_recovery(mock_telegram, router_app_context):
    """Test /do_resend recovers from send errors"""
    router_app_context.admin_service.set_skynet_admins(["@admin"])
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    # First call raises, second succeeds
    call_count = [0]

    async def send_side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("Network error")
        return 0

    router_app_context.stellar_service.send_by_list_id = type(router_app_context.stellar_service.send_by_list_id)(
        return_value=0, side_effect=send_side_effect
    )

    update = types.Update(
        update_id=61,
        message=types.Message(
            message_id=61,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=MTLChats.ITolstov, is_bot=False, first_name="Admin", username="admin"),
            text="/do_resend 123",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] in ("sendMessage", "editMessageText")]
    assert any("error" in t.lower() or "Work done" in t for t in texts)


# ============================================================================
# Tests for short XDR path in get_vote_fund_xdr
# ============================================================================


@pytest.mark.asyncio
async def test_get_vote_fund_xdr_short_xdr_no_arg(mock_telegram, router_app_context):
    """Test /get_vote_fund_xdr with short XDR and no argument uses multi_answer"""
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(stellar_router)

    # Short XDR (< 4000 chars) with no argument
    short_xdr = "A" * 100
    router_app_context.stellar_service.get_new_vote_all_mtl.return_value = [short_xdr]

    update = types.Update(
        update_id=62,
        message=types.Message(
            message_id=62,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/get_vote_fund_xdr",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    texts = [r["data"]["text"] for r in requests if r["method"] == "sendMessage"]
    # Should send via message (not file) for short XDR
    assert any("FUND" in t or short_xdr in t or "Делаю" in t for t in texts)
