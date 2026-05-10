import asyncio
import base64
import hashlib
import json
import os
import re
import uuid
from contextlib import suppress
from datetime import datetime
from typing import Any, cast

from aiogram import Router, Bot, F
from aiogram.enums import ChatType, ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, LoginUrl, User
from loguru import logger
from sqlalchemy.orm import Session

from db.repositories import MessageRepository, ConfigRepository, ChatsRepository
from other.grist_tools import MTLGrist
from other.open_ai_tools import talk_get_summary
from other.constants import MTLChats, BotValueTypes
from services.command_registry_service import update_command_info
from services.app_context import AppContext
from services.skyuser import SkyUser
from other.pyro_tools import MessageInfo
from other.miniapps_tools import miniapps
from other.stellar import send_by_list
from services.eurmtl_bot_login_service import confirm_eurmtl_bot_login

router = Router()


@router.message(Command(commands=["exit"]))
@router.message(Command(commands=["restart"]))
async def cmd_exit(message: Message, state: FSMContext, app_context: AppContext, skyuser: SkyUser):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False

    data = await state.get_data()
    my_state = data.get("MyState")

    if my_state == "StateExit":
        await state.update_data(MyState=None)
        await message.reply(":[[[ ушла в закат =(")
        if not app_context or not app_context.bot_state_service:
            raise ValueError("app_context with bot_state_service required")
        app_context.bot_state_service.request_reboot()
        exit()
    else:
        await state.update_data(MyState="StateExit")
        await message.reply(":'[ боюсь")


@router.message(Command(commands=["err"]))
async def cmd_log_err(message: Message, app_context: AppContext, skyuser: SkyUser):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False
    await cmd_send_file(message, "skynet.err")


@router.message(Command(commands=["log"]))
async def cmd_log(message: Message, app_context: AppContext, skyuser: SkyUser):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False
    await cmd_send_file(message, "skynet.log")


@router.message(Command(commands=["ping_piro"]))
async def cmd_ping_piro(message: Message, app_context: AppContext, skyuser: SkyUser):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False
    if not app_context or not app_context.group_service:
        raise ValueError("app_context with group_service required")
    group_service = cast(Any, app_context.group_service)
    await group_service.ping_piro()


@router.message(Command(commands=["reload"]))
async def cmd_reload_subscriptions(message: Message, app_context: AppContext, skyuser: SkyUser):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False
    if not app_context.stellar_notification_service:
        await message.reply("Stellar notification service not available")
        return
    await message.reply("Syncing subscriptions...")
    await app_context.stellar_notification_service.sync_subscriptions()
    count = len(app_context.stellar_notification_service.subscriptions_map)
    await message.reply(f"Done. Active subscriptions: {count}")


@router.message(Command(commands=["test"]))
async def cmd_test_miniapps(message: Message, app_context: AppContext, skyuser: SkyUser):
    if not skyuser.is_skynet_admin():
        await message.reply("Only for admins")
        return

    user_from = message.from_user.username if message.from_user and message.from_user.username else "Unknown"
    msg_info = MessageInfo(
        chat_id=message.chat.id,
        message_id=message.message_id,
        user_from=user_from,
        message_text="This is a test message from Skynet Bot to verify MiniApps integration.\n<b>Bold Text</b>",
        reply_to_message=None,
    )

    try:
        page = await miniapps.create_uuid_page(msg_info)
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Open MiniApp Page", url=page.url)]])
        await message.reply(f"Generated page: {page.url}", reply_markup=markup)
    except Exception as e:
        await message.reply(f"Error generating page: {e}")


