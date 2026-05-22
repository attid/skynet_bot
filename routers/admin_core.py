import html
import json
import csv
import io
from contextlib import suppress
from datetime import datetime
from datetime import timedelta
from typing import Any, cast

import aiohttp
from aiogram import Router, Bot, F
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    ChatPermissions,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    MessageOriginUser,
    MessageReactionUpdated,
    ReactionTypeCustomEmoji,
    BufferedInputFile,
)
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.update_report import update_top_holders_report
from other.aiogram_tools import ChatInOption, get_username_link
from other.config_reader import config
from other.constants import MTLChats, BotValueTypes
from services.command_registry_service import update_command_info
from routers.multi_handler import run_entry_channel_check
from other.timedelta import parse_timedelta_from_message
from services.app_context import AppContext
from services.skyuser import SkyUser

router = Router()


def _has_topic_admins(chat_id: int, thread_id: int, app_context) -> bool:
    """Check if topic has admins configured using DI service."""
    chat_thread_key = f"{chat_id}-{thread_id}"

    if not app_context or not app_context.admin_service:
        raise ValueError("app_context with admin_service required")
    admin_service = cast(Any, app_context.admin_service)
    return admin_service.has_topic_admins_by_key(chat_thread_key)


def _extract_mention_username(message: Message) -> str | None:
    """Extract @username from message entities (mention type).

    Returns the username string including @ prefix, or None if no mention found.
    """
    if not message.entities or not message.text:
        return None
    for entity in message.entities:
        if entity.type == "mention":
            return entity.extract_from(message.text)
    return None


async def _resolve_mute_target(message: Message, app_context: AppContext) -> tuple[int, str] | None:
    """Resolve mute/unmute target user. Priority: mention > reply.

    Returns (user_id, display_name) or None if no target found.
    """
    # 1. Try mention (@username in message text)
    mention = _extract_mention_username(message)
    if mention:
        try:
            if not app_context or not app_context.db_service:
                raise ValueError("app_context with db_service required")
            user_id = await app_context.db_service.get_user_id(mention)
            return user_id, mention
        except ValueError:
            return None

    # 2. Fallback to reply
    reply = message.reply_to_message
    if reply and not reply.forum_topic_created:
        if reply.sender_chat:
            return reply.sender_chat.id, f"Channel {reply.sender_chat.title}"
        if reply.from_user:
            return reply.from_user.id, get_username_link(reply.from_user)

    return None


async def _reply_and_cleanup(message: Message, utils_service: Any, text: str, seconds: int = 5) -> None:
    """Send a short-lived reply and schedule command cleanup."""
    info_message = await message.reply(text)
    await utils_service.sleep_and_delete(info_message, seconds)
    await utils_service.sleep_and_delete(message, seconds)


async def _safe_send_chat_status_message(bot: Bot, chat_id: int, text: str) -> None:
    """Best-effort chat status notification that must not break my_chat_member flow."""
    try:
        await bot.send_message(chat_id, text)
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.warning(f"Failed to send chat status message to {chat_id}: {exc}")


def _describe_reply_sender(reply: Message) -> str:
    """Build a short HTML-safe sender description for moderation logs."""
    if reply.sender_chat:
        title = html.escape(reply.sender_chat.title or str(reply.sender_chat.id))
        return f"channel {title}"
    if reply.from_user:
        return get_username_link(reply.from_user)
    return "unknown sender"


def _describe_cached_sender(message_context: dict[str, Any]) -> str:
    sender_chat_title = message_context.get("sender_chat_title")
    if sender_chat_title:
        return f"channel {html.escape(sender_chat_title)}"

    user_id = message_context.get("user_id")
    username = message_context.get("username")
    full_name = message_context.get("full_name") or username or str(user_id or "unknown user")
    if username:
        return f"@{html.escape(username)}"
    if user_id is not None:
        return f'<a href="tg://user?id={user_id}">{html.escape(full_name)}</a>'
    return "unknown sender"


async def _send_topic_message(bot: Bot, chat_id: int, thread_id: int, text: str) -> None:
    await bot.send_message(chat_id=chat_id, text=text, message_thread_id=thread_id, parse_mode=ParseMode.HTML)


