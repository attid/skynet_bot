import json
import random
import re
import datetime
from contextlib import suppress
from typing import Any, cast

from aiogram import Router, Bot, F
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import (
    Command,
    ChatMemberUpdatedFilter,
    IS_NOT_MEMBER,
    IS_MEMBER,
    PROMOTED_TRANSITION,
    MEMBER,
    ADMINISTRATOR,
)
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
    ChatMemberUpdated,
    ChatMemberMember,
    ChatJoinRequest,
)
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories import MessageRepository

# from routers.multi_handler import check_membership, enforce_entry_channel
from routers.moderation import UnbanCallbackData
from start import async_add_bot_users
from other.aiogram_tools import get_username_link, get_chat_link
from other.constants import MTLChats, BotValueTypes
from services.command_registry_service import update_command_info
from services.skyuser import SkyUser
from other.pyro_tools import GroupMember
from shared.domain.user import SpamStatus
from db.repositories import ConfigRepository, ChatsRepository
# from other.spam_cheker import combo_check_spammer, lols_check_spammer

router = Router()


class CaptchaCallbackData(CallbackData, prefix="captcha"):
    answer: int


class JoinCallbackData(CallbackData, prefix="join"):
    user_id: int
    chat_id: int
    can_join: bool


class EmojiCaptchaCallbackData(CallbackData, prefix="e_captcha"):
    user_id: int
    square: str
    num: int


def generate_number_with_sum(target_sum):
    while True:
        # Генерируем случайное четырехзначное число
        num = random.randint(1000, 9999)
        # Вычисляем сумму цифр этого числа
        digits_sum = sum(int(digit) for digit in str(num))
        # Если сумма цифр оканчивается на нужную цифру, возвращаем число
        if digits_sum % 10 == target_sum:
            return num


def get_last_digit_of_sum(number):
    digits_sum = sum(int(digit) for digit in str(number))
    return digits_sum % 10


def build_ban_message(user, chat, reason: str, actor=None) -> str:
    username = f"@{user.username}" if user.username else "—"
    full_name = user.full_name or "—"
    user_line = f"{user.mention_html()} was banned (id={user.id}, username={username}, name={full_name})"

    chat_username = f"@{chat.username}" if chat.username else "—"
    chat_title = chat.title or "—"
    chat_line = f"Чат: {get_chat_link(chat)} (id={chat.id}, username={chat_username}, title={chat_title})"

    parts = [
        user_line,
        chat_line,
        f"Причина: {reason}",
    ]

    if actor and actor.id != user.id:
        actor_username = f"@{actor.username}" if actor.username else "—"
        actor_name = actor.full_name or "—"
        parts.append(f"Кем: {actor.mention_html()} (id={actor.id}, username={actor_username}, name={actor_name})")

    return "\n".join(parts)


emoji_pairs = [
    ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚫️", "⚪️", "🟤"],  # Круги
    ["🟥", "🟧", "🟨", "🟩", "🟦", "🟪", "⬛️", "⬜️", "🟫"],  # Квадраты
]


def strip_emoji_captcha_lines(text: str) -> str:
    captcha_emoji = tuple(emoji for row in emoji_pairs for emoji in row)
    captcha_emoji_without_vs = tuple(emoji.replace("\ufe0f", "") for emoji in captcha_emoji)

    lines = []
    for line in text.splitlines():
        normalized_line = line.replace("\ufe0f", "")
        if any(emoji in line for emoji in captcha_emoji) or any(
            emoji in normalized_line for emoji in captcha_emoji_without_vs
        ):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


dal = (
    "🔴🟤",  # 1 9  # 0 8
    "🟠🟢",  # 2 4   # 1 3
    "🔵🟣",
)  # 5 6   # 4 5


# первый и последний; второй и четвертый; пятый и шестой; для дальтоников сильно похожи


def create_emoji_captcha_keyboard(user_id, required_num):
    random_indices = random.sample(range(9), 6)

    if required_num not in random_indices:
        random_indices[random.randint(0, 5)] = required_num

    buttons = []

    for index in random_indices:
        square = emoji_pairs[1][index]
        num = generate_number_with_sum(index)
        if index != required_num:
            num += 1
        button = InlineKeyboardButton(
            text=square, callback_data=EmojiCaptchaCallbackData(user_id=user_id, square=square, num=num).pack()
        )
        buttons.append(button)

    random.shuffle(buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons[:3], buttons[3:]])

    return keyboard


