import asyncio
import html
import json
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any, Optional, cast

from aiogram import F, Bot, Router
from aiogram.enums import MessageEntityType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    Message,
    ChatPermissions,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ReplyParameters,
)
from aiogram.fsm.context import FSMContext
from loguru import logger

from other.text_tools import extract_url
from middlewares.throttling import rate_limit
from other.aiogram_tools import ChatInOption, get_username_link, cmd_sleep_and_delete
from other.constants import MTLChats, BotValueTypes
from other.pyro_tools import MessageInfo, pyro_update_msg_info
from other.miniapps_tools import miniapps
from shared.domain.user import SpamStatus
from services.skyuser import SkyUser

router = Router()


class SpamCheckCallbackData(CallbackData, prefix="SpamCheck"):
    message_id: int
    chat_id: int
    user_id: int
    good: bool
    new_message_id: int
    message_thread_id: int


class ReplyCallbackData(CallbackData, prefix="Reply"):
    message_id: int
    chat_id: int
    user_id: int


class FirstMessageCallbackData(CallbackData, prefix="first"):
    user_id: int
    message_id: int
    spam: bool


def _log_moderation_action(
    *,
    action: str,
    actor_id: int | None,
    actor_username: str | None,
    target_user_id: int,
    chat_id: int,
    source_handler: str,
    result: str,
) -> None:
    logger.info(
        "moderation_action action={} actor_id={} actor_username={} target_user_id={} chat_id={} source_handler={} result={}",
        action,
        actor_id,
        actor_username,
        target_user_id,
        chat_id,
        source_handler,
        result,
    )


########################################################################################################################
##########################################  DI Helpers  ################################################################
########################################################################################################################


def _is_feature_enabled(app_context, chat_id: int, feature: str) -> bool:
    """Check if feature is enabled using DI service. Raises error if app_context not available."""
    if not app_context or not app_context.feature_flags:
        raise ValueError("app_context with feature_flags required")
    return app_context.feature_flags.is_enabled(chat_id, feature)


def _get_spam_status(app_context, user_id: int) -> SpamStatus:
    """Get spam status from app_context.spam_status_service."""
    if not app_context or not app_context.spam_status_service:
        raise ValueError("app_context with spam_status_service required")
    return app_context.spam_status_service.get_status(user_id)


def _is_first_vote_enabled(app_context, chat_id: int) -> bool:
    """Check if first vote is enabled using DI service. Raises error if app_context not available."""
    if not app_context or not app_context.voting_service:
        raise ValueError("app_context with voting_service required")
    return app_context.voting_service.is_first_vote_enabled(chat_id)


def _get_first_vote_data(app_context, key: str, default: dict) -> dict:
    """Get first vote data by key using DI service. Raises error if app_context not available."""
    if not app_context or not app_context.voting_service:
        raise ValueError("app_context with voting_service required")
    return app_context.voting_service.get_first_vote_data_by_key(key, default)


def _set_first_vote_data(app_context, key: str, data: dict) -> None:
    """Set first vote data by key using DI service. Raises error if app_context not available."""
    if not app_context or not app_context.voting_service:
        raise ValueError("app_context with voting_service required")
    app_context.voting_service.set_first_vote_data_by_key(key, data)


def _has_alert_users(app_context, chat_id: int) -> bool:
    """Check if chat has alert users using DI service. Raises error if app_context not available."""
    if not app_context or not app_context.notification_service:
        raise ValueError("app_context with notification_service required")
    return bool(app_context.notification_service.get_alert_users(chat_id))


def _get_alert_users(app_context, chat_id: int) -> list:
    """Get alert users for chat using DI service. Raises error if app_context not available."""
    if not app_context or not app_context.notification_service:
        raise ValueError("app_context with notification_service required")
    return app_context.notification_service.get_alert_users(chat_id)