@router.message(Command(commands=["check_gs"]))
async def cmd_check_gs(message: Message, app_context: AppContext | None = None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False
    if not app_context or not app_context.gspread_service:
        await message.reply("GSpread сервис недоступен.")
        return False
    gspread_service = cast(Any, app_context.gspread_service)

    ok, info = await gspread_service.check_credentials()
    info = (info or "").strip()
    if len(info) > 200:
        info = info[:200] + "..."

    if ok:
        await message.reply(f"Google ключ: OK. Таблиц: {info}")
    else:
        await message.reply(f"Google ключ: ошибка. {info}")


async def cmd_send_file(message: Message, filename):
    try:
        if not os.path.isfile(filename):
            await message.reply(f"Файл {filename} не найден")
            return

        if os.path.getsize(filename) == 0:
            await message.reply(f"Файл {filename} пуст")
            return

        await message.reply_document(FSInputFile(filename))
    except Exception as e:
        logger.error(f"Ошибка при отправке файла {filename}: {e}")
        await message.reply(f"Произошла ошибка при отправке файла {filename}")


@router.message(Command(commands=["summary"]))
async def cmd_get_summary(message: Message, session: Session, app_context: AppContext, skyuser: SkyUser):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False

    # Check if listening is enabled for this chat
    if not app_context or not app_context.feature_flags:
        raise ValueError("app_context with feature_flags required")
    feature_flags = cast(Any, app_context.feature_flags)
    is_listening = feature_flags.is_listening(message.chat.id)

    if not is_listening:
        await message.reply("No messages 1")
        return

    try:
        thread_id = message.message_thread_id or 0
        data = MessageRepository(session).get_messages_without_summary(
            chat_id=message.chat.id,
            thread_id=thread_id,
        )

        if not data:
            await message.reply("Нет новых сообщений для обработки")
            return

        text = ""
        summary = MessageRepository(session).add_summary(text=text)
        summary_obj = cast(Any, summary)
        session.flush()

        try:
            for record in data:
                record_username = str(record.username or "")
                record_text = str(record.text or "")
                new_text = text + f"{record_username}: {record_text} \n\n"
                if len(new_text) < 16000:
                    text = new_text
                    record.summary_id = summary.id
                    session.flush()
                else:
                    summary_obj.text = await talk_get_summary(text)
                    session.flush()
                    summary = MessageRepository(session).add_summary(text="")
                    summary_obj = cast(Any, summary)
                    session.flush()
                    text = f"{record_username}: {record_text}\n\n"
                    record.summary_id = summary.id
                    session.flush()

            if text:  # Обработка оставшегося текста
                summary_obj.text = await talk_get_summary(text)
                session.flush()

            summaries = MessageRepository(session).get_summary(
                chat_id=message.chat.id,
                thread_id=thread_id,
            )

            if not summaries:
                await message.reply("Не удалось получить сводку сообщений")
                return

            for record in summaries:
                record_text = str(record.text or "")
                if record_text:
                    await message.reply(record_text[:4000])
                else:
                    logger.warning(f"Empty summary text for record {record.id}")

            session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"Error processing messages for summary: {e}")
            await message.reply("Произошла ошибка при обработке сообщений")
            return

    except Exception as e:
        logger.error(f"Database error in cmd_get_summary: {e}")
        await message.reply("Произошла ошибка при работе с базой данных")
        return


@router.message(F.document, F.chat.type == ChatType.PRIVATE)
async def cmd_get_sha1(message: Message, bot: Bot):
    document = message.document
    if not document:
        await message.reply("Файл не найден")
        return
    file_data = await bot.download(document)
    if not file_data:
        await message.reply("Не удалось скачать файл")
        return
    file_bytes = file_data.read()

    hasher = hashlib.sha1()
    hasher.update(file_bytes)
    sha1_hash = hasher.hexdigest()
    base64_hash = base64.b64encode(hasher.digest()).decode("utf-8")

    sha256_hasher = hashlib.sha256()
    sha256_hasher.update(file_bytes)
    sha256_hash = sha256_hasher.hexdigest()

    await message.reply(
        f"SHA-1: <code>{sha1_hash}</code>\nBASE64: <code>{base64_hash}</code>\n\nSHA-256: <code>{sha256_hash}</code>"
    )


@router.message(Command(commands=["sha256"]))
async def cmd_sha256(message: Message):
    sha256_hasher = hashlib.sha256()
    text = message.text or ""
    sha256_hasher.update(text[8:].encode("utf-8"))
    sha256_hash = sha256_hasher.hexdigest()
    await message.reply(f"SHA-256: <code>{sha256_hash}</code>")


