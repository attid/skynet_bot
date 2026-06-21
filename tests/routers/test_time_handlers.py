import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from other.constants import MTLChats
from other.grist_tools import MTLGrist
import routers.time_handlers as time_handlers
from tests.fakes import FakeAsyncMethod, FakeSession


def make_session_pool(session):
    class Pool:
        def __call__(self):
            return self

        def __enter__(self):
            return session

        def __exit__(self, exc_type, exc, tb):
            return False

    return Pool()


def make_async_session_pool(session):
    class Pool:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    return Pool()


def test_scheduler_jobs_runs_check_bot_monday_at_16(router_app_context):
    class FakeScheduler:
        def __init__(self):
            self.jobs = []

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append((func, trigger, kwargs))

    scheduler = FakeScheduler()

    time_handlers.scheduler_jobs(
        scheduler,
        router_app_context.bot,
        make_async_session_pool(FakeSession()),
        db_service=router_app_context.db_service,
        async_session_pool=make_async_session_pool(FakeSession()),
    )

    check_bot_jobs = [job for job in scheduler.jobs if job[0] is time_handlers.cmd_check_bot]

    assert len(check_bot_jobs) == 1
    _, trigger, kwargs = check_bot_jobs[0]
    assert trigger == "cron"
    assert kwargs["day_of_week"] == "mon"
    assert kwargs["hour"] == 16
    assert kwargs["minute"] == 0


@pytest.mark.asyncio
async def test_cmd_send_message_1m(mock_telegram, router_app_context, monkeypatch):
    bot = router_app_context.bot

    mock_session = FakeSession()
    mock_pool = make_async_session_pool(mock_session)

    class Record:
        update_id = 0
        text = "Scheduled msg"
        user_id = 123
        use_alarm = 1
        was_send = 0
        topic_id = 0
        button_json = "{}"

    mock_record = Record()

    class FakeMessageRepository:
        def __init__(self, session):
            self.session = session

        async def async_load_new_messages(self):
            return [mock_record]

    monkeypatch.setattr(time_handlers, "MessageRepository", FakeMessageRepository)

    await time_handlers.cmd_send_message_1m(bot, mock_pool)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage" and r["data"]["text"] == "Scheduled msg"), None)
    assert req is not None
    assert str(req["data"]["chat_id"]) == "123"
    assert mock_record.was_send == 1
    assert mock_session.committed is True


@pytest.mark.asyncio
async def test_cmd_send_message_1m_handles_forbidden_as_delivery_failure(router_app_context, monkeypatch):
    bot = router_app_context.bot

    mock_session = FakeSession()
    mock_pool = make_async_session_pool(mock_session)

    class Record:
        id = 42
        update_id = 0
        text = "Scheduled msg"
        user_id = -100123
        use_alarm = 1
        was_send = 0
        topic_id = 0
        button_json = "{}"

    mock_record = Record()

    class FakeMessageRepository:
        def __init__(self, session):
            self.session = session

        async def async_load_new_messages(self):
            return [mock_record]

    async def forbidden_send_message(*args, **kwargs):
        raise TelegramForbiddenError(
            SendMessage(chat_id=mock_record.user_id, text=mock_record.text),
            "Forbidden: bot was kicked from the supergroup chat",
        )

    errors = []
    warnings = []

    monkeypatch.setattr(time_handlers, "MessageRepository", FakeMessageRepository)
    monkeypatch.setattr(bot, "send_message", forbidden_send_message)
    monkeypatch.setattr(time_handlers.logger, "error", errors.append)
    monkeypatch.setattr(time_handlers.logger, "warning", warnings.append)

    await time_handlers.cmd_send_message_1m(bot, mock_pool)

    assert mock_record.was_send == 2
    assert mock_session.committed is True
    assert errors == []
    assert len(warnings) == 1
    assert "message_id=42" in warnings[0]
    assert "chat_id=-100123" in warnings[0]