async def _log_and_delete_target(
    bot: Bot,
    chat_id: int,
    thread_id: int,
    target_message_id: int,
    actor: str,
    target_sender: str,
    chat_title: str,
) -> None:
    await bot.forward_message(chat_id=MTLChats.SpamGroup, from_chat_id=chat_id, message_id=target_message_id)
    await bot.send_message(
        chat_id=MTLChats.SpamGroup,
        text=f"Message from {target_sender} deleted by {actor} in {chat_title} topic {thread_id}.",
        parse_mode=ParseMode.HTML,
    )
    await bot.delete_message(chat_id=chat_id, message_id=target_message_id)


@router.message(F.text.startswith("!ro"))
async def cmd_set_ro(message: Message, skyuser: SkyUser):
    if not await skyuser.is_admin():
        await message.reply(skyuser.admin_denied_text())
        return False

    if message.reply_to_message is None and message.external_reply is None:
        await message.reply("Please send for reply message to set ro")
        return

    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif message.external_reply and isinstance(message.external_reply.origin, MessageOriginUser):
        target_user = message.external_reply.origin.sender_user
    else:
        target_user = None

    if not target_user:
        await message.reply("Please reply to a user message.")
        return
    delta = await parse_timedelta_from_message(message)
    if not delta:
        await message.reply("Unable to parse duration.")
        return
    try:
        await message.chat.restrict(
            target_user.id,
            permissions=ChatPermissions(
                can_send_messages=False, can_send_media_messages=False, can_send_other_messages=False
            ),
            until_date=delta,
        )
    except TelegramBadRequest as e:
        await message.reply(f"Failed to restrict user: {e.message}")
        return

    user = target_user.username if target_user.username else target_user.full_name
    await message.reply(f"{user} was set ro for {delta}")


@router.message(Command(commands=["topic"]))
async def cmd_create_topic(message: Message, skyuser: SkyUser):
    if not await skyuser.is_admin():
        await message.reply(skyuser.admin_denied_text("You are not an admin."))
        return

    if not message.chat.is_forum:
        await message.reply("Topics are not enabled in this chat.")
        return

    command_parts = (message.text or "").split(maxsplit=2)
    if len(command_parts) != 3:
        await message.reply("Incorrect command format. Use: /topic 🔵 Topic Name")
        return

    emoji, topic_name = command_parts[1], command_parts[2]

    try:
        if not message.bot:
            await message.reply("Bot is not available for this message.")
            return
        new_topic = await message.bot.create_forum_topic(
            name=topic_name, icon_custom_emoji_id=emoji, chat_id=message.chat.id
        )
        await message.reply(f"New topic '{topic_name}' created successfully with ID: {new_topic.message_thread_id}")
    except TelegramBadRequest as e:
        if "CHAT_NOT_MODIFIED" in str(e):
            await message.reply("Failed to create topic. Make sure the emoji is valid and the topic name is unique.")
        else:
            await message.reply(f"An error occurred while creating the topic: {str(e)}")


@update_command_info("/all", "тегнуть всех пользователей. работает зависимо от чата. и только в рабочих чатах")
@router.message(Command(commands=["all"]))
async def cmd_all(message: Message, app_context: AppContext):
    if not app_context or not app_context.group_service:
        raise ValueError("app_context with group_service required")
    group_service = cast(Any, app_context.group_service)
    user_list = await group_service.get_members(message.chat.id)
    members = []
    for user in user_list:
        if user.is_bot:
            continue
        if user.username:
            members.append(f"@{user.username}")
        else:
            full_name = html.unescape(user.full_name)
            members.append(f'<a href="tg://user?id={user.user_id}">{full_name}</a>')
    text = " ".join(members)
    logger.info(text)
    await message.reply(text, parse_mode=ParseMode.HTML)


@update_command_info("/check_entry_channel", "Запустить проверку всех участников на подписку в обязательный канал.")
@router.message(Command(commands=["check_entry_channel"]))
async def cmd_check_entry_channel(message: Message, bot: Bot, app_context: AppContext, skyuser: SkyUser):
    if not app_context or not app_context.group_service or not app_context.utils_service:
        raise ValueError("app_context with group_service and utils_service required")
    utils_service = cast(Any, app_context.utils_service)
    if not await skyuser.is_admin():
        await message.reply(skyuser.admin_denied_text())
        return

    try:
        checked_count, action_count = await run_entry_channel_check(bot, message.chat.id, app_context=app_context)
    except ValueError:
        info_message = await message.reply("Настройка обязательного канала не включена в этом чате.")
        await utils_service.sleep_and_delete(info_message, 10)
        await utils_service.sleep_and_delete(message, 10)
        return

    info_message = await message.reply(f"Проверено участников: {checked_count}. Применено ограничений: {action_count}.")
    await utils_service.sleep_and_delete(info_message, 30)
    await utils_service.sleep_and_delete(message, 30)


