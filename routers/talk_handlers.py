from aiogram import F, Bot, Router
from aiogram.enums import ChatType, ParseMode, ChatAction
from aiogram.utils.text_decorations import html_decoration
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, URLInputFile
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, cast

from other.text_tools import extract_url
from middlewares.throttling import rate_limit
from other.aiogram_tools import HasText, has_words, StartText, ReplyToBot
from other.constants import MTLChats, BotValueTypes
from services.command_registry_service import update_command_info
from other.pyro_tools import extract_telegram_info, pyro_update_msg_info
from other.miniapps_tools import miniapps
from services.app_context import AppContext
from services.skyuser import SkyUser
from db.repositories import ConfigRepository

router = Router()

my_talk_message = []


def _is_skynet_img_user(username: str | None, app_context: AppContext) -> bool:
    """Check if user is allowed to use /img command."""
    if not app_context or not app_context.admin_service:
        raise ValueError("app_context with admin_service required")
    if not username:
        return False
    admin_service = cast(Any, app_context.admin_service)
    return admin_service.is_skynet_img_user(username)


@router.message(Command(commands=["img"]))
async def cmd_img(message: Message, bot: Bot, app_context: AppContext):
    if not app_context or not app_context.ai_service or not app_context.admin_service:
        raise ValueError("app_context with ai_service and admin_service required")
    ai_service = cast(Any, app_context.ai_service)
    username = message.from_user.username if message.from_user else None
    if message.chat.id in (MTLChats.CyberGroup,) or _is_skynet_img_user(username, app_context):
        actor_username = message.from_user.username if message.from_user and message.from_user.username else "unknown"
        message_text = message.text or ""
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
        await bot.send_message(chat_id=MTLChats.ITolstov, text=f"{actor_username}:{message_text}")
        text = message_text[5:]

        image_urls = await ai_service.generate_image(text)

        for url in image_urls:
            image_file = URLInputFile(url, filename="image.png")
            await message.reply_photo(image_file)
    else:
        await message.reply("Только в канале фракции Киберократии")
        return False


@router.message(Command(commands=["comment"]))
async def cmd_comment(message: Message, app_context: AppContext):
    if not app_context or not app_context.ai_service:
        raise ValueError("app_context with ai_service required")
    ai_service = cast(Any, app_context.ai_service)
    if message.reply_to_message is None:
        await message.reply("А чего комментировать то?")
        return
    if message.reply_to_message.text:
        msg = message.reply_to_message.text
    else:
        msg = message.reply_to_message.caption
    try:
        await message.delete()
    except Exception:
        pass

    msg = await ai_service.talk_get_comment(message.chat.id, msg)

    msg = await message.reply_to_message.reply(msg)
    my_talk_message.append(f"{msg.message_id}*{msg.chat.id}")