@pytest.mark.asyncio
async def test_time_clear(mock_telegram, router_app_context, mock_grist, grist_server_config, monkeypatch):
    bot = router_app_context.bot

    # Redirect the Grist table's base_url at the local mock Grist server so the
    # real grist_manager HTTP client hits mock_grist instead of the live API.
    monkeypatch.setattr(
        MTLGrist.CONFIG_auto_clean,
        "base_url",
        f"{grist_server_config['url']}/api/docs",
    )

    # Seed mock_grist with a single enabled auto-clean row.
    mock_grist.add_records(
        MTLGrist.CONFIG_auto_clean.table_name,
        [{"id": 1, "fields": {"chat_id": 12345, "enabled": True}}],
    )

    mock_remove = FakeAsyncMethod(return_value=5)
    mock_sleep = FakeAsyncMethod()

    monkeypatch.setattr(time_handlers, "remove_deleted_users", mock_remove)
    monkeypatch.setattr(time_handlers.asyncio, "sleep", mock_sleep)

    await time_handlers.time_clear(bot)

    # Assert the mock Grist server was queried for the Auto_clean table.
    assert any(
        r["table"] == MTLGrist.CONFIG_auto_clean.table_name and r["method"] == "GET" for r in mock_grist.requests
    )
    mock_remove.assert_awaited_once_with(12345)
    mock_sleep.assert_awaited_once()

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage" and "Finished removing" in r["data"]["text"]), None)
    assert req is not None
    assert str(req["data"]["chat_id"]) == str(MTLChats.SpamGroup)


@pytest.mark.asyncio
async def test_time_usdm_daily_sends_summary(mock_telegram, router_app_context, monkeypatch):
    bot = router_app_context.bot

    mock_session = FakeSession()
    mock_pool = make_async_session_pool(mock_session)

    calc_result = [("addr1", "x", 10.0), ("addr2", "x", 30.0)]

    mock_create_list = FakeAsyncMethod(return_value=452)
    mock_calc_daily = FakeAsyncMethod(return_value=calc_result)
    mock_gen_xdr = FakeAsyncMethod(return_value=0)
    mock_send_by_list = FakeAsyncMethod(return_value=0)
    mock_get_balances = FakeAsyncMethod(return_value={"USDM": "626.57"})

    monkeypatch.setattr(router_app_context.stellar_service, "create_list", mock_create_list)
    monkeypatch.setattr(router_app_context.stellar_service, "calc_usdm_daily", mock_calc_daily)
    monkeypatch.setattr(router_app_context.stellar_service, "gen_xdr", mock_gen_xdr)
    monkeypatch.setattr(router_app_context.stellar_service, "send_by_list_id", mock_send_by_list)
    monkeypatch.setattr(router_app_context.stellar_service, "get_balances", mock_get_balances)

    await time_handlers.time_usdm_daily(mock_pool, bot)

    mock_send_by_list.assert_awaited_once()
    requests = mock_telegram.get_requests()
    msg_req = next(
        (r for r in requests if r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(MTLChats.USDMMGroup)),
        None,
    )
    assert msg_req is not None
    text = msg_req["data"]["text"]
    assert "Start div pays №452." in text
    assert "Found 2 addresses." in text
    assert "Total payouts sum: 40.00." in text
    assert "Осталось 626.57 USDM" in text
    assert "All work done." in text


@pytest.mark.asyncio
async def test_time_usdm_daily_retries_send_on_error(mock_telegram, router_app_context, monkeypatch):
    bot = router_app_context.bot

    mock_session = FakeSession()
    mock_pool = make_async_session_pool(mock_session)

    calc_result = [("addr1", "x", 1.0)]
    send_results = [Exception("fail"), Exception("fail"), 0]

    async def send_side_effect(*args, **kwargs):
        result = send_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    mock_create_list = FakeAsyncMethod(return_value=1)
    mock_calc_daily = FakeAsyncMethod(return_value=calc_result)
    mock_gen_xdr = FakeAsyncMethod(return_value=0)
    mock_send_by_list = FakeAsyncMethod(side_effect=send_side_effect)
    mock_get_balances = FakeAsyncMethod(return_value={"USDM": "1.00"})
    mock_sleep = FakeAsyncMethod()

    monkeypatch.setattr(router_app_context.stellar_service, "create_list", mock_create_list)
    monkeypatch.setattr(router_app_context.stellar_service, "calc_usdm_daily", mock_calc_daily)
    monkeypatch.setattr(router_app_context.stellar_service, "gen_xdr", mock_gen_xdr)
    monkeypatch.setattr(router_app_context.stellar_service, "send_by_list_id", mock_send_by_list)
    monkeypatch.setattr(router_app_context.stellar_service, "get_balances", mock_get_balances)
    monkeypatch.setattr(time_handlers.asyncio, "sleep", mock_sleep)

    await time_handlers.time_usdm_daily(mock_pool, bot)

    assert mock_send_by_list.call_count == 3
    assert mock_sleep.call_count == 2
    requests = mock_telegram.get_requests()
    assert any(r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(MTLChats.USDMMGroup) for r in requests)


