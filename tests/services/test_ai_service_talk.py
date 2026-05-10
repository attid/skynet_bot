import datetime

import pytest
from aiogram import types

import other.open_ai_tools as open_ai_tools
from services.external_services import AIService, TalkService
from tests.fakes import FakeAsyncMethod


@pytest.mark.asyncio
async def test_ai_service_talk_maps_gpt4_to_gpt_maxi(monkeypatch):
    mock_talk = FakeAsyncMethod(return_value="ok")
    monkeypatch.setattr(open_ai_tools, "talk", mock_talk)

    service = AIService()
    result = await service.talk(123, "Привет как дела", gpt4=True, googleit=True)

    assert result == "ok"
    mock_talk.assert_awaited_once()
    args, kwargs = mock_talk.call_args
    assert args == (123, "Привет как дела")
    assert kwargs["gpt_maxi"] is True
    assert kwargs["googleit"] is True
    assert "gpt4" not in kwargs


@pytest.mark.asyncio
async def test_talk_service_answer_notify_ignores_reply_without_from_user():
    bot = type("Bot", (), {"id": 42, "send_message": FakeAsyncMethod()})()
    service = TalkService(bot)
    app_context = type("AppContext", (), {"notification_service": object()})()

    reply = types.Message(
        message_id=10,
        date=datetime.datetime.now(),
        chat=types.Chat(id=-1001, type="supergroup", title="Group"),
        from_user=None,
        text="Channel message",
    )
    message = types.Message(
        message_id=11,
        date=datetime.datetime.now(),
        chat=types.Chat(id=-1001, type="supergroup", title="Group"),
        from_user=types.User(id=100, is_bot=False, first_name="User"),
        text="Reply",
        reply_to_message=reply,
    )

    await service.answer_notify_message(message, app_context)

    bot.send_message.assert_not_called()