@update_command_info("/sync", "Синхронизирует сообщение в чате с постом в канале")
@router.message(Command(commands=["sync"]))
async def cmd_sync_post(message: Message, bot: Bot, session: Session, app_context: AppContext, skyuser: SkyUser):
    if not await skyuser.is_admin():
        await message.reply(skyuser.admin_denied_text())
        return

    if not message.reply_to_message or not message.reply_to_message.forward_from_chat:
        await message.reply("Могу синхронизировать только посты")
        return

    try:
        chat = await bot.get_chat(message.reply_to_message.forward_from_chat.id)
    except TelegramBadRequest:
        await message.reply("Канал не найден, нужно быть админом в канале")
        return
    except Exception as e:
        logger.error(f"Unexpected error while getting chat: {e}")
        await message.reply("Произошла непредвиденная ошибка при получении информации о канале")
        return

    if not app_context or not app_context.bot_state_service:
        raise ValueError("app_context with bot_state_service required")

    try:
        post_id = message.reply_to_message.forward_from_message_id
        url = f"https://t.me/c/{str(chat.id)[4:]}/{post_id}"
        msg_text = message.reply_to_message.html_text
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Edit", url=url), InlineKeyboardButton(text="Edit", url=url)]]
        )
        if msg_text and msg_text[-1] == "*":
            msg_text = msg_text[:-1]
            reply_markup = None

        new_msg = await message.answer(msg_text, disable_web_page_preview=True, reply_markup=reply_markup)

        # Get sync state for this channel
        sync_key = str(chat.id)
        channel_sync = app_context.bot_state_service.get_sync_state(sync_key, {})

        if str(post_id) not in channel_sync:
            channel_sync[str(post_id)] = []

        channel_sync[str(post_id)].append({"chat_id": message.chat.id, "message_id": new_msg.message_id, "url": url})

        # Save sync state
        app_context.bot_state_service.set_sync_state(sync_key, channel_sync)

        ConfigRepository(session).save_bot_value(chat.id, BotValueTypes.Sync, json.dumps(channel_sync))

        with suppress(TelegramBadRequest):
            await message.reply_to_message.delete()
        with suppress(TelegramBadRequest):
            await message.delete()

    except Exception as e:
        logger.error(f"Error in cmd_sync_post: {e}")
        await message.reply("Произошла ошибка при синхронизации поста")


