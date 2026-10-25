import pytest
from aiohttp import ClientTimeout, web
from loguru import logger
from pydantic import SecretStr

from other import spam_cheker

CAS_API_KEY = "test-combot-key"  # noqa: S105 - test fixture value


class CasMockState:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.body = {"ok": False, "description": "Record not found."}
        self.delay = 0.0


@pytest.fixture
async def mock_cas():
    """Local stand-in for api.cas.chat (no real network calls)."""
    state = CasMockState()

    async def handle_check(request):
        state.requests.append(
            {
                "user_id": request.query.get("user_id"),
                "authorization": request.headers.get("Authorization"),
            }
        )
        if state.delay:
            import asyncio

            await asyncio.sleep(state.delay)
        return web.json_response(state.body, status=state.status)

    app = web.Application()
    app.router.add_get("/check", handle_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][0], runner.addresses[0][1]
    state.url = f"http://{host}:{port}/check"

    yield state

    await runner.cleanup()


@pytest.fixture(autouse=True)
def reset_warn_dedup():
    spam_cheker._warned_once.clear()
    yield
    spam_cheker._warned_once.clear()


@pytest.fixture
def warnings():
    records = []

    def sink(message):
        records.append(message.record["message"])

    handler_id = logger.add(sink, level="WARNING")
    yield records
    logger.remove(handler_id)


@pytest.fixture
def cas_settings(monkeypatch, mock_cas):
    monkeypatch.setattr(spam_cheker.config, "cas_api_url", mock_cas.url, raising=False)
    monkeypatch.setattr(spam_cheker.config, "cas_api_key", SecretStr(CAS_API_KEY), raising=False)
    return mock_cas


@pytest.mark.asyncio
async def test_combo_check_spammer_returns_true_for_banned_user(cas_settings):
    cas_settings.body = {"ok": True, "result": {"reasons": [7], "offenses": 1}}

    assert await spam_cheker.combo_check_spammer(5021561899) is True
    assert cas_settings.requests == [{"user_id": "5021561899", "authorization": f"Bearer {CAS_API_KEY}"}]


@pytest.mark.asyncio
async def test_combo_check_spammer_returns_false_for_unknown_user(cas_settings):
    assert await spam_cheker.combo_check_spammer(84131737) is False
    assert len(cas_settings.requests) == 1


@pytest.mark.asyncio
async def test_combo_check_spammer_sends_no_request_without_api_key(monkeypatch, cas_settings, warnings):
    monkeypatch.setattr(spam_cheker.config, "cas_api_key", None, raising=False)

    assert await spam_cheker.combo_check_spammer(84131737) is False
    assert cas_settings.requests == []
    assert any("CAS_API_KEY is not configured" in message for message in warnings)


@pytest.mark.asyncio
async def test_combo_check_spammer_handles_unauthorized_once(cas_settings, warnings):
    cas_settings.status = 401
    cas_settings.body = {"ok": False, "error_code": 401, "description": "Invalid API key"}

    assert await spam_cheker.combo_check_spammer(84131737) is False
    assert await spam_cheker.combo_check_spammer(84131738) is False

    auth_warnings = [message for message in warnings if "verify CAS_API_KEY" in message]
    assert len(auth_warnings) == 1
    assert not [message for message in warnings if "status code" in message]


@pytest.mark.asyncio
async def test_combo_check_spammer_warns_once_per_status_code(cas_settings, warnings):
    cas_settings.status = 429

    assert await spam_cheker.combo_check_spammer(84131737) is False
    assert await spam_cheker.combo_check_spammer(84131738) is False

    assert len([message for message in warnings if "status code: 429" in message]) == 1


@pytest.mark.asyncio
async def test_combo_check_spammer_handles_timeout(cas_settings, monkeypatch, warnings):
    monkeypatch.setattr(spam_cheker, "CAS_TIMEOUT", ClientTimeout(total=0.05), raising=True)
    cas_settings.delay = 0.3

    assert await spam_cheker.combo_check_spammer(84131737) is False
    assert any("timed out" in message for message in warnings)


@pytest.mark.asyncio
async def test_combo_check_spammer_handles_network_error(monkeypatch, mock_cas, warnings):
    monkeypatch.setattr(spam_cheker.config, "cas_api_url", "http://127.0.0.1:1/check", raising=False)
    monkeypatch.setattr(spam_cheker.config, "cas_api_key", SecretStr(CAS_API_KEY), raising=False)

    assert await spam_cheker.combo_check_spammer(84131737) is False
    assert any("network error" in message for message in warnings)