@router.message(Command(commands=["delete_dead_members"]))
async def cmd_delete_dead_members(message: Message, state: FSMContext, app_context: AppContext, skyuser: SkyUser):
    if not app_context or not app_context.group_service:
        raise ValueError("app_context with group_service required")
    if not await skyuser.is_admin():
        await message.reply(skyuser.admin_denied_text())
        return

    group_service = cast(Any, app_context.group_service)
    parts = (message.text or "").split()

    if len(parts) != 2:
        await message.reply(
            "Please provide a chat ID or username. "
            "Usage: /delete_dead_members -100xxxxxxxxx"
            "or /delete_dead_members @username"
        )
        return

    chat_id = parts[1]

    if not ((chat_id.startswith("-100") and chat_id[4:].isdigit()) or chat_id.startswith("@")):
        await message.reply(
            "Invalid chat ID format. It should start with -100 followed by numbers or @ followed by the channel username."
        )
        return

    if chat_id.startswith("@"):
        try:
            if not message.bot:
                await message.reply("Bot is not available for this message.")
                return
            chat = await message.bot.get_chat(chat_id)
            chat_id = chat.id
        except TelegramBadRequest:
            await message.reply("Unable to find the chat. Make sure the bot is a member of the channel/group.")
            return
    else:
        chat_id = int(chat_id)

    if not await skyuser.is_admin(chat_id=chat_id):
        await message.reply(skyuser.admin_denied_text(f"You are not an admin of the chat {chat_id}."))
        return

    await message.reply("Starting to remove deleted users. This may take some time...")
    try:
        count = await group_service.remove_deleted_users(chat_id)
        await message.reply(f"Finished removing deleted users. \n Total deleted users: {count}")
    except Exception as e:
        logger.error(f"Error in cmd_delete_dead_members: {e}")
        await message.reply(f"An error occurred while removing deleted users: {str(e)}")


@update_command_info("/mute", "Блокирует пользователя в текущей ветке (reply или @username)")
@router.message(ChatInOption("moderate"), Command(commands=["mute"]))
async def cmd_mute(message: Message, app_context: AppContext, skyuser: SkyUser):
    if not app_context or not app_context.admin_service or not app_context.db_service:
        raise ValueError("app_context with admin_service and db_service required")
    admin_service = cast(Any, app_context.admin_service)
    db_service = cast(Any, app_context.db_service)
    if message.message_thread_id is None:
        await message.reply("This command must be used in topic.")
        return False
    thread_id = message.message_thread_id
    chat_thread_key = f"{message.chat.id}-{message.message_thread_id}"

    if not _has_topic_admins(message.chat.id, thread_id, app_context):
        await message.reply("Local admins not set yet")
        return False

    if not skyuser.is_topic_admin(message.chat.id, thread_id):
        await message.reply("You are not local admin")
        return False

    # Resolve target: mention > reply
    target = await _resolve_mute_target(message, app_context)
    if target is None:
        await message.reply("Specify user by reply or @username")
        return
    user_id, user = target

    delta = await parse_timedelta_from_message(message)
    if not delta:
        await message.reply("Unable to parse mute duration")
        return
    end_time_str = (datetime.now() + delta).isoformat()

    # Use DI service
    admin_service.set_user_mute_by_key(chat_thread_key, user_id, end_time_str, user)
    all_mutes = admin_service.get_all_topic_mutes()
    await db_service.save_bot_value(0, BotValueTypes.TopicMutes, json.dumps(all_mutes))

    await message.reply(f"{user} was set mute for {delta} in topic {chat_thread_key}")