@update_command_info("/delete_welcome", "Отключить сообщения приветствия")
@router.message(Command(commands=["delete_welcome"]))
async def cmd_delete_welcome(
    message: Message,
    app_context: Any = None,
    skyuser: SkyUser | None = None,
):
    if not app_context or not app_context.config_service or not app_context.utils_service or not app_context.db_service:
        raise ValueError("app_context with config_service, utils_service, and db_service required")
    config_service = cast(Any, app_context.config_service)
    utils_service = cast(Any, app_context.utils_service)
    db_service = cast(Any, app_context.db_service)
    admin = await skyuser.is_admin() if skyuser else False

    if not admin:
        text = skyuser.admin_denied_text() if skyuser else "You are not admin."
        await message.reply(text)
        return False

    has_welcome = config_service.get_welcome_message(message.chat.id) is not None

    if has_welcome:
        config_service.remove_welcome_message(message.chat.id)
        await db_service.save_bot_value(message.chat.id, BotValueTypes.WelcomeMessage, None)

    msg = await message.reply("Removed")
    await utils_service.sleep_and_delete(msg, 60)
    await utils_service.sleep_and_delete(message, 60)


@update_command_info(
    "/set_welcome", "Установить сообщение приветствия при входе. Шаблон на имя $$USER$$", 2, "welcome_messages"
)
@router.message(Command(commands=["set_welcome"]))
async def cmd_set_welcome(
    message: Message,
    app_context: Any = None,
    skyuser: SkyUser | None = None,
):
    if not app_context or not app_context.config_service or not app_context.utils_service or not app_context.db_service:
        raise ValueError("app_context with config_service, utils_service, and db_service required")
    config_service = cast(Any, app_context.config_service)
    utils_service = cast(Any, app_context.utils_service)
    db_service = cast(Any, app_context.db_service)
    admin = await skyuser.is_admin() if skyuser else False

    if not admin:
        text = skyuser.admin_denied_text() if skyuser else "You are not admin."
        await message.reply(text)
        return False

    if len((message.text or "").split()) > 1:
        welcome_html = message.html_text or message.text or ""
        welcome_text = welcome_html[13:]

        config_service.set_welcome_message(message.chat.id, welcome_text)
        await db_service.save_bot_value(message.chat.id, BotValueTypes.WelcomeMessage, welcome_text)
        msg = await message.reply("Added")
        await utils_service.sleep_and_delete(msg, 60)
    else:
        await cmd_delete_welcome(message, app_context=app_context, skyuser=skyuser)

    await utils_service.sleep_and_delete(message, 60)


@update_command_info("/set_welcome_button", "Установить текст на кнопке капчи", 2, "welcome_button")
@router.message(Command(commands=["set_welcome_button"]))
async def cmd_set_welcome_button(
    message: Message,
    app_context: Any = None,
    skyuser: SkyUser | None = None,
):
    if not app_context or not app_context.config_service or not app_context.utils_service or not app_context.db_service:
        raise ValueError("app_context with config_service, utils_service, and db_service required")
    config_service = cast(Any, app_context.config_service)
    utils_service = cast(Any, app_context.utils_service)
    db_service = cast(Any, app_context.db_service)
    admin = await skyuser.is_admin() if skyuser else False

    if not admin:
        text = skyuser.admin_denied_text() if skyuser else "You are not admin."
        await message.reply(text)
        return False

    if len((message.text or "").split()) > 1:
        text = (message.text or "")[19:].strip()

        config_service.set_welcome_button(message.chat.id, text)
        await db_service.save_bot_value(message.chat.id, BotValueTypes.WelcomeButton, text)
        msg = await message.reply("Added")
        await utils_service.sleep_and_delete(msg, 60)
    else:
        msg = await message.reply("need more words")
        await utils_service.sleep_and_delete(msg, 60)

    await utils_service.sleep_and_delete(message, 60)