@update_command_info("/resync", "Восстанавливает синхронизацию сообщения с постом в канале")
@router.message(Command(commands=["resync"]))
async def cmd_resync_post(message: Message, session: Session, bot: Bot, app_context: AppContext, skyuser: SkyUser):
    if not await skyuser.is_admin():
        await message.reply(skyuser.admin_denied_text())
        return

    reply_message = message.reply_to_message if isinstance(message.reply_to_message, Message) else None
    if not reply_message or not reply_message.from_user or reply_message.from_user.id != bot.id:
        await message.reply("Нужно ответить на сообщение, отправленное ботом")
        return

    if not app_context or not app_context.bot_state_service:
        raise ValueError("app_context with bot_state_service required")

    try:
        # Получаем клавиатуру из сообщения бота
        reply_markup = reply_message.reply_markup
        if not reply_markup or not isinstance(reply_markup, InlineKeyboardMarkup):
            await message.reply("Не найдена клавиатура с кнопкой редактирования")
            return

        # Извлекаем URL из кнопки Edit
        edit_button = next(
            (button for row in reply_markup.inline_keyboard for button in row if button.text == "Edit"), None
        )
        if not edit_button:
            await message.reply("Не найдена кнопка Edit")
            return

        url = edit_button.url
        if not url:
            await message.reply("Неверный формат URL")
            return
        # Извлекаем chat_id и post_id из URL
        match = re.search(r"https://t\.me/c/(\d+)/(\d+)", url)
        if not match:
            await message.reply("Неверный формат URL")
            return

        chat_id, post_id = match.groups()
        chat_id = int(f"-100{chat_id}")

        # Проверяем, что бот является участником канала
        try:
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            if bot_member.status not in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
            ):
                await message.reply(
                    "Бот не является участником канала, синхронизация не будет работать. Добавьте бота в канал и попробуйте снова."
                )
                return
        except TelegramBadRequest:
            await message.reply(
                "Бот не является участником канала, синхронизация не будет работать. Добавьте бота в канал и попробуйте снова."
            )
            return

        # Get sync state for this channel
        sync_key = str(chat_id)
        channel_sync = cast(dict[str, list[dict[str, Any]]], app_context.bot_state_service.get_sync_state(sync_key, {}))

        if post_id not in channel_sync:
            channel_sync[post_id] = []

        # Проверяем, существует ли уже запись для данного чата и сообщения
        existing_record = next(
            (
                record
                for record in channel_sync[post_id]
                if record["chat_id"] == message.chat.id and record["message_id"] == reply_message.message_id
            ),
            None,
        )

        if existing_record:
            await message.reply("Синхронизация для этого сообщения уже существует")
        else:
            # Добавляем новую запись, не затрагивая существующие
            channel_sync[post_id].append(
                {"chat_id": message.chat.id, "message_id": reply_message.message_id, "url": url}
            )

            # Save sync state
            app_context.bot_state_service.set_sync_state(sync_key, channel_sync)

            # Сохраняем обновленные данные в БД
            ConfigRepository(session).save_bot_value(chat_id, BotValueTypes.Sync, json.dumps(channel_sync))

            await message.reply(
                "Синхронизация восстановлена, сообщение не обновленно, внесите любую правку в оригинал."
            )

    except Exception as e:
        logger.error(f"Error in cmd_resync_post: {e}")
        await message.reply("Произошла ошибка при восстановлении синхронизации")

    # Удаляем команду /resync
    with suppress(TelegramBadRequest):
        await message.delete()


@router.edited_channel_post(F.text)
async def cmd_edited_channel_post(message: Message, bot: Bot, session: Session, app_context: AppContext):
    if not app_context or not app_context.bot_state_service:
        raise ValueError("app_context with bot_state_service required")
    logger.info(
        "edited_channel_post received: channel_id={}, post_id={}",
        message.chat.id,
        message.message_id,
    )
    # Get sync state for this channel
    sync_key = str(message.chat.id)
    channel_sync = cast(dict[str, list[dict[str, Any]]], app_context.bot_state_service.get_sync_state(sync_key, {}))

    post_sync_records = channel_sync.get(str(message.message_id), [])
    if not post_sync_records:
        logger.info(
            "No sync records found: channel_id={}, post_id={}",
            message.chat.id,
            message.message_id,
        )
        return

    logger.info(
        "Sync records found: channel_id={}, post_id={}, targets={}",
        message.chat.id,
        message.message_id,
        len(post_sync_records),
    )

    stale_records = []
    for data in post_sync_records:
        msg_text = message.html_text
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Edit", url=data["url"]), InlineKeyboardButton(text="Edit", url=data["url"])]
            ]
        )
        if msg_text and msg_text[-1] == "*":
            msg_text = msg_text[:-1]
            reply_markup = None
        logger.info(
            "Syncing edited post to chat_id={}, message_id={}, source_channel_id={}, source_post_id={}",
            data["chat_id"],
            data["message_id"],
            message.chat.id,
            message.message_id,
        )
        try:
            await bot.edit_message_text(
                text=msg_text,
                chat_id=data["chat_id"],
                message_id=data["message_id"],
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as exc:
            logger.error(
                "Failed to sync edited post to chat_id={}, message_id={}, source_channel_id={}, source_post_id={}: {}",
                data["chat_id"],
                data["message_id"],
                message.chat.id,
                message.message_id,
                exc,
            )
            stale_records.append(data)
            continue
        except Exception as exc:
            logger.error(
                "Failed to sync edited post to chat_id={}, message_id={}, source_channel_id={}, source_post_id={}: {}",
                data["chat_id"],
                data["message_id"],
                message.chat.id,
                message.message_id,
                exc,
            )
            continue
        logger.info(
            "Synced edited post to chat_id={}, message_id={}, source_channel_id={}, source_post_id={}",
            data["chat_id"],
            data["message_id"],
            message.chat.id,
            message.message_id,
        )

    # Remove stale records and persist
    if stale_records:
        post_key = str(message.message_id)
        for record in stale_records:
            channel_sync[post_key].remove(record)
        if not channel_sync[post_key]:
            del channel_sync[post_key]
        app_context.bot_state_service.set_sync_state(sync_key, channel_sync)
        ConfigRepository(session).save_bot_value(message.chat.id, BotValueTypes.Sync, json.dumps(channel_sync))


@router.message(CommandStart(deep_link=True, magic=F.args.regexp(r"^eurmtl_.+")), F.chat.type == "private")
async def cmd_eurmtl_bot_login(message: Message):
    start_arg = (message.text or "").split(maxsplit=1)[1]
    token = start_arg.removeprefix("eurmtl_")
    if not token or not message.from_user:
        await message.answer("Ссылка устарела, начните вход заново на сайте.")
        return

    auth_date = int(message.date.timestamp())
    result = await confirm_eurmtl_bot_login(token=token, user=message.from_user, auth_date=auth_date)
    if result.success:
        await message.answer("Вход подтвержден, вернитесь на сайт.")
        return

    await message.answer("Ссылка устарела, начните вход заново на сайте.")


@router.message(Command(commands=["eurmtl"]))
@router.message(CommandStart(deep_link=True, magic=F.args == "eurmtl"), F.chat.type == "private")
async def cmd_eurmtl(message: Message):
    url1 = LoginUrl(url="https://eurmtl.me/authorize")
    url2 = LoginUrl(url="https://eurmtl.me/tables/authorize")
    await message.answer(
        "Click the button below to log in EURMTL.me:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Main", login_url=url1)],
                [InlineKeyboardButton(text="Tables", login_url=url2)],
            ]
        ),
    )