@update_command_info("/unmute", "Снимает мьют пользователя в текущей ветке (reply или @username)")
@router.message(ChatInOption("moderate"), Command(commands=["unmute"]))
async def cmd_unmute(message: Message, app_context: AppContext, skyuser: SkyUser):
    if not app_context or not app_context.admin_service or not app_context.db_service:
        raise ValueError("app_context with admin_service and db_service required")
    admin_service = cast(Any, app_context.admin_service)
    db_service = cast(Any, app_context.db_service)
    if message.message_thread_id is None:
        await message.reply("This command must be used in topic.")
        return False
    thread_id = message.message_thread_id
    chat_thread_key = f"{message.chat.id}-{message.message_thread_id}"

    if not _has_topic_admins(message.chat.id, thread_id, app_context):
        await message.reply("Local admins not set yet")
        return False

    if not skyuser.is_topic_admin(message.chat.id, thread_id):
        await message.reply("You are not local admin")
        return False

    # Resolve target: mention > reply
    target = await _resolve_mute_target(message, app_context)
    if target is None:
        await message.reply("Specify user by reply or @username")
        return
    user_id, user = target

    # Check if user is actually muted
    topic_mutes = admin_service.get_topic_mutes_by_key(chat_thread_key)
    if not topic_mutes or user_id not in topic_mutes:
        await message.reply(f"{user} is not muted in this topic")
        return

    admin_service.remove_user_mute_by_key(chat_thread_key, user_id)
    all_mutes = admin_service.get_all_topic_mutes()
    await db_service.save_bot_value(0, BotValueTypes.TopicMutes, json.dumps(all_mutes))

    await message.reply(f"{user} was unmuted in topic {chat_thread_key}")


@update_command_info("/show_mute", "Показывает пользователей, которые заблокированы в текущей ветке")
@router.message(ChatInOption("moderate"), Command(commands=["show_mute"]))
async def cmd_show_mutes(message: Message, app_context: AppContext, skyuser: SkyUser):
    if not app_context or not app_context.admin_service or not app_context.db_service:
        raise ValueError("app_context with admin_service and db_service required")
    admin_service = cast(Any, app_context.admin_service)
    db_service = cast(Any, app_context.db_service)
    if message.message_thread_id is None:
        await message.reply("This command must be used in topic.")
        return False
    thread_id = message.message_thread_id
    chat_thread_key = f"{message.chat.id}-{message.message_thread_id}"

    if not _has_topic_admins(message.chat.id, thread_id, app_context):
        await message.reply("Local admins not set yet")
        return False

    if not skyuser.is_topic_admin(message.chat.id, thread_id):
        await message.reply("You are not local admin")
        return False

    # Get mutes using DI service
    topic_mutes = admin_service.get_topic_mutes_by_key(chat_thread_key)

    if not topic_mutes:
        await message.reply("No users are currently muted in this topic")
        return

    current_time = datetime.now()
    muted_users = []
    users_to_remove = []

    mute_items = list(topic_mutes.items())

    for user_id, mute_info in mute_items:
        try:
            end_time = datetime.fromisoformat(mute_info["end_time"])
            if end_time > current_time:
                remaining_time = end_time - current_time
                muted_users.append(f"{mute_info['user']} - {remaining_time}")
            else:
                users_to_remove.append(user_id)
        except (ValueError, KeyError):
            continue

    # Remove expired mutes
    if users_to_remove:
        for user_id in users_to_remove:
            admin_service.remove_user_mute_by_key(chat_thread_key, user_id)
        all_mutes = admin_service.get_all_topic_mutes()
        await db_service.save_bot_value(0, BotValueTypes.TopicMutes, json.dumps(all_mutes))

    if muted_users:
        mute_list = "\n".join(muted_users)
        await message.reply(f"Currently muted users in this topic:\n{mute_list}")
    else:
        await message.reply("No users are currently muted in this topic")