@update_command_info("/stop_exchange", "Остановить ботов обмена. Только для админов")
@router.message(Command(commands=["stop_exchange"]))
async def cmd_stop_exchange(message: Message, app_context: Any = None, skyuser: SkyUser | None = None):
    is_admin_user = skyuser.is_skynet_admin() if skyuser else False

    if not is_admin_user:
        await message.reply("You are not my admin.")
        return False

    if not app_context or not app_context.stellar_service or not app_context.db_service:
        raise ValueError("app_context with stellar_service and db_service required")
    stellar_service = cast(Any, app_context.stellar_service)
    db_service = cast(Any, app_context.db_service)
    await db_service.save_bot_value(0, BotValueTypes.StopExchange, 1)
    await stellar_service.stop_all_exchange()

    await message.reply("Was stop")


@update_command_info("/start_exchange", "Запустить ботов обмена. Только для админов")
@router.message(Command(commands=["start_exchange"]))
async def cmd_start_exchange(message: Message, app_context: Any = None, skyuser: SkyUser | None = None):
    is_admin_user = skyuser.is_skynet_admin() if skyuser else False

    if not is_admin_user:
        await message.reply("You are not my admin.")
        return False

    if not app_context or not app_context.db_service:
        raise ValueError("app_context with db_service required")
    db_service = cast(Any, app_context.db_service)
    await db_service.save_bot_value(0, BotValueTypes.StopExchange, None)
    await message.reply("Was start")


