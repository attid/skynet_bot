import pytest
import asyncio
from other.aiogram_tools import cmd_sleep_and_delete_task
from tests.fakes import FakeAsyncMethod


@pytest.mark.asyncio
async def test_cmd_sleep_and_delete_task_none_sleep_time():
    message = type("Msg", (), {})()
    message.delete = FakeAsyncMethod(return_value=None)
    calls = []

    async def fake_sleep(seconds):
        calls.append(seconds)

    original_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        await cmd_sleep_and_delete_task(message, None)
    finally:
        asyncio.sleep = original_sleep

    assert calls == [0]
    message.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_cmd_sleep_and_delete_task_valid_sleep_time():
    message = type("Msg", (), {})()
    message.delete = FakeAsyncMethod(return_value=None)
    calls = []

    async def fake_sleep(seconds):
        calls.append(seconds)

    original_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        await cmd_sleep_and_delete_task(message, 10)
    finally:
        asyncio.sleep = original_sleep

    assert calls == [10]
    message.delete.assert_awaited_once()


# ============================================================================
# Rich replies
# ============================================================================

from other.aiogram_tools import (  # noqa: E402
    PLAIN_MESSAGE_LIMIT,
    html_for_rich_message,
    multi_reply,
    split_html,
)


def test_html_for_rich_message_converts_newlines():
    assert html_for_rich_message("Операция 0\nОперация 1") == "Операция 0<br>Операция 1"
    assert html_for_rich_message("a\n\nb") == "a<br><br>b"


def test_html_for_rich_message_keeps_preformatted_newlines():
    text = "Заголовок\n<pre>код 1\nкод 2</pre>\nХвост"
    assert html_for_rich_message(text) == "Заголовок<br><pre>код 1\nкод 2</pre><br>Хвост"


def test_html_for_rich_message_keeps_code_inline():
    assert html_for_rich_message("<code>a\nb</code>") == "<code>a\nb</code>"


def test_split_html_prefers_newlines():
    text = "line1\n" * 3
    chunks = split_html(text, limit=12)

    assert all(len(chunk) <= 12 for chunk in chunks)
    assert all(chunk.startswith("line1") for chunk in chunks)


def _reply_message():
    message = type("Msg", (), {})()
    message.reply = FakeAsyncMethod(return_value=None)
    message.reply_rich = FakeAsyncMethod(return_value=None)
    return message


@pytest.mark.asyncio
async def test_multi_reply_short_text_stays_plain():
    message = _reply_message()

    await multi_reply(message, "коротко")

    message.reply.assert_awaited_once()
    assert not message.reply_rich.called


@pytest.mark.asyncio
async def test_multi_reply_long_text_sent_as_single_rich_message_with_breaks():
    message = _reply_message()
    text = "\n".join(f"Операция {index}" for index in range(1000))

    await multi_reply(message, text)

    args, kwargs = message.reply_rich.call_args
    rich_html = args[0].html if args else kwargs["rich_message"].html
    assert rich_html.count("<br>") == text.count("\n")
    assert "\n" not in rich_html
    assert not message.reply.called


@pytest.mark.asyncio
async def test_multi_reply_falls_back_to_plain_chunks():
    message = _reply_message()
    message.reply_rich = FakeAsyncMethod(side_effect=RuntimeError("rich rejected"))
    text = "\n".join(f"Операция {index} " + "x" * 40 for index in range(300))

    await multi_reply(message, text)

    assert message.reply_rich.called
    sent = [call[0][0] for call in message.reply.call_args_list]
    assert len(sent) >= 2
    assert all(len(chunk) <= PLAIN_MESSAGE_LIMIT for chunk in sent)
    assert sum(len(chunk) for chunk in sent) >= len(text)