@update_command_info("/del", "Удаляет сообщение в текущей ветке по reply")
@router.message(ChatInOption("moderate"), Command(commands=["del"]))
async def cmd_del_message(message: Message, bot: Bot, app_context: AppContext, skyuser: SkyUser):
    if not app_context or not app_context.admin_service or not app_context.utils_service:
        raise ValueError("app_context with admin_service and utils_service required")
    utils_service = cast(Any, app_context.utils_service)

    if message.message_thread_id is None:
        await _reply_and_cleanup(message, utils_service, "This command must be used in topic.")
        return False

    thread_id = message.message_thread_id
    if not _has_topic_admins(message.chat.id, thread_id, app_context):
        await _reply_and_cleanup(message, utils_service, "Local admins not set yet")
        return False

    if not skyuser.is_topic_admin(message.chat.id, thread_id):
        await _reply_and_cleanup(message, utils_service, "You are not local admin")
        return False

    reply = message.reply_to_message
    if reply is None or reply.forum_topic_created:
        await _reply_and_cleanup(message, utils_service, "Please send for reply message to delete")
        return False

    actor = get_username_link(message.from_user) if message.from_user else "unknown actor"
    chat_title = html.escape(message.chat.title or str(message.chat.id))
    target_sender = _describe_reply_sender(reply)

    try:
        await _log_and_delete_target(
            bot=bot,
            chat_id=reply.chat.id,
            thread_id=thread_id,
            target_message_id=reply.message_id,
            actor=actor,
            target_sender=target_sender,
            chat_title=chat_title,
        )
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.warning(
            "cmd_del_message failed chat_id={} thread_id={} target_message_id={} error={}",
            message.chat.id,
            thread_id,
            reply.message_id,
            exc,
        )
        await _reply_and_cleanup(message, utils_service, "Unable to delete this message")
        return False

    await utils_service.sleep_and_delete(message, 5)
    return True


@router.message_reaction(ChatInOption("moderate"))
async def message_reaction(
    message: MessageReactionUpdated,
    bot: Bot,
    session: Any = None,
    app_context: AppContext | None = None,
    skyuser: SkyUser | None = None,
):
    if (
        not app_context
        or not app_context.admin_service
        or not app_context.message_thread_cache_service
        or not app_context.db_service
    ):
        raise ValueError("app_context with admin_service, message_thread_cache_service, and db_service required")
    admin_service = cast(Any, app_context.admin_service)
    message_thread_cache_service = cast(Any, app_context.message_thread_cache_service)
    db_service = cast(Any, app_context.db_service)
    message_any = cast(Any, message)
    if skyuser is None:
        user = message_any.user if hasattr(message_any, "user") else None
        skyuser = SkyUser(
            user_id=user.id if user else None,
            username=user.username if user else None,
            chat_id=message_any.chat.id if message_any.chat else None,
            sender_chat_id=None,
            bot=bot,
            app_context=app_context,
        )
    if message_any.new_reaction and isinstance(message_any.new_reaction[0], ReactionTypeCustomEmoji):
        reaction: ReactionTypeCustomEmoji = message_any.new_reaction[0]

        # 1. First, check if this emoji is a known moderation command
        is_delete_command = reaction.custom_emoji_id == "5220151067429335888"  # X emoji
        mute_deltas = {
            "5220090169088045319": timedelta(minutes=10),
            "5220223291599383581": timedelta(minutes=60),
            "5221946956464548565": timedelta(days=1),
        }
        delta = mute_deltas.get(reaction.custom_emoji_id)

        # If it's not a known command, ignore it immediately
        if not is_delete_command and delta is None:
            return False

        # 2. Since it's a moderation command, now we need to check context and permissions
        message_context = await message_thread_cache_service.get_message_context(
            message_any.chat.id, message_any.message_id
        )
        if not message_context:
            logger.debug(
                "message_reaction skipped: no cached message context chat_id={} message_id={}",
                message_any.chat.id,
                message_any.message_id,
            )
            return False

        thread_id = int(message_context["thread_id"])
        chat_thread_key = f"{message_any.chat.id}-{thread_id}"

        if not _has_topic_admins(message_any.chat.id, thread_id, app_context):
            await _send_topic_message(bot, message_any.chat.id, thread_id, "Local admins not set yet")
            return False

        if not skyuser.is_topic_admin(message_any.chat.id, thread_id):
            await _send_topic_message(bot, message_any.chat.id, thread_id, "You are not local admin")
            return False

        # 3. Execute the command
        if is_delete_command:
            actor = f"@{html.escape(skyuser.username)}" if skyuser.username else "unknown actor"
            chat_title = html.escape(message_any.chat.title or str(message_any.chat.id))
            target_sender = _describe_cached_sender(message_context)
            try:
                await _log_and_delete_target(
                    bot=bot,
                    chat_id=message_any.chat.id,
                    thread_id=thread_id,
                    target_message_id=message_any.message_id,
                    actor=actor,
                    target_sender=target_sender,
                    chat_title=chat_title,
                )
            except (TelegramBadRequest, TelegramForbiddenError) as exc:
                logger.warning(
                    "message_reaction delete failed chat_id={} thread_id={} target_message_id={} error={}",
                    message_any.chat.id,
                    thread_id,
                    message_any.message_id,
                    exc,
                )
            return True

        # Handle mute (delta is not None here — guarded by early return above)
        assert delta is not None
        user_id = message_context.get("user_id")
        if user_id is None:
            await _send_topic_message(bot, message_any.chat.id, thread_id, "Please react to a user message to set mute")
            return False

        user = _describe_cached_sender(message_context)
        end_time_str = (datetime.now() + delta).isoformat()

        admin_service.set_user_mute_by_key(chat_thread_key, user_id, end_time_str, user)
        all_mutes = admin_service.get_all_topic_mutes()
        await db_service.save_bot_value(0, BotValueTypes.TopicMutes, json.dumps(all_mutes))

        await _send_topic_message(
            bot, message_any.chat.id, thread_id, f"{user} was set mute for {delta} in topic {chat_thread_key}"
        )
        return True

    # new_reaction=[ReactionTypeCustomEmoji(type='custom_emoji', custom_emoji_id='5220151067429335888')]
    # 10m    "custom_emoji_id": "5220090169088045319"
    # 60m    "custom_emoji_id": "5220223291599383581"
    # 1D    "custom_emoji_id": "5221946956464548565"
    # X    "custom_emoji_id": "5220151067429335888"


