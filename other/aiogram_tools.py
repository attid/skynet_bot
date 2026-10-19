import asyncio
import html
import re
from enum import Enum
from typing import Any

from aiogram import Bot
from aiogram.filters import Filter
from aiogram.types import (
    BufferedInputFile,
    Chat,
    ChatMember,
    InputRichMessage,
    Message,
    ReactionTypeCustomEmoji,
    User,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from middlewares.retry import logger
from other.config_reader import config
from other.text_tools import extract_url
from services.app_context import app_context

scheduler: AsyncIOScheduler


class AdminPermission(Enum):
    """Перечисление прав администратора в Telegram."""

    CAN_RESTRICT_MEMBERS = "can_restrict_members"
    CAN_DELETE_MESSAGES = "can_delete_messages"
    CAN_PROMOTE_MEMBERS = "can_promote_members"
    CAN_CHANGE_INFO = "can_change_info"
    CAN_INVITE_USERS = "can_invite_users"
    CAN_PIN_MESSAGES = "can_pin_messages"
    CAN_MANAGE_TOPICS = "can_manage_topics"
    CAN_MANAGE_VIDEO_CHATS = "can_manage_video_chats"
    CAN_POST_MESSAGES = "can_post_messages"
    CAN_EDIT_MESSAGES = "can_edit_messages"
    IS_ANONYMOUS = "is_anonymous"


non_breaking_space = chr(0x00A0)


## def get_user_id(user_id: Message | int | User | CallbackQuery):
##     if isinstance(user_id, CallbackQuery):
##         user_id = user_id.from_user.id
##     elif isinstance(user_id, Message):
##         user_id = user_id.from_user.id
##     elif isinstance(user_id, User):
##         user_id = user_id.id
##     else:
##         user_id = user_id
##
##     return user_id


def get_chat_link(chat: Chat):
    if chat.username:
        return f"@{chat.username} {chat.title}"

    return f"<a href='https://t.me/c/{chat.id}/999999999999'>{chat.title}</a>"


## async def is_admin(event: Message | CallbackQuery, chat_id=None, permission: AdminPermission = None):
##     \"\"\"
##     Проверяет, является ли пользователь администратором чата и имеет ли указанные права.
##
##     Args:
##         event (Message | CallbackQuery): Объект сообщения или колбэка.
##         chat_id: ID чата для проверки. Если None, будет определен из event.
##         permission (AdminPermission, optional): Право администратора для проверки из перечисления AdminPermission.
##             Например, AdminPermission.CAN_RESTRICT_MEMBERS.
##         Если None, проверяется только статус администратора.
##
##     Returns:
##         bool: True, если пользователь является администратором и имеет указанные права (если указаны).
##
##     Examples:
##         # Проверка, является ли пользователь администратором
##         is_admin_result = await is_admin(message)
##
##         # Проверка, может ли администратор ограничивать пользователей
##         can_restrict = await is_admin(message, permission=AdminPermission.CAN_RESTRICT_MEMBERS)
##     \"\"\"
##     if chat_id is None:
##         if isinstance(event, CallbackQuery):
##             chat_id = event.message.chat.id
##         else:
##             chat_id = event.chat.id
##
##     user_id = get_user_id(event)
##
##     if user_id == MTLChats.GroupAnonymousBot:
##         return True
##
##     if user_id == chat_id:
##         return True
##
##     with suppress(TelegramBadRequest):
##         members = await event.bot.get_chat_administrators(chat_id=chat_id)
##
##         if permission is None:
##             # Проверяем только статус администратора
##             return any(member.user.id == user_id for member in members)
##         else:
##             # Проверяем наличие указанного права у администратора
##             for member in members:
##                 if member.user.id == user_id:
##                     # Проверяем, есть ли у администратора указанное право
##                     return getattr(member, permission.value, False)
##
##             return False


def add_text(lines, num_line, text):
    if len(lines) > num_line - 1:
        lines.pop(num_line - 1)
    lines.append(text)
    return "\n".join(lines)


# def cmd_delete_later(message: Message, minutes=5, seconds=None):
#     current_time = datetime.now()
#     if seconds:
#         future_time = current_time + timedelta(seconds=seconds)
#     else:
#         future_time = current_time + timedelta(minutes=minutes)
#     scheduler.add_job(cmd_delete_by_scheduler, run_date=future_time, args=(message,))  # noqa: F821


async def cmd_sleep_and_delete(message: Message, sleep_time=3 * 60):
    """
    Asynchronous function that sleeps for a specified time and then attempts to delete a message.
    Args:
        message (Message): The message to be deleted.
        sleep_time: The time to sleep in seconds.
    """
    # asyncio.ensure_future(cmd_sleep_and_delete_task(message, sleep_time))
    return asyncio.create_task(cmd_sleep_and_delete_task(message, sleep_time))


async def cmd_sleep_and_delete_task(message: Message, sleep_time):
    if sleep_time is None:
        sleep_time = 0
    await asyncio.sleep(sleep_time)
    try:
        await message.delete()
    except Exception:
        pass


async def cmd_delete_by_scheduler(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


def message_body(message: Message) -> tuple[str, list]:
    """Return the searchable body of a message and its entities.

    Media posts keep their text in ``caption``/``caption_entities``, so the
    plain ``text``/``entities`` pair is empty for them.
    """
    if message.text:
        return message.text, list(message.entities or [])
    return message.caption or "", list(message.caption_entities or [])


def message_text(message: Message) -> str:
    """Return text or caption of a message."""
    return message_body(message)[0]


def rich_message_text(message: Message) -> str:
    """Flatten ``Message.rich_message`` blocks into plain text.

    Rich posts (the new Bot API message format) carry their content in blocks,
    so ``text``/``caption`` stay empty for them.
    """
    rich_message = getattr(message, "rich_message", None)
    if rich_message is None:
        return ""
    try:
        payload = rich_message.model_dump(exclude_none=True)
    except Exception:
        logger.exception("cannot dump rich_message")
        return ""
    return "\n".join(_iter_string_values(payload, skip_keys={"type"}))


def _iter_string_values(value: Any, skip_keys: set[str] | None = None) -> list[str]:
    """Collect all string values of a nested pydantic-dump structure."""
    skip_keys = skip_keys or set()
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for key, nested in value.items():
            if key in skip_keys:
                continue
            found.extend(_iter_string_values(nested, skip_keys))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.extend(_iter_string_values(nested, skip_keys))
    return found


def message_full_text(message: Message) -> str:
    """Return any searchable text of a message: text, caption or rich blocks."""
    return message_text(message) or rich_message_text(message)


def extract_message_url(message: Message, host: str = "eurmtl.me", allow_scheme_less: bool = True) -> str | None:
    """Find an URL of ``host`` in the message text, caption, rich blocks, entities or buttons.

    Handles messages where the link is hidden behind a text_link entity
    (markdown-style links), links without an explicit scheme, links that live
    only in an inline keyboard button (sign-tool notifications) and rich
    messages that carry their content in blocks instead of ``text``.
    """
    text, entities = message_body(message)
    url = extract_url(text, host, allow_scheme_less=allow_scheme_less)
    if url:
        return url
    for entity in entities:
        entity_url = getattr(entity, "url", None)
        if entity_url:
            found = extract_url(entity_url, host, allow_scheme_less=allow_scheme_less)
            if found:
                return found
        if entity.type == "url":
            try:
                found = extract_url(entity.extract_from(text), host, allow_scheme_less=allow_scheme_less)
            except Exception:
                logger.exception("cannot extract url from entity")
                continue
            if found:
                return found
    url = extract_url(rich_message_text(message), host, allow_scheme_less=allow_scheme_less)
    if url:
        return url
    return extract_url_from_reply_markup(message, host, allow_scheme_less=allow_scheme_less)


def extract_reply_url(message: Message, host: str = "eurmtl.me", allow_scheme_less: bool = True) -> str | None:
    """Find a tool URL in what an incoming message replies to.

    Looks into the replied message itself (text, caption, rich blocks,
    buttons) and into the server-side quote, which is how replies to a channel
    post in a comments thread are delivered.
    """
    reply = getattr(message, "reply_to_message", None)
    if reply is not None:
        url = extract_message_url(reply, host, allow_scheme_less=allow_scheme_less)
        if url:
            return url
    quote = getattr(message, "quote", None)
    quote_text = getattr(quote, "text", None)
    if quote_text:
        url = extract_url(quote_text, host, allow_scheme_less=allow_scheme_less)
        if url:
            return url
    return None


def describe_reply_dump(message: Message, limit: int = 2500) -> str:
    """Compact dump of the replied message for debugging unreadable replies."""
    reply = getattr(message, "reply_to_message", None)
    parts: list[str] = []
    if reply is None:
        parts.append("reply=None")
    else:
        try:
            parts.append(f"reply_type={type(reply).__name__}")
            parts.append(f"reply_keys={sorted(reply.model_dump(exclude_none=True).keys())}")
            parts.append(f"reply_dump={reply.model_dump_json(exclude_none=True)[:limit]}")
        except Exception:
            logger.exception("cannot dump replied message")
            parts.append(f"reply_repr={reply!r}"[:limit])
    quote = getattr(message, "quote", None)
    if quote is not None:
        parts.append(f"quote_text={getattr(quote, 'text', None)!r}"[:limit])
    return " | ".join(parts)


def extract_url_from_reply_markup(
    message: Message, host: str = "eurmtl.me", allow_scheme_less: bool = False
) -> str | None:
    """Find an URL of ``host`` among the inline keyboard buttons of a message."""
    reply_markup = getattr(message, "reply_markup", None)
    rows = getattr(reply_markup, "inline_keyboard", None) or []
    for row in rows:
        for button in row or []:
            button_url = getattr(button, "url", None)
            if not button_url:
                continue
            found = extract_url(button_url, host, allow_scheme_less=allow_scheme_less)
            if found:
                return found
    return None


# Plain ``sendMessage`` allows 4096 characters, rich messages allow 16384.
PLAIN_MESSAGE_LIMIT = 4000
RICH_MESSAGE_LIMIT = 16000

_PRE_BLOCK_RE = re.compile(r"(<pre>.*?</pre>|<code>.*?</code>)", re.DOTALL)


def html_for_rich_message(text: str) -> str:
    """Convert plain line breaks into explicit ``<br>`` for rich messages.

    Rich messages are parsed as HTML, where a newline is just whitespace — so
    the usual ``\n`` separated answer would collapse into one paragraph. Fragments
    inside ``<pre>``/``<code>`` keep their newlines as is.
    """
    parts = _PRE_BLOCK_RE.split(text)
    return "".join(part if index % 2 else part.replace("\n", "<br>") for index, part in enumerate(parts))


def split_html(text: str, limit: int) -> list[str]:
    """Split HTML text into chunks of at most ``limit`` characters.

    Splits on newlines so tags are never cut in the middle.
    """
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        else:
            cut += 1  # keep the newline so no characters are lost on re-joining
        chunks.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        chunks.append(rest)
    return chunks


async def multi_reply(message: Message, text: str):
    """Reply with ``text``, keeping long answers in a single rich message.

    Plain messages are limited to 4096 characters, so long texts used to arrive
    as several messages. Rich messages hold up to 16384 characters; when the
    chat rejects one, we fall back to the classic chunked replies.
    """
    if not text:
        return
    if len(text) <= PLAIN_MESSAGE_LIMIT:
        await message.reply(text)
        return

    chunks = split_html(text, RICH_MESSAGE_LIMIT)
    for index, chunk in enumerate(chunks):
        try:
            await message.reply_rich(InputRichMessage(html=html_for_rich_message(chunk)))
        except Exception:
            logger.warning("rich reply failed (len=%s), falling back to plain replies", len(chunk), exc_info=True)
            for plain_chunk in split_html("\n".join(chunks[index:]), PLAIN_MESSAGE_LIMIT):
                await message.reply(plain_chunk)
            return


async def multi_answer(message: Message, text: str):
    while len(text) > 0:
        await message.answer(text[:4000])
        text = text[4000:]


async def answer_text_file(message: Message, text: str, filename: str = None):
    """Отправляет текст как файл, используя BufferedInputFile"""
    if filename is None:
        filename = f"response_{message.message_id}.txt"
    text_file = BufferedInputFile(text.encode(), filename=filename)
    await message.answer_document(text_file)


def has_words(master, words_array):
    for word in words_array:
        if master.upper().find(word.upper()) > -1:
            return True
    return False


def start_words(master, words_array):
    if master:
        for word in words_array:
            if master.upper().startswith(word.upper()):
                return True
    return False


class HasText(Filter):
    def __init__(self, my_arr: tuple) -> None:
        self.my_arr = my_arr

    async def __call__(self, message: Message) -> bool:
        return has_words(message.text, self.my_arr)


class StartText(Filter):
    def __init__(self, my_arr: tuple) -> None:
        self.my_arr = my_arr

    async def __call__(self, message: Message) -> bool:
        return start_words(message.text, self.my_arr)


class HasRegex(Filter):
    """Фильтр для проверки регулярных выражений в сообщении"""

    def __init__(self, patterns: tuple) -> None:
        self.patterns = [re.compile(pattern) for pattern in patterns]

    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False

        for pattern in self.patterns:
            match = pattern.search(message.text)
            if match:
                pass
                # logger.info(f"HasRegex: Паттерн '{pattern.pattern}' найден: {match.group()}")
            else:
                return False

        return True


class ReplyToBot(Filter):
    async def __call__(self, message: Message, bot: Bot) -> bool:
        reply = message.reply_to_message
        return bool(reply and reply.from_user and reply.from_user.id == bot.id)


class ChatInOption(Filter):
    """Filter that checks if chat has a feature flag enabled."""

    def __init__(self, feature_name: str) -> None:
        self.feature_name = feature_name

    async def __call__(self, message: Message) -> bool:
        # Use app_context singleton to check feature flags
        if app_context and app_context.feature_flags:
            return app_context.feature_flags.is_enabled(message.chat.id, self.feature_name)
        return False


def get_username_link(user: User):
    full_name = html.unescape(user.full_name)
    if user.username:
        username = f"@{user.username} {full_name}"
    else:
        username = f'<a href="tg://user?id={user.id}">{full_name}</a>'
    return username


async def get_user_info(bot: Bot, chat_id: int, user_id: int) -> ChatMember | None:
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member
    except Exception as e:
        print(f"Ошибка при получении информации о пользователе: {e}")
        return None


async def main():
    bot = Bot(token=config.bot_token.get_secret_value())
    try:
        chat_id = -1001429770534
        user_ids = [7539876829, 7321780032]

        for user_id in user_ids:
            user_info = await get_user_info(bot, chat_id, user_id)
            if user_info:
                print(f"Информация о пользователе {user_id}:", user_info)
            else:
                print(f"Не удалось получить информацию о пользователе {user_id}")
    finally:
        await bot.session.close()


async def main0(chat_id: str = "@Montelibero_ru", message_id: int = 9544, custom_emoji_id: str = "5458863124947942457"):
    async with Bot(
        token=config.bot_token.get_secret_value(),
    ) as bot:
        await bot.set_message_reaction(
            chat_id=chat_id, message_id=message_id, reaction=[ReactionTypeCustomEmoji(custom_emoji_id=custom_emoji_id)]
        )


async def update_mongo_chats_names():
    chats = await app_context.db_service.get_all_chats()

    async with Bot(token=config.bot_token.get_secret_value()) as bot:
        for chat in chats:
            try:
                info = await bot.get_chat(chat_id=chat.chat_id)
                count = await app_context.db_service.update_chat_with_dict(
                    chat.chat_id, {"username": info.username, "title": info.title, "name": None}
                )
                print(count)
                await asyncio.sleep(0.3)
            except Exception as ex:
                logger.warning(ex)


if __name__ == "__main__":
    a = asyncio.run(update_mongo_chats_names())
    print(a)
