import pytest

from tests.fakes import FakeAsyncMethod
from other.stellar import utils
import services.app_context as app_context_module


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append({"chat_id": chat_id, "text": text})


class FakeUser:
    username = "caller"


class FakeReplyMessage:
    def get_url(self):
        return "https://t.me/c/1/2"


class FakeMessage:
    from_user = FakeUser()
    reply_to_message = FakeReplyMessage()

    def __init__(self):
        self.replies = []

    async def reply(self, text):
        self.replies.append(text)


@pytest.mark.asyncio
async def test_send_by_list_uses_async_db_service_when_session_is_absent(monkeypatch):
    bot = FakeBot()
    message = FakeMessage()
    get_user_id = FakeAsyncMethod(return_value=123)

    class FakeDbService:
        async def get_user_id(self, username):
            return await get_user_id(username)

    class FakeAppContext:
        db_service = FakeDbService()

    monkeypatch.setattr(app_context_module, "app_context", FakeAppContext())

    await utils.send_by_list(bot, ["@target"], message)

    get_user_id.assert_awaited_once_with("@target")
    assert bot.sent == [{"chat_id": 123, "text": "@caller call you here https://t.me/c/1/2"}]
    assert message.replies == ["was send to @target \n can`t send to "]