def _get_message_notify_config(app_context, chat_id: int) -> Optional[str]:
    """Get message notification config using DI service. Raises error if app_context not available."""
    if not app_context or not app_context.notification_service:
        raise ValueError("app_context with notification_service required")
    return app_context.notification_service.get_message_notify_config(chat_id)


def _get_topic_mutes(app_context, chat_id: int, thread_id: int | None) -> dict:
    """Get topic mutes using DI service. Raises error if app_context not available."""
    if not app_context or not app_context.admin_service:
        raise ValueError("app_context with admin_service required")
    return app_context.admin_service.get_topic_mutes(chat_id, thread_id)


def _remove_topic_mute(app_context, chat_id: int, thread_id: int | None, user_id: int) -> None:
    """Remove topic mute using DI service. Raises error if app_context not available."""
    if not app_context or not app_context.admin_service:
        raise ValueError("app_context with admin_service required")
    app_context.admin_service.remove_user_mute(chat_id, thread_id, user_id)


def _get_db_service(app_context):
    """Return async database service from app context."""
    if not app_context or not app_context.db_service:
        raise ValueError("app_context with db_service required")
    return app_context.db_service


async def _save_topic_mutes_to_db(app_context) -> None:
    """Save topic mutes to database using async database service."""
    if not app_context or not app_context.admin_service:
        raise ValueError("app_context with admin_service required")
    all_mutes = app_context.admin_service.get_all_topic_mutes()
    await _get_db_service(app_context).save_bot_value(0, BotValueTypes.TopicMutes, json.dumps(all_mutes))


########################################################################################################################
##########################################  functions  #################################################################
########################################################################################################################


def _get_sender_name(message: Message) -> str:
    # from_user can be None for channel/anonymous messages; fall back to sender_chat.
    if message.from_user:
        if message.from_user.username:
            return message.from_user.username
        return html.escape(message.from_user.full_name)
    if message.sender_chat:
        if message.sender_chat.username:
            return message.sender_chat.username
        return html.escape(message.sender_chat.title or "")
    return ""


async def save_url(chat_id, msg_id, msg, app_context):
    url = extract_url(msg)
    db_service = _get_db_service(app_context)
    await db_service.save_bot_value(chat_id, BotValueTypes.PinnedUrl, url)
    await db_service.save_bot_value(chat_id, BotValueTypes.PinnedId, msg_id)


async def set_vote(message, app_context=None):
    from_user_id = message.from_user.id if message.from_user else 0
    user_id = message.sender_chat.id if message.sender_chat else from_user_id
    if _is_first_vote_enabled(app_context, message.chat.id):
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


async def check_alert(bot, message, session, app_context=None):
    # if user need be alert
    if message.entities and _has_alert_users(app_context, message.chat.id):
        # Создаем msg_info один раз для всего сообщения
        msg_info = MessageInfo(
            chat_id=message.chat.id,
            user_from=_get_sender_name(message),
            message_id=message.message_id,
            chat_name=message.chat.title or "",
            message_text=message.html_text or "",
        )
        if message.reply_to_message:
            msg_info.reply_to_message = MessageInfo(
                chat_id=message.chat.id,
                user_from=_get_sender_name(message.reply_to_message),
                message_id=message.reply_to_message.message_id,
                message_text=message.reply_to_message.html_text or "",
            )

        # Получаем инфу о топике через Pyro один раз для сообщения
        await pyro_update_msg_info(msg_info)

        # Формируем topic_info один раз
        topic_info = ""
        if getattr(msg_info, "thread_id", None):
            chat_id_num = str(abs(message.chat.id))[3:]
            thread_id = msg_info.thread_id
            thread_name = getattr(msg_info, "thread_name", None)
            # thread_link = f"https://t.me/c/{chat_id_num}/{message.message_id}?thread={thread_id}"
            thread_link = f"https://t.me/c/{chat_id_num}/{thread_id}"
            if thread_name:
                topic_info = f'Топик <a href="{thread_link}">"{thread_name}"</a>\n'
            else:
                topic_info = f'Топик <a href="{thread_link}">id {thread_id}</a>\n'

        # Создаем Telegraph страницу один раз для всего сообщения
        telegraph_link = await miniapps.create_uuid_page(msg_info)
        chat_name_display = (msg_info.chat_name or "")[:30]
        buttons = [[InlineKeyboardButton(text=f"ПП {chat_name_display}", url=telegraph_link.url)]]

        for entity in message.entities:
            if entity.type == "mention":
                username = entity.extract_from(message.text)
                try:
                    user_id = await _get_db_service(app_context).get_user_id(username)
                except ValueError as ex:
                    user_id = 0
                    logger.warning(ex)
                alert_users = _get_alert_users(app_context, message.chat.id)
                if user_id > 0 and user_id in alert_users:
                    with suppress(TelegramBadRequest, TelegramForbiddenError):
                        alert_username = get_username_link(message.from_user)

                        await bot.send_message(
                            user_id,
                            f"Вас упомянул {alert_username}\n"
                            f"В чате {message.chat.title}\n"
                            f"{topic_info}"
                            f"Ссылка на сообщение {message.get_url()}",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                            parse_mode="HTML",
                        )