@router.message(Command(commands=["grist"]))
@router.message(CommandStart(deep_link=True, magic=F.args == "grist"), F.chat.type == "private")
async def cmd_grist(message: Message, app_context: AppContext):
    if not app_context or not app_context.grist_service:
        raise ValueError("app_context with grist_service required")
    if not message.from_user:
        await message.answer("❌ Не удалось определить пользователя.")
        return
    user_id = message.from_user.id
    grist_service = cast(Any, app_context.grist_service)
    try:
        access_records = await grist_service.load_table_data(MTLGrist.GRIST_access)

        for r in access_records:
            print(r)

        user_record = next((r for r in access_records if r.get("user_id") == user_id), None)

        if not user_record:
            await message.answer("❌ У вас нет доступа к Grist.")
            return

        new_key = str(uuid.uuid4())

        update_data = {
            "records": [{"id": user_record["id"], "fields": {"key": new_key, "dt_update": datetime.now().isoformat()}}]
        }

        await grist_service.patch_data(MTLGrist.GRIST_access, update_data)

        await message.answer(f"✅ Новый ключ доступа:\n<code>{new_key}</code>")

    except Exception as e:
        logger.error(f"Grist access error: {e}")
        await message.answer("⚠️ Произошла ошибка при обработке запроса. Попробуйте позже.")


@router.message(Command(commands=["update_mtlap"]))
async def cmd_update_mtlap(message: Message, bot: Bot, app_context: AppContext, skyuser: SkyUser):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return

    if not app_context or not app_context.gspread_service or not app_context.mtl_service:
        raise ValueError("app_context with gspread_service and mtl_service required")
    gspread_service = cast(Any, app_context.gspread_service)
    mtl_service = cast(Any, app_context.mtl_service)

    data = await gspread_service.get_all_mtlap()

    if not data or len(data) < 1:
        await message.reply("Ошибка: таблица пуста или не найдены данные.")
        return

    headers = data[0]

    if len(headers) < 15 or headers[1] != "TGID" or headers[14] != "SkyNet":
        await message.reply("Ошибка: неверный формат таблицы. Проверьте наличие и позицию столбцов TGID и SkyNet.")
        return

    results = []
    user_id: int

    for row in data[1:]:
        if len(row[1]) < 3:
            break

        try:
            user_id = int(row[1])
            await bot.send_chat_action(user_id, action="typing")
            results.append(True)
        except Exception:
            results.append(False)
        await asyncio.sleep(0.1)

    await gspread_service.get_update_mtlap_skynet_row(results)

    await message.reply("Готово 1")

    result = await mtl_service.check_consul_mtla_chats(message.bot)

    if result:
        await message.reply("\n".join(result))

    await message.reply("Готово 2")