bad_names = ["ЧВК ВАГНЕР", "ЧВК ВАГНЕР"]


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def new_chat_member(event: ChatMemberUpdated, session: AsyncSession, bot: Bot, app_context: Any = None):
    if (
        not app_context
        or not app_context.antispam_service
        or not app_context.config_service
        or not app_context.group_service
    ):
        raise ValueError("app_context with antispam_service, config_service and group_service required")
    antispam_service = cast(Any, app_context.antispam_service)
    config_service = cast(Any, app_context.config_service)
    group_service = cast(Any, app_context.group_service)
    feature_flags = cast(Any, app_context.feature_flags) if app_context.feature_flags else None
    utils_service = cast(Any, app_context.utils_service) if app_context.utils_service else None
    new_user_id = event.new_chat_member.user.id
    chat_id = event.chat.id

    is_spam1 = await antispam_service.combo_check_spammer(new_user_id)

    if is_spam1:
        await bot.ban_chat_member(chat_id, event.new_chat_member.user.id)
        reason = f'<a href="https://cas.chat/query?u={new_user_id}">CAS ban</a>'
        await bot.send_message(
            MTLChats.SpamGroup,
            build_ban_message(event.new_chat_member.user, event.chat, reason, actor=event.from_user),
            disable_web_page_preview=True,
        )
        return

    is_spam2 = await antispam_service.lols_check_spammer(new_user_id)

    if is_spam2:
        await bot.ban_chat_member(chat_id, event.new_chat_member.user.id)
        reason = f'<a href="https://lols.bot/?u={new_user_id}">LOLS base</a>'
        await bot.send_message(
            MTLChats.SpamGroup,
            build_ban_message(event.new_chat_member.user, event.chat, reason, actor=event.from_user),
            disable_web_page_preview=True,
        )
        return

    if event.new_chat_member.user.full_name in bad_names:
        await bot.ban_chat_member(chat_id, event.new_chat_member.user.id)
        reason = f"за использование запрещенного никнейма: {event.new_chat_member.user.full_name}"
        await bot.send_message(
            MTLChats.SpamGroup, build_ban_message(event.new_chat_member.user, event.chat, reason, actor=event.from_user)
        )
        return

    required_channel = config_service.get_entry_channel(chat_id)

    if required_channel:
        membership_ok, _ = await group_service.enforce_entry_channel(bot, chat_id, new_user_id, required_channel)
        if not membership_ok:
            return

    member = GroupMember(
        user_id=event.new_chat_member.user.id,
        username=event.new_chat_member.user.username,
        full_name=event.new_chat_member.user.full_name,
        is_admin=False,
    )

    chats_repo = ChatsRepository(session)
    await chats_repo.async_add_user_to_chat(chat_id, member)
    user = await chats_repo.async_get_user_by_id(event.new_chat_member.user.id)
    user_obj = cast(Any, user) if user else None
    user_type_now = int(user_obj.user_type) if user_obj and user_obj.user_type is not None else 0

    username = get_username_link(event.new_chat_member.user)
    if user_type_now == SpamStatus.BAD:
        with suppress(TelegramBadRequest):
            await bot.ban_chat_member(chat_id, event.new_chat_member.user.id)
        kb_unban = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="unban",
                        callback_data=UnbanCallbackData(user_id=event.new_chat_member.user.id, chat_id=chat_id).pack(),
                    )
                ]
            ]
        )
        # await bot.send_message(chat_id, f'{username} was banned', reply_markup=kb_unban)
        reason = "SpamStatus.BAD (db)"
        await bot.send_message(
            MTLChats.SpamGroup,
            build_ban_message(event.new_chat_member.user, event.chat, reason, actor=event.from_user),
            reply_markup=kb_unban,
        )

    selfmod_enabled = feature_flags.is_enabled(chat_id, "selfmod") if feature_flags else False
    if selfmod_enabled:
        from routers.selfmod import begin_join_vote

        try:
            await begin_join_vote(bot, event.chat, event.new_chat_member.user, app_context)
        except Exception as e:
            logger.warning("selfmod begin_join_vote failed chat={} user={} err={}", chat_id, new_user_id, e)
        return

    welcome_msg = config_service.get_welcome_message(chat_id)

    if welcome_msg:
        if event.new_chat_member.user:
            msg = welcome_msg if welcome_msg else "Hi new user"
            msg = msg.replace("$$USER$$", username)

            kb_captcha = None
            captcha_enabled = feature_flags.is_enabled(chat_id, "captcha") if feature_flags else False

            if captcha_enabled:
                btn_msg = config_service.get_welcome_button(chat_id) or "I'm not bot"

                kb_captcha = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=btn_msg,
                                callback_data=CaptchaCallbackData(answer=event.new_chat_member.user.id).pack(),
                            )
                        ]
                    ]
                )
                random_color = random.randint(0, 8)
                if msg.find("$$COLOR$$") > 0:
                    msg = msg.replace("$$COLOR$$", emoji_pairs[0][random_color])
                    kb_captcha = create_emoji_captcha_keyboard(event.new_chat_member.user.id, random_color)

                try:
                    await bot.restrict_chat_member(
                        chat_id,
                        event.new_chat_member.user.id,
                        permissions=ChatPermissions(
                            can_send_messages=False, can_send_media_messages=False, can_send_other_messages=False
                        ),
                    )
                    logger.info(
                        "moderation_artifact action=restrict_captcha chat_id={} user_id={} actor_id={}",
                        chat_id,
                        event.new_chat_member.user.id,
                        event.from_user.id if event.from_user else "system",
                    )
                except Exception as e:
                    message_repo = MessageRepository(session)
                    error_message = f"new_chat_member error {type(e)} {event.chat.model_dump_json()}"
                    await message_repo.async_send_admin_message(error_message)

            answer = await bot.send_message(
                chat_id, msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=kb_captcha
            )
            if utils_service:
                await utils_service.sleep_and_delete(answer)

    auto_all_enabled = feature_flags.is_enabled(chat_id, "auto_all") if feature_flags else False

    if auto_all_enabled:
        config_repo = ConfigRepository(session)
        json_str = await config_repo.async_load_bot_value(chat_id, BotValueTypes.All, "[]")
        members = json.loads(json_str) if json_str else []

        if event.new_chat_member.user.username:
            members.append("@" + event.new_chat_member.user.username)
        else:
            await bot.send_message(
                chat_id, f"{event.new_chat_member.user.full_name} dont have username cant add to /all"
            )

        await config_repo.async_save_bot_value(chat_id, BotValueTypes.All, json.dumps(members))


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def left_chat_member(
    event: ChatMemberUpdated,
    session: AsyncSession,
    bot: Bot,
    app_context: Any = None,
    skyuser: SkyUser | None = None,
):
    if not app_context or not app_context.feature_flags or not app_context.group_service:
        raise ValueError("app_context with feature_flags and group_service required")
    feature_flags = cast(Any, app_context.feature_flags)
    group_service = cast(Any, app_context.group_service)
    chat_id = event.chat.id

    chats_repo = ChatsRepository(session)
    await chats_repo.async_remove_user_from_chat(chat_id, event.new_chat_member.user.id)

    auto_all_enabled = feature_flags.is_enabled(chat_id, "auto_all")

    if auto_all_enabled:
        config_repo = ConfigRepository(session)
        json_str = await config_repo.async_load_bot_value(chat_id, BotValueTypes.All, "[]")
        members = json.loads(json_str) if json_str else []

        if event.from_user.username:
            username = "@" + event.from_user.username
            if username in members:
                members.remove(username)
            await config_repo.async_save_bot_value(chat_id, BotValueTypes.All, json.dumps(members))

    if event.new_chat_member.status == ChatMemberStatus.KICKED:
        actor_username = event.from_user.username if event.from_user else None
        logger.info(f"{event.old_chat_member.user} kicked from {get_chat_link(event.chat)} by {actor_username}")

        if event.from_user and event.from_user.id == bot.id:
            return

        if skyuser and skyuser.is_skynet_admin():
            c1, _ = await group_service.check_membership(bot, MTLChats.SerpicaGroup, event.old_chat_member.user.id)
            c2, _ = await group_service.check_membership(bot, MTLChats.MTLAAgoraGroup, event.old_chat_member.user.id)
            c3, _ = await group_service.check_membership(bot, MTLChats.ClubFMCGroup, event.old_chat_member.user.id)
            in_other_chats = c1 or c2 or c3

            if not in_other_chats:
                await async_add_bot_users(session, event.old_chat_member.user.id, None, 2)

        kb_unban = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="unban",
                        callback_data=UnbanCallbackData(user_id=event.new_chat_member.user.id, chat_id=chat_id).pack(),
                    )
                ]
            ]
        )
        reason = "Banned manually by chat admin"
        await bot.send_message(
            MTLChats.SpamGroup,
            build_ban_message(event.new_chat_member.user, event.chat, reason, actor=event.from_user),
            reply_markup=kb_unban,
        )