async def save_last(message, session, app_context=None):
    if _is_feature_enabled(app_context, message.chat.id, "save_last_message_date"):
        if message.from_user:
            await _get_db_service(app_context).update_user_chat_date(message.from_user.id, message.chat.id)


async def notify_message(message: Message, app_context=None):
    if message.is_automatic_forward:
        return

    if not message.from_user:
        return
    if not message.bot:
        return
    notify_config = _get_message_notify_config(app_context, message.chat.id)
    if notify_config:
        record = notify_config.split(":")
        dest_chat = record[0]
        dest_topic = int(record[1]) if len(record) > 1 and record[1].isdigit() else None
        if len(dest_chat) > 3:
            kb_reply = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="BanAndDelete",
                            callback_data=ReplyCallbackData(
                                chat_id=message.chat.id, message_id=message.message_id, user_id=message.from_user.id
                            ).pack(),
                        ),
                        InlineKeyboardButton(text="👀", callback_data="👀"),
                    ]
                ]
            )

            dest_chat_member = await message.bot.get_chat_member(dest_chat, message.from_user.id)
            username = message.from_user.username
            if dest_chat_member.status != "left":
                user_mention = f"{username}" if username else f"{message.from_user.first_name}"
            else:
                user_mention = f"@{username}" if username else f"{message.from_user.first_name}"

            await message.bot.send_message(
                chat_id=dest_chat,
                message_thread_id=dest_topic,
                text=f"User {user_mention}: \nChat: {html.escape(message.chat.title or '')}",
                reply_markup=kb_reply,
                reply_parameters=ReplyParameters(message_id=message.message_id, chat_id=message.chat.id),
            )
            # print(msg)


