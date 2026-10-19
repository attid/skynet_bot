import pytest

from other import web_tools
from other.web_tools import EurmtlXdrError, WebResponse, get_eurmtl_xdr
from tests.fakes import FakeAsyncMethod


@pytest.fixture
def fake_http(monkeypatch):
    """Patch the shared HTTP session manager with a fake get_web_request."""
    fake = FakeAsyncMethod()
    monkeypatch.setattr(web_tools.http_session_manager, "get_web_request", fake)
    return fake


@pytest.mark.asyncio
async def test_get_eurmtl_xdr_returns_xdr(fake_http):
    fake_http.return_value = WebResponse(status=200, data={"xdr": "AAAA"})

    xdr = await get_eurmtl_xdr("https://eurmtl.me/sign_tools/2f633a09c0ffee")

    assert xdr == "AAAA"
    _, kwargs = fake_http.call_args
    assert kwargs["url"] == "https://eurmtl.me/remote/get_xdr/2f633a09c0ffee"


@pytest.mark.asyncio
async def test_get_eurmtl_xdr_without_tool_id_raises(fake_http):
    with pytest.raises(EurmtlXdrError):
        await get_eurmtl_xdr("https://eurmtl.me/sign_tools/")
    assert not fake_http.called


@pytest.mark.asyncio
async def test_get_eurmtl_xdr_inline_xdr_needs_no_request(fake_http):
    xdr = await get_eurmtl_xdr("https://eurmtl.me/sign_tools?xdr=AAAA")

    assert xdr == "AAAA"
    assert not fake_http.called


@pytest.mark.asyncio
async def test_get_eurmtl_xdr_missing_xdr_raises(fake_http):
    fake_http.return_value = WebResponse(status=200, data={"error": "not found"})

    with pytest.raises(EurmtlXdrError, match="не вернула xdr"):
        await get_eurmtl_xdr("https://eurmtl.me/sign_tools/2f633a09c0ffee")


@pytest.mark.asyncio
async def test_get_eurmtl_xdr_request_failure_raises(fake_http):
    fake_http.side_effect = RuntimeError("no network")

    with pytest.raises(EurmtlXdrError, match="no network"):
        await get_eurmtl_xdr("https://eurmtl.me/sign_tools/2f633a09c0ffee")