def contains_emoji(s: str) -> bool:
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"  # emoticons
        "\U0001f300-\U0001f5ff"  # symbols & pictographs
        "\U0001f680-\U0001f6ff"  # transport & map symbols
        "\U0001f1e0-\U0001f1ff"  # flags (iOS)
        "\U00002702-\U000027b0"
        "\U000024c2-\U0001f251"
        "]+",
        flags=re.UNICODE,
    )
    return bool(emoji_pattern.search(s))


@router.message(F.new_chat_members)
@router.message(F.left_chat_member)
async def msg_delete_income(message: Message, app_context=None):
    """
    # только удаляем сообщения о входе
    """
    chat_id = message.chat.id

    # Get delete_income config using DI service (app_context required)
    delete_income_config = None
    if app_context and app_context.config_service:
        delete_income_config = app_context.config_service.get_delete_income(chat_id)

    if delete_income_config is not None:
        with suppress(TelegramBadRequest):
            if delete_income_config == 2:
                if message.from_user and contains_emoji(message.from_user.full_name):
                    await message.delete()
            else:
                await message.delete()


@router.callback_query(CaptchaCallbackData.filter())
async def cq_captcha(query: CallbackQuery, callback_data: CaptchaCallbackData, bot: Bot):
    answer = callback_data.answer
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible", show_alert=True)
        return
    if query.from_user.id == answer:
        await query.answer("Thanks !", show_alert=True)
        chat = await bot.get_chat(query.message.chat.id)
        permissions = chat.permissions or ChatPermissions(can_send_messages=True)
        await bot.restrict_chat_member(
            query.message.chat.id,
            query.from_user.id,
            permissions=permissions,
            until_date=datetime.timedelta(seconds=65),
        )
        logger.info(
            "moderation_artifact action=restrict_release chat_id={} user_id={} source=captcha_v1",
            query.message.chat.id,
            query.from_user.id,
        )
    else:
        await query.answer("For other user", show_alert=True)
    await query.answer()