@router.message(Command(commands=["update_chats_info"]))
async def cmd_chats_info(message: Message, session: Session, app_context: AppContext, skyuser: SkyUser):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return
    if not app_context or not app_context.group_service:
        raise ValueError("app_context with group_service required")
    group_service = cast(Any, app_context.group_service)
    await message.answer(text="Обновление информации о чатах...")
    for chat_id in [MTLChats.DistributedGroup, -1001892843127]:
        members = await group_service.get_members(chat_id)
        ChatsRepository(session).update_chat_info(chat_id, members)
    await message.answer(text="Обновление информации о чатах... Done.")


async def check_membership(bot: Bot, chat_id: int, user_id: int) -> tuple[bool, User | None]:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        is_member = member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR]
        return is_member, member.user

    except TelegramBadRequest:
        return False, None


@update_command_info("/push", "Отправить сообщение в личку. Только для админов скайнета")
@router.message(Command(commands=["push"]))
async def cmd_push(message: Message, bot: Bot, app_context: AppContext, skyuser: SkyUser):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return

    if message.reply_to_message is None:
        await message.reply("Команду надо посылать в ответ на список логинов")
        return

    source_text = message.reply_to_message.text or ""
    if source_text.find("@") == -1:
        await message.reply("Нет не одной собаки. Команда работает в ответ на список логинов")
        return

    all_users = source_text.split()
    await send_by_list(bot, all_users, message)


@router.message(Command(commands=["get_info"]))
@router.message(Command(re.compile(r"get_info_(\d+)")))
async def cmd_get_info(
    message: Message, bot: Bot, app_context: AppContext | None = None, skyuser: SkyUser | None = None
):
    if not skyuser or not skyuser.is_skynet_admin():
        if message.chat.id != MTLChats.HelperChat:
            await message.reply("You are not my admin.")
            return

    command_args = (message.text or "").split()
    if not command_args:
        await message.reply("Пришлите числовой ID")
        return

    command_name = command_args[0].split("@")[0].lstrip("/")
    if command_name == "get_info":
        if len(command_args) < 2:
            await message.reply("Пришлите числовой ID")
            return
        raw_id = command_args[1].strip()
        if raw_id.upper().startswith("#ID"):
            raw_id = raw_id[3:]
        if not raw_id.isdigit():
            await message.reply("ID должен быть числом.")
            return
        user_id = raw_id
    else:
        match = re.match(r"get_info_(\d+)", command_name)
        if not match:
            await message.reply("Некорректная команда. Используйте /get_info <ID>")
            return
        user_id = match.group(1)

    messages = []

    chat_list = (
        (MTLChats.MonteliberoChanel, "канал Montelibero ru"),
        (MTLChats.MTLAAgoraGroup, "MTLAAgoraGroup"),
        (-1001429770534, "chat Montelibero ru"),
    )

    for chat_id, chat_name in chat_list:
        is_member, user = await check_membership(bot, chat_id, int(user_id))
        if is_member:
            if user and user.username:
                messages.append(f"Пользователь @{user.username} подписан на {chat_name}")
            else:
                messages.append(f"Пользователь подписан на {chat_name}")
                messages.append("<b>!Внимание: нет юзернейма</b>")
        else:
            messages.append(f"Пользователь не подписан на {chat_name}")

    # messages.extend(await gs_find_user(user_id))
    # if app_context:
    #      messages.extend(await app_context.gspread_service.find_user(user_id))
    # else:
    #      messages.extend(await gs_find_user(user_id))

    messages.append("Я больше не умею проверять на айдропы, гуглшит не работает")

    await message.reply("\n".join(messages))


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router admin_system was loaded")
