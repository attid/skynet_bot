from contextlib import suppress
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from other.text_tools import extract_url
from start import add_bot_users
from other.constants import MTLChats, BotValueTypes
from services.app_context import app_context
from shared.domain.user import SpamStatus
from other.spam_cheker import is_mixed_word, contains_spam_phrases, combo_check_spammer, lols_check_spammer
from other.open_ai_tools import talk_check_spam


class SpamCheckCallbackData(CallbackData, prefix="SpamCheck"):
    message_id: int
    chat_id: int
    user_id: int
    good: bool
    new_message_id: int
    message_thread_id: int


class FirstMessageCallbackData(CallbackData, prefix="first"):
    user_id: int
    message_id: int
    spam: bool


def _get_sender_id(message) -> int | None:
    from_user = getattr(message, "from_user", None)
    sender_chat = getattr(message, "sender_chat", None)
    if from_user and from_user.id == MTLChats.Channel_Bot and sender_chat:
        return sender_chat.id
    if from_user:
        return from_user.id
    if sender_chat:
        return sender_chat.id
    return None


def _get_sender_username(message) -> str | None:
    from_user = getattr(message, "from_user", None)
    sender_chat = getattr(message, "sender_chat", None)
    if from_user:
        return from_user.username
    if sender_chat:
        return sender_chat.username
    return None


async def save_url(chat_id, msg_id, msg):
    url = extract_url(msg)
    await app_context.db_service.save_bot_value(chat_id, BotValueTypes.PinnedUrl, url)
    await app_context.db_service.save_bot_value(chat_id, BotValueTypes.PinnedId, msg_id)


async def delete_and_log_spam(message, session, rules_name):
    user_id = _get_sender_id(message)
    if user_id is None:
        logger.warning("Skip spam delete/log: message has no from_user or sender_chat")
        return
    # user_username = message.sender_chat.username if message.sender_chat else message.from_user.username
    with suppress(TelegramBadRequest):
        await message.chat.restrict(
            user_id,
            permissions=ChatPermissions(
                can_send_messages=False, can_send_media_messages=False, can_send_other_messages=False
            ),
        )
    msg = await message.forward(MTLChats.SpamGroup)
    chat_link = f"@{message.chat.username}" if message.chat.username else message.chat.invite_link
    msg_text = f"Сообщение из чата {message.chat.title} {chat_link}\n{rules_name}"
    if message.reply_to_message:
        msg_text += f"\nОтвет на сообщение: {message.reply_to_message.get_url()}"

    external_reply = message.external_reply
    if not external_reply and message.reply_to_message:
        external_reply = message.reply_to_message.external_reply
    if external_reply:
        ext_chat = getattr(external_reply, "chat", None)
        ext_chat_title = getattr(ext_chat, "title", None) if ext_chat else None
        ext_chat_id = getattr(ext_chat, "id", None) if ext_chat else None
        ext_message_id = getattr(external_reply, "message_id", None)
        msg_text += f"\nExternal reply: chat_id={ext_chat_id}, msg_id={ext_message_id}"
        if ext_chat_title:
            msg_text += f" ({ext_chat_title})"
        logger.info(f"External reply detected for spam: chat_id={ext_chat_id}, message_id={ext_message_id}")

    await msg.reply(
        msg_text,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Restore. Its good msg !",
                        callback_data=SpamCheckCallbackData(
                            message_id=message.message_id,
                            chat_id=message.chat.id,
                            user_id=user_id,
                            new_message_id=msg.message_id,
                            message_thread_id=message.message_thread_id if message.message_thread_id else 0,
                            good=True,
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Its spam! Kick him !",
                        callback_data=SpamCheckCallbackData(
                            message_id=message.message_id,
                            chat_id=message.chat.id,
                            user_id=user_id,
                            new_message_id=msg.message_id,
                            message_thread_id=message.message_thread_id if message.message_thread_id else 0,
                            good=False,
                        ).pack(),
                    )
                ],
            ]
        ),
    )
    await message.delete()
    add_bot_users(session, user_id, _get_sender_username(message), 0)


async def set_vote(message):
    user_id = _get_sender_id(message)
    if user_id is None:
        logger.warning("Skip first-message vote: message has no from_user or sender_chat")
        return
    if app_context.voting_service.is_first_vote_enabled(message.chat.id):
        kb_reply = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Spam",
                        callback_data=FirstMessageCallbackData(
                            spam=True, message_id=message.message_id, user_id=user_id
                        ).pack(),
                    ),
                    InlineKeyboardButton(
                        text="Good",
                        callback_data=FirstMessageCallbackData(
                            spam=False, message_id=message.message_id, user_id=user_id
                        ).pack(),
                    ),
                ]
            ]
        )
        await message.reply(text="Please help me detect spam messages", reply_markup=kb_reply)


async def check_spam(message, session=None):
    # Check session? In last_handler it was passed.
    # We should assume session is needed for add_bot_users?
    # Yes, add_bot_users(session, ...)
    # If session is None, add_bot_users might fail if it uses DB.
    # In last_handler.py: async def check_spam(message, session):
    # So we need session.

    from_user = getattr(message, "from_user", None)
    if from_user and from_user.id == MTLChats.Telegram_Repost_Bot:
        return False

    user_id = _get_sender_id(message)
    if user_id is None:
        logger.warning("Skip spam check: message has no from_user or sender_chat")
        return False

    if app_context.check_user(user_id) == SpamStatus.GOOD:
        return False

    rules_name = "xz"
    process_message = False

    if await combo_check_spammer(user_id):
        process_message = True
        rules_name = f'<a href="https://cas.chat/query?u={user_id}">CAS ban</a>'

    if await lols_check_spammer(user_id):
        process_message = True
        rules_name = (f'<a href="https://lols.bot/?u={user_id}">LOLS base</a>',)

    if not process_message and message.entities:
        custom_emoji_count = 0
        for entity in message.entities:
            if entity.type in ("url", "text_link", "mention"):
                rules_name = "link"
                process_message = True
                break
            elif entity.type == "custom_emoji":
                custom_emoji_count += 1

        if custom_emoji_count > 3:
            process_message = True
            rules_name = "emoji"

    if not process_message and message.external_reply:
        process_message = True
        rules_name = "external_reply"

    if not process_message:
        words = message.text.split()
        mixed_word_count = sum(is_mixed_word(word) for word in words)
        if mixed_word_count >= 3:
            process_message = True
            rules_name = "mixed"

    if not process_message and contains_spam_phrases(message.text):
        process_message = True
        rules_name = "spam_phrases"

    if not process_message:
        spam_persent = await talk_check_spam(message.text)
        logger.info(f"{spam_persent} {message.text}")
        if spam_persent and spam_persent > 69:
            process_message = True
            rules_name = "open AI"

    if process_message:
        await delete_and_log_spam(message, session, rules_name)
        return True
    else:
        add_bot_users(session, user_id, _get_sender_username(message), 1)
        await set_vote(message)
        return False