@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated, bot: Bot):
    chat = update.chat
    old_status = update.old_chat_member.status
    new_status = update.new_chat_member.status

    if old_status != new_status:
        if new_status == ChatMemberStatus.MEMBER:
            logger.info(f"Bot was added to chat {chat.id}")
            if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                await _safe_send_chat_status_message(bot, chat.id, "Thanks for adding me to this chat!")

        elif new_status == ChatMemberStatus.LEFT:
            logger.info(f"Bot was removed from chat {chat.id}")

        elif new_status == ChatMemberStatus.ADMINISTRATOR:
            logger.info(f"Bot's permissions were updated in chat {chat.id}")
            if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                await _safe_send_chat_status_message(bot, chat.id, "Thanks for making me an admin!")

        elif new_status == ChatMemberStatus.RESTRICTED:
            logger.warning(f"Bot's permissions were restricted in chat {chat.id}")

        elif new_status == ChatMemberStatus.KICKED:
            logger.warning(f"Bot's permissions were kicked in chat {chat.id}")

        else:
            logger.info(f"Bot status changed in chat {chat.id} from {old_status} to {new_status}")
    # You can add more specific logic based on your needs

    # For example, you might want to update some global data:
    # if new_status == ChatMemberStatus.MEMBER or new_status == ChatMemberStatus.ADMINISTRATOR:
    #     if chat.id not in global_data.active_chats:
    #         global_data.active_chats.append(chat.id)
    # elif new_status == ChatMemberStatus.LEFT:
    #     if chat.id in global_data.active_chats:
    #         global_data.active_chats.remove(chat.id)


@router.message(F.migrate_to_chat_id)
async def on_migrate(message: Message, bot: Bot):
    old_chat_id = message.chat.id
    new_chat_id = message.migrate_to_chat_id
    if new_chat_id is None:
        return
    logger.info(f"Chat {old_chat_id} migrated to {new_chat_id}")
    await bot.send_message(chat_id=new_chat_id, text=f"Chat {old_chat_id} migrated to {new_chat_id}")


@router.message(Command(commands=["s"]))
@router.message(Command(commands=["send_me"]))
async def cmd_send_me(message: Message, bot: Bot, skyuser: SkyUser):
    if not await skyuser.is_admin():
        await message.reply(skyuser.admin_denied_text())
        return

    if message.reply_to_message is None:
        await message.reply("Please send for reply message to get it")
        return

    if not message.from_user:
        await message.reply("Cannot identify user.")
        return
    if message.reply_to_message:
        if message.reply_to_message.text or message.reply_to_message.caption:
            await bot.send_message(
                chat_id=message.from_user.id,
                text=message.reply_to_message.html_text or message.reply_to_message.caption or "",
            )

        if message.reply_to_message.photo:
            photo = message.reply_to_message.photo[-1]
            await bot.send_photo(
                chat_id=message.from_user.id, photo=photo.file_id, caption=message.reply_to_message.caption
            )

        elif message.reply_to_message.video:
            video = message.reply_to_message.video
            await bot.send_video(
                chat_id=message.from_user.id, video=video.file_id, caption=message.reply_to_message.caption
            )