async def cmd_check_reply_only(message: Message, session: Any, bot: Bot, state: FSMContext, app_context=None):
    has_hashtag = False
    if message.entities:
        for entity in message.entities:
            if entity.type == MessageEntityType.HASHTAG:
                has_hashtag = True
                break

    # Проверяем временное разрешение от FSM
    has_temp_permission = False
    fsm_data = await state.get_data()
    expiration_str = fsm_data.get("reply_only_expiration")

    if expiration_str:
        try:
            expiration_time = datetime.fromisoformat(expiration_str)
            if datetime.now() <= expiration_time:
                has_temp_permission = True
            else:
                # Время истекло, удаляем наш ключ
                await state.update_data(reply_only_expiration=None)
        except ValueError:
            # Некорректный формат времени, удаляем ключ
            await state.update_data(reply_only_expiration=None)

    # Если есть хэштег, устанавливаем временное разрешение
    if has_hashtag:
        expiration_time = datetime.now() + timedelta(minutes=1)
        await state.update_data(reply_only_expiration=expiration_time.isoformat())

    if (
        message.reply_to_message
        or message.forward_from_chat
        or has_hashtag
        or has_temp_permission
        or message.is_automatic_forward
    ):
        if message.from_user:
            await _get_db_service(app_context).save_message(
                user_id=message.from_user.id,
                username=message.from_user.username or "",
                thread_id=message.message_thread_id or 0,
                text=message.text or "",
                chat_id=message.chat.id,
            )
    else:
        msg = await message.reply(
            "В этом чате включен режим контроля использования функции ответа. \n"
            "Сообщение будет удаленно через 15 секунд!\n"
            'Рекомендую скопировать его повторить его с использованием функции "ответ" на нужное сообщение.\n'
            '<a href="https://telegra.ph/rc-06-15-3">Подробнее о режиме тут</a>',
            disable_web_page_preview=True,
        )

        await asyncio.sleep(15)
        try:
            if message.has_protected_content:
                if message.from_user:
                    await message.copy_to(chat_id=message.from_user.id)
            else:
                if message.from_user:
                    await message.forward(chat_id=message.from_user.id)
            sender_name = message.from_user.username if message.from_user and message.from_user.username else "user"
            msg_d = await bot.send_message(
                chat_id=message.chat.id,
                disable_web_page_preview=True,
                text=f"Сообщение от {sender_name} переслано в личку.\n"
                '<a href="https://telegra.ph/rc-06-15-3">Подробнее о режиме тут</a>',
            )
        except TelegramBadRequest:
            sender_name = message.from_user.username if message.from_user and message.from_user.username else "user"
            msg_d = await bot.send_message(
                chat_id=message.chat.id,
                disable_web_page_preview=True,
                text=f"Сообщение от {sender_name} удалено\n"
                '<a href="https://telegra.ph/rc-06-15-3">Подробнее о режиме тут</a>',
            )
        except TelegramForbiddenError:
            sender_name = message.from_user.username if message.from_user and message.from_user.username else "user"
            msg_d = await bot.send_message(
                chat_id=message.chat.id,
                disable_web_page_preview=True,
                text=f"Сообщение от {sender_name} удалено. Личка в блокировке =(\n"
                '<a href="https://telegra.ph/rc-06-15-3">Подробнее о режиме тут</a>',
            )
        with suppress(TelegramBadRequest):
            await message.delete()
            await msg.delete()

        if app_context:
            utils_service = cast(Any, app_context.utils_service) if app_context.utils_service else None
            if utils_service:
                await utils_service.sleep_and_delete(msg_d, 120)
        else:
            await cmd_sleep_and_delete(msg_d, 120)


async def cmd_tools(message: Message, bot: Bot, session: Any, app_context=None):
    if not app_context or not app_context.stellar_service or not app_context.utils_service:
        raise ValueError("app_context with stellar_service and utils_service required")
    stellar_service = cast(Any, app_context.stellar_service)
    utils_service = cast(Any, app_context.utils_service)
    url_found = False
    url_text = message.text or ""
    if message.entities:
        for entity in message.entities:
            if entity.type in ["url", "text_link"]:
                base_text = message.text or ""
                url = (
                    entity.url
                    if entity.type == "text_link"
                    else base_text[entity.offset : entity.offset + entity.length]
                )
                if url and "eurmtl.me/sign_tools" in url:
                    url_found = True
                    url_text = url
                    break

    if url_found or ("eurmtl.me/sign_tools" in url_text):
        msg_id = await _get_db_service(app_context).load_bot_value(message.chat.id, BotValueTypes.PinnedId)
        with suppress(TelegramBadRequest):
            await bot.unpin_chat_message(message.chat.id, msg_id)

        await save_url(message.chat.id, message.message_id, url_text, app_context)
        with suppress(TelegramBadRequest):
            await message.pin()

        pinned_url = await _get_db_service(app_context).load_bot_value(message.chat.id, BotValueTypes.PinnedUrl)
        msg = await stellar_service.check_url_xdr(pinned_url)
        msg = "\n".join(msg)

        await utils_service.multi_reply(message, msg)


