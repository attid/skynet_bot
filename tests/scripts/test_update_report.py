import pytest

from tests.fakes import FakeAsyncMethod, FakeSession
import scripts.update_report as update_report


def make_async_session_pool(session):
    class Pool:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    return Pool()


@pytest.mark.asyncio
async def test_lite_report_uses_async_session_pool(monkeypatch):
    session = FakeSession()
    pool = make_async_session_pool(session)

    save_assets = FakeAsyncMethod()
    update_main = FakeAsyncMethod()
    update_top = FakeAsyncMethod()
    update_mmwb = FakeAsyncMethod()
    sleep = FakeAsyncMethod()

    monkeypatch.setattr(update_report, "save_assets", save_assets)
    monkeypatch.setattr(update_report, "update_main_report", update_main)
    monkeypatch.setattr(update_report, "update_top_holders_report", update_top)
    monkeypatch.setattr(update_report, "update_mmwb_report", update_mmwb)
    monkeypatch.setattr(update_report.asyncio, "sleep", sleep)

    await update_report.lite_report(pool)

    update_main.assert_awaited_once_with(session)
    update_top.assert_awaited_once_with(session)
    update_mmwb.assert_awaited_once_with(session)
    assert sleep.call_count == 3
    assert session.committed is True
