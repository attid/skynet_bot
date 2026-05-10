import pytest
from aiogram import types

from other import antispam_logic
from tests.fakes import FakeAsyncMethod


@pytest.mark.asyncio
async def test_set_vote_sends_keyboard_when_enabled(monkeypatch, router_app_context):
    monkeypatch.setattr(antispam_logic, "app_context", router_app_context, raising=True)

    chat_id = 123
    router_app_context.voting_service.enable_first_vote(chat_id)

    message = type("Msg", (), {})()
    message.sender_chat = None
    message.from_user = types.User(id=100, is_bot=False, first_name="Test")
    message.chat = types.Chat(id=chat_id, type="supergroup")
    message.message_id = 10
    message.reply = FakeAsyncMethod(return_value=None)

    await antispam_logic.set_vote(message)

    message.reply.assert_awaited_once()
    args, kwargs = message.reply.call_args
    text = kwargs.get("text") if kwargs else (args[0] if args else "")
    assert "detect spam messages" in text

    reply_markup = kwargs.get("reply_markup")
    assert reply_markup is not None
    assert len(reply_markup.inline_keyboard[0]) == 2


@pytest.mark.asyncio
async def test_set_vote_does_nothing_when_disabled(monkeypatch, router_app_context):
    monkeypatch.setattr(antispam_logic, "app_context", router_app_context, raising=True)

    message = type("Msg", (), {})()
    message.sender_chat = None
    message.from_user = types.User(id=101, is_bot=False, first_name="Test")
    message.chat = types.Chat(id=999, type="supergroup")
    message.message_id = 11
    message.reply = FakeAsyncMethod(return_value=None)

    await antispam_logic.set_vote(message)

    message.reply.assert_not_called()


@pytest.mark.asyncio
async def test_set_vote_uses_sender_chat_when_from_user_missing(monkeypatch, router_app_context):
    monkeypatch.setattr(antispam_logic, "app_context", router_app_context, raising=True)

    chat_id = 123
    sender_chat_id = -100777
    router_app_context.voting_service.enable_first_vote(chat_id)

    message = type("Msg", (), {})()
    message.sender_chat = types.Chat(id=sender_chat_id, type="channel", title="Channel")
    message.from_user = None
    message.chat = types.Chat(id=chat_id, type="supergroup")
    message.message_id = 12
    message.reply = FakeAsyncMethod(return_value=None)

    await antispam_logic.set_vote(message)

    message.reply.assert_awaited_once()
    _, kwargs = message.reply.call_args
    keyboard = kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data == f"first:{sender_chat_id}:12:1"


@pytest.mark.asyncio
async def test_check_spam_ignores_message_without_identifiable_sender(monkeypatch, router_app_context):
    monkeypatch.setattr(antispam_logic, "app_context", router_app_context, raising=True)

    message = type("Msg", (), {})()
    message.sender_chat = None
    message.from_user = None
    message.chat = types.Chat(id=123, type="supergroup")
    message.text = "hello"

    assert await antispam_logic.check_spam(message, session=object()) is False