async def check_mute(message, session, app_context=None):
    if not _is_feature_enabled(app_context, message.chat.id, "moderate"):
        return False

    chat_id = message.chat.id
    thread_id = message.message_thread_id
    topic_mutes = _get_topic_mutes(app_context, chat_id, thread_id)

    if not topic_mutes:
        return False

    user_id = message.from_user.id if message.from_user else 0

    # Check if the user is muted
    if user_id in topic_mutes:
        # Perform mute check for user
        pass
    # Check if the channel (sender_chat) is muted
    elif message.sender_chat and message.sender_chat.id in topic_mutes:
        user_id = message.sender_chat.id
    else:
        return False

    mute_info = topic_mutes[user_id]
    current_time = datetime.now()

    try:
        end_time = datetime.fromisoformat(mute_info["end_time"])
    except ValueError as e:
        chat_thread_key = f"{chat_id}-{thread_id}"
        logger.error(f"Invalid date format for user {user_id} in chat {chat_thread_key}: {e}")
        # Remove the invalid entry
        _remove_topic_mute(app_context, chat_id, thread_id, user_id)
        await _save_topic_mutes_to_db(app_context)
        return False

    if current_time < end_time:
        await message.delete()
        return True
    else:
        _remove_topic_mute(app_context, chat_id, thread_id, user_id)
        await _save_topic_mutes_to_db(app_context)
        return False


########################################################################################################################
##########################################  handlers  ##################################################################
########################################################################################################################


@rate_limit(0, "listen")
@router.message(F.text)  # если текст #точно не приватное, приватные выше остановились
async def cmd_last_check(message: Message, session: Any, bot: Bot, state: FSMContext, app_context=None):
    # Dependency Injection: check_spam
    # Using app_context if available (and antispam service)
    chat_id = message.chat.id

    # Check no_first_link feature using DI service
    if _is_feature_enabled(app_context, chat_id, "no_first_link"):
        if app_context:
            antispam_service = cast(Any, app_context.antispam_service) if app_context.antispam_service else None
            deleted = await antispam_service.check_spam(message, session) if antispam_service else False
        else:
            from other.antispam_logic import check_spam

            deleted = await check_spam(message, session)
        if deleted:
            # If the message was deleted during spam check, we stop processing
            return

    # Check need_decode using DI service
    needs_decode = False
    if app_context and app_context.bot_state_service:
        needs_decode = app_context.bot_state_service.needs_decode(chat_id)

    if needs_decode:
        await cmd_tools(message, bot, session, app_context=app_context)

    # Check save_last_message_date using DI service
    if _is_feature_enabled(app_context, chat_id, "save_last_message_date"):
        await save_last(message, session, app_context=app_context)

    # Check moderate using DI service
    if _is_feature_enabled(app_context, chat_id, "moderate"):
        await check_mute(message, session, app_context=app_context)

    # Check notify_message using DI service
    if _get_message_notify_config(app_context, chat_id):
        await notify_message(message, app_context=app_context)

    # Check reply_only using DI service
    if _is_feature_enabled(app_context, chat_id, "reply_only"):
        await cmd_check_reply_only(message, session, bot, state, app_context=app_context)

    await check_alert(bot, message, session, app_context=app_context)

    from_user_id = message.from_user.id if message.from_user else 0
    user_id = message.sender_chat.id if message.sender_chat else from_user_id
    # Check user type using DI service
    # SpamStatus.NEW == 0 means new user, triggers first vote
    if _get_spam_status(app_context, user_id) == SpamStatus.NEW:
        await set_vote(message, app_context=app_context)

    await _get_db_service(app_context).save_bot_user(
        user_id, message.from_user.username if message.from_user and message.from_user.username else None, 1
    )

    # Check listen using DI service
    if _is_feature_enabled(app_context, chat_id, "listen"):
        await _get_db_service(app_context).save_message(
            user_id=user_id,
            username=message.from_user.username if message.from_user and message.from_user.username else "",
            thread_id=message.message_thread_id or 0,
            text=message.text or "",
            chat_id=message.chat.id,
        )


