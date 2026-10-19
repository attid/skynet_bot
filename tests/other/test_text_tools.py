import datetime

from aiogram import types

from other.aiogram_tools import (
    extract_message_url,
    extract_reply_url,
    message_body,
    message_text,
    rich_message_text,
)
from other.text_tools import extract_url


def _message(**kwargs) -> types.Message:
    defaults = dict(
        message_id=1,
        date=datetime.datetime.now(),
        chat=types.Chat(id=1, type="supergroup", title="Group"),
        from_user=types.User(id=1, is_bot=False, first_name="User"),
    )
    return types.Message(**{**defaults, **kwargs})


def test_extract_url_basic():
    assert extract_url("see https://eurmtl.me/sign_tools/abc123 now") == "https://eurmtl.me/sign_tools/abc123"


def test_extract_url_strips_trailing_punctuation():
    assert extract_url("link: https://eurmtl.me/sign_tools/abc123).") == "https://eurmtl.me/sign_tools/abc123"
    assert extract_url("(см. https://eurmtl.me/sign_tools/abc123)") == "https://eurmtl.me/sign_tools/abc123"


def test_extract_url_scheme_less_when_allowed():
    assert extract_url("eurmtl.me/sign_tools/abc123", allow_scheme_less=True) == ("https://eurmtl.me/sign_tools/abc123")
    assert extract_url("eurmtl.me/sign_tools/abc123") is None


def test_extract_url_other_host_ignored():
    assert extract_url("https://example.com/sign_tools/abc123") is None
    assert extract_url("https://example.com/sign_tools/abc123", surl=None) == "https://example.com/sign_tools/abc123"


def test_extract_url_subdomain_and_case():
    assert extract_url("https://WWW.Eurmtl.me/sign_tools/abc") == "https://WWW.Eurmtl.me/sign_tools/abc"


def test_extract_url_empty_or_none():
    assert extract_url(None) is None
    assert extract_url("") is None
    assert extract_url("no links here") is None


def test_message_text_prefers_text_over_caption():
    assert message_text(_message(text="hello", caption="cap")) == "hello"
    assert message_text(_message(caption="cap")) == "cap"


def test_message_body_uses_caption_entities():
    caption_entities = [types.MessageEntity(type="url", offset=0, length=10)]
    text, entities = message_body(_message(caption="https://eurmtl.me/x", caption_entities=caption_entities))
    assert text == "https://eurmtl.me/x"
    assert entities == caption_entities


def test_extract_message_url_from_caption():
    message = _message(caption="подписать: https://eurmtl.me/sign_tools/abc123")
    assert extract_message_url(message) == "https://eurmtl.me/sign_tools/abc123"


def test_extract_message_url_from_hidden_text_link():
    message = _message(
        text="смотри тут",
        entities=[types.MessageEntity(type="text_link", offset=0, length=10, url="https://eurmtl.me/sign_tools/abc")],
    )
    assert extract_message_url(message) == "https://eurmtl.me/sign_tools/abc"


def test_extract_message_url_rejects_other_host():
    message = _message(text="https://example.com/sign_tools/abc")
    assert extract_message_url(message) is None


def test_extract_message_url_from_rich_message_blocks():
    """Rich channel posts keep content in blocks, not in text/caption."""
    rich = types.RichMessage(
        blocks=[
            types.RichBlockParagraph(
                text=[
                    "MTLF: Signing and voting ",
                    types.RichTextBold(text="#active Вопрос 706"),
                    " ссылка: https://eurmtl.me/sign_tools/2f633a09c0ffee",
                ]
            )
        ]
    )
    message = _message(rich_message=rich)

    assert message_text(message) == ""
    assert "sign_tools/2f633a09c0ffee" in rich_message_text(message)
    assert extract_message_url(message) == "https://eurmtl.me/sign_tools/2f633a09c0ffee"


def test_extract_message_url_from_quoted_post():
    """Reply to a channel post delivers the link only through Message.quote."""
    quoted = types.Message(
        message_id=2,
        date=datetime.datetime.now(),
        chat=types.Chat(id=1, type="supergroup", title="Comments"),
        from_user=types.User(id=2, is_bot=False, first_name="Author"),
    )
    message = _message(
        text="/decode",
        reply_to_message=quoted,
        quote=types.TextQuote(text="Вопрос 706: https://eurmtl.me/sign_tools/2f633a09c0ffee", position=0),
    )

    assert extract_message_url(message.reply_to_message) is None
    assert extract_reply_url(message) == "https://eurmtl.me/sign_tools/2f633a09c0ffee"


def test_extract_message_url_from_inline_button():
    message = _message(
        text="Транзакция ожидает подписи",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="Подписать", url="https://eurmtl.me/sign_tools/2f633a09c0ffee")]
            ]
        ),
    )
    assert extract_message_url(message) == "https://eurmtl.me/sign_tools/2f633a09c0ffee"