@router.callback_query(EmojiCaptchaCallbackData.filter())
async def cq_emoji_captcha(query: CallbackQuery, callback_data: EmojiCaptchaCallbackData, bot: Bot):
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible", show_alert=True)
        return
    if query.from_user.id == callback_data.user_id:
        index = emoji_pairs[1].index(callback_data.square)
        if get_last_digit_of_sum(callback_data.num) == index:
            await query.answer("Thanks !", show_alert=True)
            chat = await bot.get_chat(query.message.chat.id)
            permissions = chat.permissions or ChatPermissions(can_send_messages=True)
            await bot.restrict_chat_member(
                query.message.chat.id,
                query.from_user.id,
                permissions=permissions,
                until_date=datetime.timedelta(seconds=65),
            )
            logger.info(
                "moderation_artifact action=restrict_release chat_id={} user_id={} source=captcha_v2",
                query.message.chat.id,
                query.from_user.id,
            )
        else:
            await query.answer("Wrong answer", show_alert=True)
            logger.info(
                "moderation_artifact action=captcha_wrong_answer chat_id={} user_id={} source=captcha_v2",
                query.message.chat.id,
                query.from_user.id,
            )
            original_text = query.message.html_text or query.message.text or ""
            clean_text = strip_emoji_captcha_lines(original_text)
            wrong_answer_notice = (
                "Ответ неверный. Если вы считаете, что это ошибка, напишите администрации: @mtl_helper_bot\n\n"
                "Wrong answer. If you believe this is a mistake, contact admins: @mtl_helper_bot"
            )
            wrong_answer_text = f"{clean_text}\n\n{wrong_answer_notice}" if clean_text else wrong_answer_notice
            try:
                await query.message.edit_text(
                    wrong_answer_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=None,
                )
            except TelegramBadRequest as e:
                logger.warning(
                    "captcha wrong-answer edit failed chat={} user={} err={}",
                    query.message.chat.id,
                    query.from_user.id,
                    e,
                )
                with suppress(TelegramBadRequest):
                    await query.message.delete_reply_markup()
    else:
        await query.answer("For other user", show_alert=True)


@router.message(Command(commands=["recaptcha"]))
async def cmd_recaptcha(
    message: Message,
    session: AsyncSession,
    app_context: Any = None,
    skyuser: SkyUser | None = None,
):
    if not app_context or not app_context.utils_service:
        raise ValueError("app_context with utils_service required")
    utils_service = cast(Any, app_context.utils_service)
    admin = await skyuser.is_admin() if skyuser else False

    if not admin:
        text = skyuser.admin_denied_text() if skyuser else "You are not admin."
        await message.reply(text)
        return None

    if len((message.text or "").split()) < 2:
        msg = await message.reply("need more words")
        await utils_service.sleep_and_delete(msg)
        return None

    await message.answer(
        " ".join((message.text or "").split(" ")[1:]),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Get Captcha", callback_data="ReCaptcha")]]
        ),
    )
    await message.delete()
    return None


@router.callback_query(F.data == "ReCaptcha")
async def cq_recaptcha(query: CallbackQuery, session: AsyncSession, bot: Bot, app_context: Any = None):
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible", show_alert=True)
        return
    await new_chat_member(
        ChatMemberUpdated(
            chat=query.message.chat,
            from_user=query.from_user,
            new_chat_member=ChatMemberMember(user=query.from_user),
            old_chat_member=ChatMemberMember(user=query.from_user),
            date=query.message.date,
        ),
        session,
        bot,
        app_context=app_context,
    )
    await query.answer()


@router.chat_member(ChatMemberUpdatedFilter(PROMOTED_TRANSITION))
@router.chat_member(ChatMemberUpdatedFilter(ADMINISTRATOR >> MEMBER))
async def cmd_update_admin(event: ChatMemberUpdated, session: AsyncSession, bot: Bot, app_context: Any = None):
    if not app_context or not app_context.admin_service:
        raise ValueError("app_context with admin_service required")
    admin_service = cast(Any, app_context.admin_service)
    chat_id = event.chat.id

    # Chat is accessible if we received this update - remove from inaccessible list
    from routers.admin_panel import async_unmark_chat_accessible

    await async_unmark_chat_accessible(chat_id, app_context)

    members = await event.chat.get_administrators()
    new_admins = [member.user.id for member in members]

    admin_service.set_chat_admins(chat_id, new_admins)
    config_repo = ConfigRepository(session)
    await config_repo.async_save_bot_value(chat_id, BotValueTypes.Admins, json.dumps(new_admins))


