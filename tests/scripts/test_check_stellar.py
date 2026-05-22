import pytest

from tests.fakes import FakeAsyncMethod, FakeSession
import scripts.check_stellar as check_stellar


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
async def test_cmd_check_bot_uses_async_session_for_alerts(monkeypatch):
    session = FakeSession()
    pool = make_async_session_pool(session)
    messages = []

    class FakeMessageRepository:
        def __init__(self, repo_session):
            self.session = repo_session

        async def async_add_message(self, chat_id, text, use_alarm=0, update_id=None, button_json=None, topic_id=0):
            messages.append(
                {
                    "session": self.session,
                    "chat_id": chat_id,
                    "text": text,
                    "topic_id": topic_id,
                }
            )

    monkeypatch.setattr(check_stellar, "MessageRepository", FakeMessageRepository)
    monkeypatch.setattr(check_stellar, "get_balances", FakeAsyncMethod(return_value={"XLM": "50"}))
    monkeypatch.setattr(check_stellar, "EXCHANGE_BOTS", [])
    monkeypatch.setattr(check_stellar, "stellar_get_orders_sum", FakeAsyncMethod(return_value=100000))

    await check_stellar.cmd_check_bot(pool)

    assert messages == [
        {
            "session": session,
            "chat_id": check_stellar.MTLChats.SignGroup,
            "text": "Внимание Баланс MyMTLWallet меньше 100 !",
            "topic_id": 0,
        }
    ]
    assert session.committed is True