@update_command_info(
    "/alert_me", "Делает подписку на упоминания и сообщает об упоминаниях в личку(alarm)", 3, "alert_me"
)
@router.message(Command(commands=["alert_me"]))
async def cmd_set_alert_me(message: Message, app_context: AppContext):
    if (
        not app_context
        or not app_context.notification_service
        or not app_context.utils_service
        or not app_context.db_service
    ):
        raise ValueError("app_context with notification_service, utils_service, and db_service required")
    if not message.from_user:
        await message.reply("Cannot identify user.")
        return
    notification_service = cast(Any, app_context.notification_service)
    utils_service = cast(Any, app_context.utils_service)
    db_service = cast(Any, app_context.db_service)
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Use DI service
    is_subscribed = notification_service.toggle_alert_user(chat_id, user_id)
    alert_users = notification_service.get_alert_users(chat_id)
    await db_service.save_bot_value(chat_id, BotValueTypes.AlertMe, json.dumps(alert_users))
    msg = await message.reply("Added" if is_subscribed else "Removed")

    await utils_service.sleep_and_delete(message, 60)
    await utils_service.sleep_and_delete(msg, 60)


@update_command_info("/calc", "Посчитать сообщения от ответного")
@router.message(Command(commands=["calc"]))
async def cmd_calc(message: Message):
    if not message.reply_to_message:
        await message.reply("This command must be used in reply to a message.")
        return

    current_message_id = message.message_id
    replied_message_id = message.reply_to_message.message_id
    difference = current_message_id - replied_message_id

    with suppress(TelegramBadRequest):
        await message.reply_to_message.reply(f"This message was {difference} messages ago.")
        await message.delete()


@update_command_info("/web_pin", "Делает пост который можно потом редактировать в WebApp")
@update_command_info(
    "/web_pin comment", "В личке делает пост который можно потом редактировать в WebApp по ссылке для пересылки"
)
@router.message(Command(commands=["web_pin"]))
async def cmd_web_pin(message: Message, command: CommandObject):
    text = command.args
    if not text:
        text = "new text"

    if message.chat.type == ChatType.PRIVATE:
        headers = {"Authorization": f"Bearer {config.eurmtl_key}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.get("https://eurmtl.me/remote/get_new_pin_id", headers=headers) as response:
                return_json = await response.json()
        message_uuid = return_json["uuid"]
        edit_button_url = f"https://t.me/myMTLbot/WebEditor?startapp=0_{message_uuid}"
        reply_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Edit", url=edit_button_url)]])
        await message.answer(text, reply_markup=reply_markup)
        return

    # else

    sent_message = await message.answer(text)

    # Получаем chat_id и message_id отправленного сообщения
    chat_id = message.chat.shifted_id
    message_id = sent_message.message_id

    # Формируем URL для кнопки с учетом chat_id и message_id
    edit_button_url = f"https://t.me/myMTLbot/WebEditor?startapp={chat_id}_{message_id}"

    # Создаем клавиатуру с кнопками
    reply_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Edit", url=edit_button_url),
                InlineKeyboardButton(text="Edit", url=edit_button_url),
            ]
        ]
    )

    # Обновляем сообщение, добавляя клавиатуру
    await sent_message.edit_reply_markup(reply_markup=reply_markup)