@pytest.mark.asyncio
async def test_time_usdm_daily_gives_up_after_many_errors(mock_telegram, router_app_context, monkeypatch):
    bot = router_app_context.bot

    mock_session = FakeSession()
    mock_pool = make_async_session_pool(mock_session)

    calc_result = [("addr1", "x", 1.0)]
    send_results = [Exception("fail")] * 20

    async def send_side_effect(*args, **kwargs):
        result = send_results.pop(0)
        raise result

    mock_create_list = FakeAsyncMethod(return_value=1)
    mock_calc_daily = FakeAsyncMethod(return_value=calc_result)
    mock_gen_xdr = FakeAsyncMethod(return_value=0)
    mock_send_by_list = FakeAsyncMethod(side_effect=send_side_effect)
    mock_get_balances = FakeAsyncMethod(return_value={"USDM": "1.00"})
    mock_sleep = FakeAsyncMethod()

    monkeypatch.setattr(router_app_context.stellar_service, "create_list", mock_create_list)
    monkeypatch.setattr(router_app_context.stellar_service, "calc_usdm_daily", mock_calc_daily)
    monkeypatch.setattr(router_app_context.stellar_service, "gen_xdr", mock_gen_xdr)
    monkeypatch.setattr(router_app_context.stellar_service, "send_by_list_id", mock_send_by_list)
    monkeypatch.setattr(router_app_context.stellar_service, "get_balances", mock_get_balances)
    monkeypatch.setattr(time_handlers.asyncio, "sleep", mock_sleep)

    await time_handlers.time_usdm_daily(mock_pool, bot)

    assert mock_send_by_list.call_count == 20
    assert mock_sleep.call_count == 20
    requests = mock_telegram.get_requests()
    assert not any(
        r["method"] == "sendMessage" and str(r["data"]["chat_id"]) == str(MTLChats.USDMMGroup) for r in requests
    )


@pytest.mark.asyncio
async def test_cmd_send_message_test(mock_telegram, router_app_context, monkeypatch):
    """Test that cmd_send_message_test sends a message to TestGroup with time and random number."""
    bot = router_app_context.bot

    # Mock random.randint to return a predictable value
    monkeypatch.setattr(time_handlers.random, "randint", lambda a, b: 5)

    await time_handlers.cmd_send_message_test(bot)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert str(req["data"]["chat_id"]) == str(MTLChats.TestGroup)
    # Message should contain "rand=5" and "job.next_run_time"
    assert "rand=5" in req["data"]["text"]
    assert "job.next_run_time" in req["data"]["text"]


@pytest.mark.asyncio
async def test_cmd_send_message_start_month(mock_telegram, router_app_context):
    """Test that cmd_send_message_start_month sends reminder to SignGroup."""
    bot = router_app_context.bot

    await time_handlers.cmd_send_message_start_month(bot)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert str(req["data"]["chat_id"]) == str(MTLChats.SignGroup)
    assert str(req["data"]["message_thread_id"]) == "59558"
    assert "кучицы" in req["data"]["text"]
    assert "/all" in req["data"]["text"]


@pytest.mark.asyncio
async def test_time_check_ledger(mock_telegram, router_app_context):
    """Test that time_check_ledger returns early (currently disabled with TODO comment)."""
    bot = router_app_context.bot

    mock_session = FakeSession()
    mock_pool = make_session_pool(mock_session)

    # Should return None immediately due to early return
    result = await time_handlers.time_check_ledger(bot, mock_pool)

    assert result is None
    # No messages should be sent since the function returns early
    requests = mock_telegram.get_requests()
    assert len(requests) == 0