@router.message(ChatInOption("no_first_link"))  # точно не текс, выше остановились
async def cmd_last_check_other(message: Message, session: Any, bot: Bot, app_context):
    sender_id = message.from_user.id if message.from_user else 0
    user_id = message.sender_chat.id if sender_id == MTLChats.Channel_Bot and message.sender_chat else sender_id

    # Check user type using DI service
    # SpamStatus.GOOD means good user, skip spam check
    if _get_spam_status(app_context, user_id) == SpamStatus.GOOD:
        return False

    antispam_service = cast(Any, app_context.antispam_service) if app_context and app_context.antispam_service else None
    if antispam_service:
        await antispam_service.delete_and_log_spam(message, session)


########################################################################################################################
#####################################  callback_query  #################################################################
########################################################################################################################


def get_named_reply_markup(button_text):
    reply_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, callback_data="👀")]])
    return reply_markup


@rate_limit(0, "listen")
@router.callback_query(SpamCheckCallbackData.filter())
async def cq_spam_check(
    query: CallbackQuery,
    callback_data: SpamCheckCallbackData,
    bot: Bot,
    session: Any,
    app_context=None,
    skyuser: SkyUser | None = None,
):
    admin = await skyuser.is_admin() if skyuser else False
    actor_id = query.from_user.id if query.from_user else None
    actor_username = query.from_user.username if query.from_user else None

    if not admin:
        text = skyuser.admin_denied_text() if skyuser else "You are not admin."
        await query.answer(text, show_alert=True)
        return False

    if not isinstance(query.message, Message):
        await query.answer("Message is not accessible", show_alert=True)
        return False
    if callback_data.good:
        chat = await bot.get_chat(callback_data.chat_id)
        await bot.forward_message(callback_data.chat_id, query.message.chat.id, callback_data.new_message_id)
        permissions = chat.permissions or ChatPermissions(can_send_messages=True)
        _log_moderation_action(
            action="restrict",
            actor_id=actor_id,
            actor_username=actor_username,
            target_user_id=callback_data.user_id,
            chat_id=callback_data.chat_id,
            source_handler="routers.last_handler.cq_spam_check",
            result="started",
        )
        try:
            await bot.restrict_chat_member(
                chat_id=callback_data.chat_id,
                user_id=callback_data.user_id,
                permissions=permissions,
            )
        except TelegramBadRequest:
            _log_moderation_action(
                action="restrict",
                actor_id=actor_id,
                actor_username=actor_username,
                target_user_id=callback_data.user_id,
                chat_id=callback_data.chat_id,
                source_handler="routers.last_handler.cq_spam_check",
                result="failed",
            )
            raise
        _log_moderation_action(
            action="restrict",
            actor_id=actor_id,
            actor_username=actor_username,
            target_user_id=callback_data.user_id,
            chat_id=callback_data.chat_id,
            source_handler="routers.last_handler.cq_spam_check",
            result="success",
        )
        await query.answer("Oops, bringing the message back!", show_alert=True)
        await _get_db_service(app_context).save_bot_user(callback_data.user_id, None, 1)
        await query.message.edit_reply_markup(
            reply_markup=get_named_reply_markup(f"✅ Restored {query.from_user.username}")
        )
    else:
        await _get_db_service(app_context).save_bot_user(callback_data.user_id, None, 2)
        await query.answer("Banned !")
        await query.message.edit_reply_markup(
            reply_markup=get_named_reply_markup(f"✅ Banned {query.from_user.username}")
        )
        _log_moderation_action(
            action="ban",
            actor_id=actor_id,
            actor_username=actor_username,
            target_user_id=callback_data.user_id,
            chat_id=callback_data.chat_id,
            source_handler="routers.last_handler.cq_spam_check",
            result="started",
        )
        try:
            await bot.ban_chat_member(chat_id=callback_data.chat_id, user_id=callback_data.user_id)
        except TelegramBadRequest:
            _log_moderation_action(
                action="ban",
                actor_id=actor_id,
                actor_username=actor_username,
                target_user_id=callback_data.user_id,
                chat_id=callback_data.chat_id,
                source_handler="routers.last_handler.cq_spam_check",
                result="failed",
            )
        else:
            _log_moderation_action(
                action="ban",
                actor_id=actor_id,
                actor_username=actor_username,
                target_user_id=callback_data.user_id,
                chat_id=callback_data.chat_id,
                source_handler="routers.last_handler.cq_spam_check",
                result="success",
            )


