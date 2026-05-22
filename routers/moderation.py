from contextlib import suppress
from typing import Any, cast

from aiogram import Router, Bot, html
from sqlalchemy.orm import Session
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from other.constants import MTLChats
from services.command_registry_service import update_command_info
from services.app_context import AppContext
from services.skyuser import SkyUser
from shared.domain.user import SpamStatus

router = Router()


class UnbanCallbackData(CallbackData, prefix="unban"):
    user_id: int
    chat_id: int


@router.message(Command(commands=["ban", "sban"]))
async def cmd_ban(message: Message, session: Session, bot: Bot, app_context: AppContext, skyuser: SkyUser):
    if (
        not app_context
        or not app_context.utils_service
        or not app_context.feature_flags
        or not app_context.moderation_service
    ):
        raise ValueError("app_context with utils_service, feature_flags, and moderation_service required")
    utils_service = cast(Any, app_context.utils_service)
    feature_flags = cast(Any, app_context.feature_flags)
    moderation_service = cast(Any, app_context.moderation_service)
    skynet_admin = skyuser.is_skynet_admin()
    command_text = message.text or ""
    actor_username = message.from_user.username if message.from_user and message.from_user.username else "unknown"
    reply_message = message.reply_to_message if isinstance(message.reply_to_message, Message) else None

    admin = await skyuser.is_admin()

    if not (skynet_admin or (admin and reply_message)):
        await message.reply(skyuser.admin_denied_text("You are not my admin."))
        return False

    with suppress(TelegramBadRequest):
        if reply_message:
            if not reply_message.from_user:
                await message.reply("Cannot detect user in replied message.")
                return
            user_id = reply_message.from_user.id

            await utils_service.sleep_and_delete(reply_message, 5)

            msg = await reply_message.forward(chat_id=MTLChats.SpamGroup)
            spam_check = feature_flags.is_enabled(message.chat.id, "no_first_link")
            chat_title = message.chat.title or str(message.chat.id)
            chat_link = message.get_url()
            chat_url = html.link(chat_title, chat_link) if chat_link else chat_title
            await msg.reply(f"Was banned by {actor_username} in {chat_url} chat.\nSpam check: {spam_check}")
        elif len(command_text.split()) > 1 and skynet_admin:
            try:
                user_id = await moderation_service.get_user_id(session, command_text.split()[1])
            except ValueError as e:
                await message.reply(str(e))
                return
        else:
            await message.reply("You need to specify user ID or @username and be skynet admin.")
            return

        await moderation_service.ban_user(session, message.chat.id, user_id, bot)
        logger.info(
            "moderation_artifact action=ban chat_id={} user_id={} actor_id={}",
            message.chat.id,
            user_id,
            message.from_user.id if message.from_user else "unknown",
        )

        msg = await message.answer(f"User (ID: {user_id}) has been banned.")
        if reply_message is None:
            await bot.send_message(
                chat_id=MTLChats.SpamGroup,
                text=f"User (ID: {user_id}) has been banned by {actor_username} in {message.chat.title} chat.",
            )

        # If the command is sban, delete the messages quickly
        tm = 2 if command_text.startswith("/sban") else 10

        await utils_service.sleep_and_delete(message, tm)
        await utils_service.sleep_and_delete(msg, tm)


@router.message(Command(commands=["unban"]))
async def cmd_unban(message: Message, session: Session, bot: Bot, app_context: AppContext, skyuser: SkyUser):
    if not app_context or not app_context.moderation_service:
        raise ValueError("app_context with moderation_service required")
    moderation_service = cast(Any, app_context.moderation_service)
    command_text = message.text or ""
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False

    if len(command_text.split()) > 1:
        try:
            param = command_text.split()[1]
            if param.isdigit() or (param.startswith("-") and param[1:].isdigit()):
                user_id = int(param)
            else:
                user_id = await moderation_service.get_user_id(session, param)
        except ValueError as e:
            await message.reply(str(e))
            return

        await moderation_service.unban_user(session, message.chat.id, user_id, bot)
        logger.info(
            "moderation_artifact action=unban chat_id={} user_id={} actor_id={}",
            message.chat.id,
            user_id,
            message.from_user.id if message.from_user else "unknown",
        )
        await bot.send_message(
            chat_id=MTLChats.SpamGroup,
            text=(
                f"User (ID: {user_id}) has been unbanned by "
                f"{message.from_user.username if message.from_user and message.from_user.username else 'unknown'} "
                f"in {message.chat.title} chat."
            ),
        )

        await message.reply(f"User (ID: {user_id}) has been unbanned.")
    else:
        await message.reply("You need to specify user ID or @username.")


@update_command_info("/test_id", "Узнать статус ID в списке заблокированных\nПример: /test_id id или /test_id -100id")
@router.message(Command(commands=["test_id"]))
async def cmd_test_id(message: Message, session: Session, bot: Bot, app_context: AppContext, skyuser: SkyUser):
    if not app_context or not app_context.moderation_service:
        raise ValueError("app_context with moderation_service required")
    moderation_service = cast(Any, app_context.moderation_service)
    command_text = message.text or ""
    if len(command_text.split()) > 1:
        param = command_text.split()[1]
        try:
            if param.isdigit() or (param.startswith("-") and param[1:].isdigit()):
                user_id = int(param)
            else:
                user_id = await moderation_service.get_user_id(session, param)
        except ValueError as e:
            await message.reply(str(e))
            return
    else:
        sender_id = message.from_user.id if message.from_user else skyuser.sender_chat_id
        user_id = skyuser.sender_chat_id if sender_id == MTLChats.Channel_Bot else sender_id

    user_status = await moderation_service.check_user_status(session, user_id)

    if user_status == SpamStatus.NEW:
        message_text = "New User"
    elif user_status == SpamStatus.GOOD:
        message_text = "Good User"
    elif user_status == SpamStatus.BAD:
        message_text = "Bad User"
    else:
        message_text = f"unknown status {user_status}"

    await message.reply(f"User ID: {user_id}, Type: {message_text}")


@router.callback_query(UnbanCallbackData.filter())
async def cmd_q_unban(
    call: CallbackQuery,
    session: Session,
    bot: Bot,
    callback_data: UnbanCallbackData,
    app_context: AppContext,
    skyuser: SkyUser,
):
    if not app_context or not app_context.moderation_service:
        raise ValueError("app_context with moderation_service required")
    moderation_service = cast(Any, app_context.moderation_service)
    if not skyuser.is_skynet_admin():
        await call.answer("You are not my admin.", show_alert=True)
        return False

    await moderation_service.unban_user(session, callback_data.chat_id, callback_data.user_id, bot)
    logger.info(
        "moderation_artifact action=unban_callback chat_id={} user_id={} actor_id={}",
        callback_data.chat_id,
        callback_data.user_id,
        call.from_user.id if call.from_user else "unknown",
    )
    await bot.send_message(
        chat_id=MTLChats.SpamGroup,
        text=(
            f"User (ID: {callback_data.user_id}) has been unbanned via callback by "
            f"{call.from_user.username if call.from_user and call.from_user.username else 'unknown'} "
            f"in chat_id={callback_data.chat_id}."
        ),
    )

    await call.answer("User unbanned successfully.")
    if isinstance(call.message, Message):
        actor_label = (
            f"@{call.from_user.username}"
            if call.from_user and call.from_user.username
            else call.from_user.full_name
            if call.from_user and call.from_user.full_name
            else "done"
        )
        await call.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=actor_label, callback_data="👀")]]
            )
        )


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router moderation was loaded")