@router.chat_join_request()
async def handle_chat_join_request(chat_join_request: ChatJoinRequest, bot: Bot, app_context: Any = None):
    if not app_context or not app_context.notification_service or not app_context.feature_flags:
        raise ValueError("app_context with notification_service and feature_flags required")
    notification_service = cast(Any, app_context.notification_service)
    feature_flags = cast(Any, app_context.feature_flags)
    chat_id = chat_join_request.chat.id
    user_id = chat_join_request.from_user.id

    info_chat_id = notification_service.get_join_notify_config(chat_id)

    if info_chat_id:
        username = get_username_link(chat_join_request.from_user)

        kb_join = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Принять",
                        callback_data=JoinCallbackData(user_id=user_id, chat_id=chat_id, can_join=True).pack(),
                    ),
                    InlineKeyboardButton(
                        text="Отказать",
                        callback_data=JoinCallbackData(user_id=user_id, chat_id=chat_id, can_join=False).pack(),
                    ),
                ]
            ]
        )

        if len(str(info_chat_id)) > 5:
            await bot.send_message(
                info_chat_id,
                f'Новый участник {username} хочет присоединиться к чату "{chat_join_request.chat.title}". '
                f"Требуется подтверждение.",
                reply_markup=kb_join,
            )
        else:
            await bot.send_message(
                chat_id,
                f"Новый участник {username} хочет присоединиться к чату. Требуется подтверждение.",
                reply_markup=kb_join,
            )

        join_request_captcha_enabled = feature_flags.is_enabled(chat_id, "join_request_captcha")

        if join_request_captcha_enabled:
            with suppress(TelegramBadRequest, TelegramForbiddenError):
                edit_button_url = f"https://t.me/myMTLbot/JoinCaptcha?startapp={chat_id}"

                # Создаем клавиатуру с кнопками
                reply_markup = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Start Captcha v1", url=edit_button_url + "_1")],
                        [InlineKeyboardButton(text="Start Captcha v2", url=edit_button_url + "_2")],
                    ]
                )
                await bot.send_message(
                    chat_id=chat_join_request.user_chat_id,
                    text=f"К сожалению из-за натиска ботов в чат добавляются только "
                    f"те кто прошел проверку. \n\n"
                    f"Для того чтоб зайти в чат '{chat_join_request.chat.title}' вам "
                    f"надо нажать на одну из кнопок ниже и подтвердить что вы человек. ",
                    reply_markup=reply_markup,
                )

    # Optional: Auto-approve join request
    # await bot.approve_chat_join_request(chat_id, user_id)


@router.callback_query(JoinCallbackData.filter())
async def cq_join(
    query: CallbackQuery,
    callback_data: JoinCallbackData,
    bot: Bot,
    app_context: Any = None,
    skyuser: SkyUser | None = None,
):
    admin = await skyuser.is_admin(callback_data.chat_id) if skyuser else False

    if not admin:
        text = skyuser.admin_denied_text() if skyuser else "You are not admin."
        await query.answer(text, show_alert=True)
        return False

    if callback_data.can_join:
        with suppress(TelegramBadRequest):
            await bot.approve_chat_join_request(callback_data.chat_id, callback_data.user_id)
        await query.answer("✅")
        if isinstance(query.message, Message):
            await query.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text=f"✅ {query.from_user.username}", callback_data="👀")]]
                )
            )

    else:
        await bot.decline_chat_join_request(callback_data.chat_id, callback_data.user_id)
        await query.answer("❌")
        if isinstance(query.message, Message):
            await query.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text=f"❌ {query.from_user.username}", callback_data="👀")]]
                )
            )

    # await query.answer("Ready !", show_alert=True)


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router welcome was loaded")


if __name__ == "__main__":
    print(create_emoji_captcha_keyboard(1, 0))