@router.callback_query(ReplyCallbackData.filter())
async def cq_reply_ban(
    query: CallbackQuery, callback_data: ReplyCallbackData, bot: Bot, app_context=None, skyuser: SkyUser | None = None
):
    admin = await skyuser.is_admin(callback_data.chat_id) if skyuser else False
    actor_id = query.from_user.id if query.from_user else None
    actor_username = query.from_user.username if query.from_user else None

    if not admin:
        text = (
            skyuser.admin_denied_text("Вы не являетесь администратором в том чате.")
            if skyuser
            else "Вы не являетесь администратором в том чате."
        )
        await query.answer(text, show_alert=True)
        return

    if not isinstance(query.message, Message):
        await query.answer("Message is not accessible", show_alert=True)
        return

    _log_moderation_action(
        action="ban",
        actor_id=actor_id,
        actor_username=actor_username,
        target_user_id=callback_data.user_id,
        chat_id=callback_data.chat_id,
        source_handler="routers.last_handler.cq_reply_ban",
        result="started",
    )
    try:
        await bot.ban_chat_member(chat_id=callback_data.chat_id, user_id=callback_data.user_id)
    except TelegramBadRequest:
        _log_moderation_action(
            action="ban",
            actor_id=actor_id,
            actor_username=actor_username,
            target_user_id=callback_data.user_id,
            chat_id=callback_data.chat_id,
            source_handler="routers.last_handler.cq_reply_ban",
            result="failed",
        )
    else:
        _log_moderation_action(
            action="ban",
            actor_id=actor_id,
            actor_username=actor_username,
            target_user_id=callback_data.user_id,
            chat_id=callback_data.chat_id,
            source_handler="routers.last_handler.cq_reply_ban",
            result="success",
        )

    with suppress(TelegramBadRequest):
        await bot.delete_message(chat_id=callback_data.chat_id, message_id=callback_data.message_id)

    with suppress(TelegramBadRequest):
        await query.message.delete()

    await query.answer("Пользователь забанен и сообщения удалены.", show_alert=True)


@router.callback_query(F.data == "👀")
async def cq_look(query: CallbackQuery):
    await query.answer("👀", show_alert=True)