@router.message(F.text, F.reply_to_message, ReplyToBot(), F.chat.type != ChatType.PRIVATE)
async def cmd_last_check_reply_to_bot(message: Message, app_context: AppContext):
    if not app_context or not app_context.ai_service or not app_context.talk_service:
        raise ValueError("app_context with ai_service and talk_service required")
    ai_service = cast(Any, app_context.ai_service)
    talk_service = cast(Any, app_context.talk_service)
    if message.reply_to_message and f"{message.reply_to_message.message_id}*{message.chat.id}" in my_talk_message:
        # answer on bot message
        msg_text = await ai_service.talk(message.chat.id, message.text or "")

        try:
            msg = await message.reply(msg_text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            msg = await message.reply(msg_text)
        my_talk_message.append(f"{msg.message_id}*{msg.chat.id}")

    await talk_service.answer_notify_message(message, app_context)


@router.message(StartText(("SKYNET", "СКАЙНЕТ")), HasText(("УБИТЬ", "убей", "kill")))
async def cmd_last_check_nap(message: Message):
    await message.answer("Нельзя убивать. NAP NAP NAP")


@router.message(StartText(("SKYNET", "СКАЙНЕТ")), HasText(("ДЕКОДИРУЙ", "decode")))
async def cmd_last_check_decode(message: Message, session: AsyncSession, bot: Bot, app_context: AppContext):
    if (
        not app_context
        or not app_context.stellar_service
        or not app_context.utils_service
        or not app_context.config_service
    ):
        raise ValueError("app_context with stellar_service, utils_service, and config_service required")
    stellar_service = cast(Any, app_context.stellar_service)
    utils_service = cast(Any, app_context.utils_service)
    if message.reply_to_message:
        url = None
        if message.reply_to_message.text:
            if "eurmtl.me/sign_tools" in message.reply_to_message.text:
                url = extract_url(message.reply_to_message.text)

        if not url and message.reply_to_message.entities:
            for entity in message.reply_to_message.entities:
                if entity.type in ["url", "text_link"]:
                    source_text = message.reply_to_message.text or ""
                    url = entity.url if entity.type == "text_link" else entity.extract_from(source_text)
                    if url and "eurmtl.me/sign_tools" in url:
                        break
                    else:
                        url = None

        if url:
            msg = await stellar_service.check_url_xdr(url)
            msg = "\n".join(msg)
            await utils_service.multi_reply(message, msg)
        else:
            await message.reply("Ссылка не найдена")
    else:
        pinned_url = (
            await ConfigRepository(session).async_load_bot_value(message.chat.id, BotValueTypes.PinnedUrl) or ""
        )
        msg = await stellar_service.check_url_xdr(pinned_url)
        msg = "\n".join(msg)
        await utils_service.multi_reply(message, msg[:4000])


@update_command_info("Скайнет напомни", "Попросить Скайнет напомнить про подпись транзакции. Только в рабочем чате.")
@router.message(StartText(("SKYNET", "СКАЙНЕТ")), HasText(("НАПОМНИ",)))
async def cmd_last_check_remind(
    message: Message, session: AsyncSession, bot: Bot, app_context: AppContext, skyuser: SkyUser
):
    if not app_context or not app_context.talk_service:
        raise ValueError("app_context with talk_service required")
    talk_service = cast(Any, app_context.talk_service)
    await talk_service.remind(message, session, app_context, skyuser=skyuser)


@router.message(StartText(("SKYNET", "СКАЙНЕТ")), HasText(("задач",)))
async def cmd_last_check_task(message: Message, session: AsyncSession, bot: Bot, app_context: AppContext):
    if not app_context or not app_context.ai_service:
        raise ValueError("app_context with ai_service required")
    ai_service = cast(Any, app_context.ai_service)
    tmp_msg = await message.reply("Анализирую задачу...")
    msg = ""
    if message.reply_to_message:
        reply_username = (
            message.reply_to_message.from_user.username
            if message.reply_to_message.from_user and message.reply_to_message.from_user.username
            else "unknown"
        )
        msg += f"сообщение от: {reply_username} \nссылка: {message.reply_to_message.get_url()}\n"
        msg += f'текст: """{message.reply_to_message.text}"""\n\n\n'

    sender_username = message.from_user.username if message.from_user and message.from_user.username else "unknown"
    msg += f"сообщение от: {sender_username} \n"
    msg += f"ссылка: {message.get_url()}\n"
    msg += f'текст: """{(message.text or "")[7:]}"""\n\n\n'

    msg = await ai_service.add_task_to_google(msg)

    await message.reply(msg)
    await tmp_msg.delete()


@router.message(StartText(("SKYNET", "СКАЙНЕТ")), HasText(("гороскоп",)))
async def cmd_last_check_horoscope(message: Message, session: AsyncSession, bot: Bot, app_context: AppContext):
    if not app_context or not app_context.ai_service:
        raise ValueError("app_context with ai_service required")
    ai_service = cast(Any, app_context.ai_service)
    horoscope = ai_service.get_horoscope()
    await message.answer("\n".join(horoscope), parse_mode=ParseMode.MARKDOWN)


@update_command_info("Скайнет обнови отчёт", "Попросить Скайнет обновить файл отчета. Только в рабочем чате.")
@update_command_info("Скайнет обнови гарантов", "Попросить Скайнет обновить файл гарантов. Только в рабочем чате.")
@router.message(StartText(("SKYNET", "СКАЙНЕТ")), HasText(("ОБНОВИ",)))
async def cmd_last_check_update(
    message: Message, session: AsyncSession, bot: Bot, app_context: AppContext, skyuser: SkyUser
):
    if not app_context or not app_context.admin_service or not app_context.report_service:
        raise ValueError("app_context with admin_service and report_service required")
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False

    report_service = cast(Any, app_context.report_service)
    message_text = message.text or ""

    if has_words(message_text, ["MM", "ММ"]):
        msg = await message.reply("Зай, я запустила обновление")
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await report_service.update_mmwb_report(session)
        await msg.reply("Обновление завершено")
    if has_words(message_text, ["БДМ", "BIM"]):
        msg = await message.reply("Зай, я запустила обновление")
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await report_service.update_bim_data(session)
        await msg.reply("Обновление завершено")
    if has_words(message_text, ["ГАРАНТОВ"]):
        msg = await message.reply("Зай, я запустила обновление")
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await report_service.update_guarantors_report()
        await msg.reply("Обновление завершено")
    if has_words(message_text, ["ОТЧЕТ", "отчёт", "report"]):
        msg = await message.reply("Зай, я запустила обновление")
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await report_service.update_main_report(session)
        await msg.reply("Обновление завершено")
    if has_words(message_text, ["donate", "donates", "donated"]):
        msg = await message.reply("Зай, я запустила обновление")
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await report_service.update_donate_report(session)
        await msg.reply("Обновление завершено")


@rate_limit(5, "private_links")
@router.message(F.chat.type == ChatType.PRIVATE, F.entities)
async def handle_private_message_links(message: Message, bot: Bot):
    telegram_links = []
    buttons = []
    entities = message.entities or []
    base_text = message.text or ""
    if not message.from_user:
        return

    for entity in entities:
        if entity.type in ["url", "text_link"]:
            url = entity.url if entity.type == "text_link" else entity.extract_from(base_text)
            if url and "t.me/" in url:
                msg_info = extract_telegram_info(url)
                if msg_info:
                    try:
                        chat = await bot.get_chat(msg_info.chat_id)
                        telegram_links.append(f'{url} Группа "{chat.title}"')

                        chat_member = await bot.get_chat_member(msg_info.chat_id, message.from_user.id)
                        if chat_member and chat_member.status not in ["left", "kicked"]:
                            await pyro_update_msg_info(msg_info)
                            if msg_info.thread_name:
                                thread_link = "/".join(url.split("/")[:-1])
                                telegram_links.append(f'Топик <a href="{thread_link}"> "{msg_info.thread_name}"</a>')

                            if msg_info.message_text:
                                telegraph_link = await miniapps.create_uuid_page(msg_info)
                                chat_name = msg_info.chat_name or ""
                                buttons.append(
                                    [InlineKeyboardButton(text=f"ПП {chat_name[:30]}", url=telegraph_link.url)]
                                )
                    except TelegramBadRequest as e:
                        logger.error(f"Ошибка TelegramBadRequest при обработке {url}: {e}")
                        telegram_links.append(f'{url} группа "не определена"')
                    except Exception as e:
                        logger.error(f"Неожиданная ошибка при обработке {url}: {e}")

                    telegram_links.append(" ")

    if telegram_links:
        response = "Найдены ссылки:\n" + "\n".join(telegram_links)
        if buttons:
            response += "\n\n предпросмотр сообщений : "
        await message.reply(
            response,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
        )


@router.message(F.chat.type == ChatType.PRIVATE, F.text)
@router.message(StartText(("SKYNET", "СКАЙНЕТ", "SKYNET4", "СКАЙНЕТ4")), F.text)
@router.message(Command(commands=["skynet"]))
async def cmd_last_check_p(message: Message, session: AsyncSession, bot: Bot, app_context: AppContext):
    if not app_context or not app_context.ai_service:
        raise ValueError("app_context with ai_service required")
    ai_service = cast(Any, app_context.ai_service)
    message_text = message.text or ""
    gpt4 = False
    if len(message_text) > 7 and message_text[7] == "4":
        if message.chat.id != MTLChats.CyberGroup:
            await message.reply("Только в канале фракции Киберократии")
            return False
        gpt4 = True

    msg = message_text
    if message.reply_to_message and message.reply_to_message.text:
        msg = f"{message.reply_to_message.text} \n================\n{message_text}"

    googleit = "загугли" in message_text.lower()

    msg = await ai_service.talk(message.chat.id, msg, gpt4, googleit=googleit)

    if msg is None:
        msg = "=( connection error, retry again )="
    try:
        msg = await message.reply(msg, parse_mode=ParseMode.MARKDOWN)
    except TelegramBadRequest:
        try:
            msg = await message.reply(html_decoration.quote(msg), parse_mode=ParseMode.HTML)
        except TelegramBadRequest:
            msg = await message.reply(html_decoration.quote(msg))
    if message.chat.type != ChatType.PRIVATE:
        # на случай вызова из /skynet
        my_talk_message.append(f"{msg.message_id}*{msg.chat.id}")


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router talk_handlers was loaded")


cast(Any, register_handlers).priority = 90
