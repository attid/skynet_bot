import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from start import on_startup
from other.constants import MTLChats
from tests.conftest import TEST_BOT_TOKEN
from other.config_reader import config


class FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text):
        self.sent_messages.append((chat_id, text))


class FakeAsyncEngine:
    def __init__(self):
        self.disposed = False

    async def dispose(self):
        self.disposed = True


@pytest.mark.asyncio
async def test_startup_sends_message_to_admin(mock_telegram, dp, monkeypatch):
    """
    Verifies that on_startup:
    1. Sets commands (setMyCommands)
    2. Sends a startup message to the admin
    """
    # Setup
    session = AiohttpSession(api=TelegramAPIServer.from_base(mock_telegram.base_url))
    bot = Bot(token=TEST_BOT_TOKEN, session=session)

    # Mock admin ID match
    # Note: start.py uses MTLChats.ITolstov constant for admin notification
    # We should verify that MTLChats.ITolstov matches what we expect or just check the call to that ID.

    monkeypatch.setattr(config, "test_mode", True)

    # Execute
    await on_startup(bot, dp)

    # Verify
    # Expecting: setMyCommands (2 calls: private Scopes, admin Scope) + sendMessage

    cmds_reqs = [r for r in mock_telegram.get_requests() if r["method"] == "setMyCommands"]
    assert len(cmds_reqs) >= 2

    msg_req = next((r for r in mock_telegram.get_requests() if r["method"] == "sendMessage"), None)
    assert msg_req is not None
    assert "Bot started" in msg_req["data"]["text"]
    # MTLChats.ITolstov is hardcoded in start.py
    assert str(msg_req["data"]["chat_id"]) == str(MTLChats.ITolstov)

    await bot.session.close()


@pytest.mark.asyncio
async def test_shutdown_disposes_async_engine(monkeypatch):
    import start

    engine = FakeAsyncEngine()
    monkeypatch.setattr(start, "async_engine", engine)

    await start.on_shutdown(FakeBot())

    assert engine.disposed is True