@router.callback_query(FirstMessageCallbackData.filter())
async def cq_first_vote_check(
    query: CallbackQuery,
    callback_data: FirstMessageCallbackData,
    bot: Bot,
    session: Any,
    app_context=None,
    skyuser: SkyUser | None = None,
):
    actor_id = query.from_user.id if query.from_user else None
    actor_username = query.from_user.username if query.from_user else None
    if not isinstance(query.message, Message):
        await query.answer("Message is not accessible", show_alert=True)
        return False
    if query.from_user.id == callback_data.user_id:
        await query.answer("You can't vote", show_alert=True)
        return False

    key = f"{callback_data.message_id}{query.message.chat.id}"
    default_vote_data = {"spam": 0, "good": 0, "users": [], "spam_users_mentions": [], "good_users_mentions": []}
    data = _get_first_vote_data(app_context, key, default_vote_data)

    if query.from_user.id in data["users"]:
        await query.answer("You have already voted.", show_alert=True)
        return False

    # Определяем вес голоса: 5 для администраторов, 1 для остальных
    admin = await skyuser.is_admin() if skyuser else False

    vote_weight = 5 if admin else 1
    username_link = get_username_link(query.from_user)

    # Добавляем пользователя в общий список
    data["users"].append(query.from_user.id)

    if callback_data.spam:
        data["spam"] += vote_weight
        data["spam_users_mentions"].append(username_link)
    else:
        data["good"] += vote_weight
        data["good_users_mentions"].append(username_link)

    _set_first_vote_data(app_context, key, data)

    # Проверяем, достиг ли счет 5 для спама
    if data["spam"] >= 5:
        # Удаляем сообщение голосования и сообщение о котором голосование
        with suppress(TelegramBadRequest):
            await bot.delete_message(query.message.chat.id, callback_data.message_id)
        with suppress(TelegramBadRequest):
            await query.message.forward(MTLChats.SpamGroup)
        with suppress(TelegramBadRequest):
            await bot.delete_message(query.message.chat.id, query.message.message_id)

        # Рестрикт для пользователя
        _log_moderation_action(
            action="restrict",
            actor_id=actor_id,
            actor_username=actor_username,
            target_user_id=callback_data.user_id,
            chat_id=query.message.chat.id,
            source_handler="routers.last_handler.cq_first_vote_check",
            result="started",
        )
        try:
            await query.message.chat.restrict(
                callback_data.user_id,
                permissions=ChatPermissions(
                    can_send_messages=False, can_send_media_messages=False, can_send_other_messages=False
                ),
            )
        except TelegramBadRequest:
            _log_moderation_action(
                action="restrict",
                actor_id=actor_id,
                actor_username=actor_username,
                target_user_id=callback_data.user_id,
                chat_id=query.message.chat.id,
                source_handler="routers.last_handler.cq_first_vote_check",
                result="failed",
            )
        else:
            _log_moderation_action(
                action="restrict",
                actor_id=actor_id,
                actor_username=actor_username,
                target_user_id=callback_data.user_id,
                chat_id=query.message.chat.id,
                source_handler="routers.last_handler.cq_first_vote_check",
                result="success",
            )
        await _get_db_service(app_context).save_bot_user(callback_data.user_id, None, 2)
        await query.answer("Message marked as spam and user restricted.", show_alert=True)
        return None

    if data["good"] >= 5:
        with suppress(TelegramBadRequest):
            await query.message.forward(MTLChats.SpamGroup)
        with suppress(TelegramBadRequest):
            await bot.delete_message(query.message.chat.id, query.message.message_id)
        await query.answer("Message marked as good.", show_alert=True)
        return None

    kb_reply = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Spam ({data['spam']})",
                    callback_data=FirstMessageCallbackData(
                        spam=True, message_id=callback_data.message_id, user_id=callback_data.user_id
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=f"Good ({data['good']})",
                    callback_data=FirstMessageCallbackData(
                        spam=False, message_id=callback_data.message_id, user_id=callback_data.user_id
                    ).pack(),
                ),
            ]
        ]
    )

    # Редактируем сообщение с новыми кнопками
    spam_list = "\n".join(data.get("spam_users_mentions", []))
    good_list = "\n".join(data.get("good_users_mentions", []))
    text = (
        "Please help me detect spam messages\n"
        f"\n*Spam votes ({data['spam']}):*\n{spam_list if spam_list else 'None'}"
        f"\n\n*Good votes ({data['good']}):*\n{good_list if good_list else 'None'}"
    )

    await bot.edit_message_text(
        chat_id=query.message.chat.id,
        message_id=query.message.message_id,
        text=text,
        parse_mode="HTML",
        reply_markup=kb_reply,
    )
    await query.answer("Your vote has been counted.", show_alert=True)
    return None


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router last_handler was loaded")


cast(Any, register_handlers).priority = 99