@update_command_info("/show_all_topic_admin", "Показать всех администраторов всех топиков")
@router.message(Command(commands=["show_all_topic_admin"]))
async def cmd_show_all_topic_admin(message: Message, app_context: AppContext, skyuser: SkyUser):
    if not app_context or not app_context.admin_service:
        raise ValueError("app_context with admin_service required")
    if not await skyuser.is_admin():
        await message.reply(skyuser.admin_denied_text("You are not an admin."))
        return

    chat_id = message.chat.id
    chat_admins = {}
    prefix = f"{chat_id}-"

    # Get topic admins using DI service
    admin_service = cast(Any, app_context.admin_service)
    all_topic_admins = admin_service.get_all_topic_admins()

    for key, admins in all_topic_admins.items():
        if key.startswith(prefix):
            try:
                topic_id = key[len(prefix) :]
                if topic_id not in chat_admins:
                    chat_admins[topic_id] = set()
                chat_admins[topic_id].update(admins)
            except Exception as e:
                logger.warning(f"Could not parse topic_admins key: {key}, error: {e}")
                continue

    if not chat_admins:
        await message.reply("No topic admins found for this chat.")
        return

    response_lines = ["<b>Topic Admins for this chat:</b>"]
    for topic_id, admins in chat_admins.items():
        chat_id_for_link = str(chat_id).replace("-100", "")
        topic_link = f"https://t.me/c/{chat_id_for_link}/{topic_id}"
        admin_list = " ".join(sorted(list(admins)))
        response_lines.append(f'<a href="{topic_link}">Topic {topic_id}</a>: {admin_list}')

    await message.reply("\n".join(response_lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@update_command_info("/get_users_csv", "Получить CSV файл со списком пользователей чата")
@router.message(Command(commands=["get_users_csv"]))
async def cmd_get_users_csv(message: Message, bot: Bot, app_context: AppContext):
    if not app_context or not app_context.group_service:
        raise ValueError("app_context with group_service required")
    group_service = cast(Any, app_context.group_service)
    if message.chat.id != MTLChats.MTLIDGroup:
        return

    command_parts = (message.text or "").split()
    if len(command_parts) != 2:
        await message.reply("Usage: /get_users_csv <chat_id>")
        return

    target_chat_id_str = command_parts[1]
    if not (target_chat_id_str.startswith("-100") and target_chat_id_str[1:].isdigit()):
        await message.reply("Invalid chat_id format. It must start with -100.")
        return

    target_chat_id = int(target_chat_id_str)

    try:
        bot_member = await bot.get_chat_member(target_chat_id, bot.id)
        if bot_member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await message.reply("I am not a member of the target chat.")
            return
    except TelegramBadRequest:
        await message.reply("I am not a member of the target chat, or the chat does not exist.")
        return
    except Exception as e:
        await message.reply(f"An error occurred while checking my membership: {e}")
        logger.error(f"Error checking bot membership: {e}")
        return

    try:
        if not message.from_user:
            await message.reply("Cannot identify user.")
            return
        user_member = await bot.get_chat_member(target_chat_id, message.from_user.id)
        if user_member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await message.reply("You are not a member of the target chat.")
            return
    except TelegramBadRequest:
        await message.reply("You are not a member of the target chat, or the chat does not exist.")
        return
    except Exception as e:
        await message.reply(f"An error occurred while checking your membership: {e}")
        logger.error(f"Error checking user membership: {e}")
        return

    await message.reply("Processing... This may take a while for large chats.")

    try:
        members = await group_service.get_members(target_chat_id)
    except Exception as e:
        await message.reply(f"Failed to get group members: {e}")
        logger.error(f"Failed to get group members for {target_chat_id}: {e}")
        return

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["user_id", "full_name", "username", "is_admin", "is_bot"])

    for member in members:
        writer.writerow([member.user_id, member.full_name, member.username or "", member.is_admin, member.is_bot])

    output.seek(0)

    csv_file = BufferedInputFile(output.getvalue().encode("utf-8"), filename=f"users_{target_chat_id}.csv")
    await message.reply_document(csv_file)


GD_LINK = "https://docs.google.com/spreadsheets/d/1HSgK_QvK4YmVGwFXuW5CmqgszDxe99FAS2btN3FlQsI/edit#gid=171831156"


@update_command_info("/update_top_holders", "Обновляет Top Holders Google Sheets")
@router.message(Command(commands=["update_top_holders"]))
async def cmd_update_top_holders(message: Message, session: AsyncSession, skyuser: SkyUser):
    if not await skyuser.is_admin():
        await message.reply(skyuser.admin_denied_text())
        return

    await message.reply("Обновляю Top Holders report...")
    try:
        await update_top_holders_report(session)
        await message.reply(f'Top Holders report обновлён.\n<a href="{GD_LINK}">MTL_TopHolders</a>')
    except Exception as e:
        logger.error(f"Error in cmd_update_top_holders: {e}")
        await message.reply(f"Ошибка: {e}")


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router admin_core was loaded")
