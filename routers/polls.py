import json
import math
from contextlib import suppress
from typing import Any, cast

from aiogram import Router, Bot, F
from loguru import logger
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    PollAnswer,
    ReactionTypeEmoji,
    MessageOriginChannel,
)
from sqlalchemy.ext.asyncio import AsyncSession

from other.constants import MTLChats, BotValueTypes
from services.command_registry_service import update_command_info
from services.app_context import AppContext
from services.skyuser import SkyUser
from other.grist_tools import MTLGrist
from shared.domain.stellar_addresses import MTLAddresses
from db.repositories import ConfigRepository

router = Router()


class PollCallbackData(CallbackData, prefix="poll"):
    answer: int


empty_poll = '{"closed": true, "question": "", "options": []}'

# we have dict with votes for different chats
chat_to_address = {
    -1001649743884: MTLAddresses.public_issuer,
    -1001837984392: MTLAddresses.public_issuer,
    MTLChats.TestGroup: MTLAddresses.public_issuer,
    MTLChats.USDMMGroup: MTLAddresses.public_usdm,
    -1002210483308: MTLAddresses.public_issuer,  # -1002210483308 тестовый канал
    -1002042260878: MTLAddresses.public_mtla,
}


@router.channel_post(F.poll)
async def channel_post(message: Message, session: AsyncSession, app_context: AppContext):
    if not app_context or not app_context.poll_service:
        raise ValueError("app_context with poll_service required")
    poll_service = cast(Any, app_context.poll_service)
    if message.chat.id in (-1001649743884, -1001837984392, -1002042260878, -1002210483308):
        if message.poll:
            buttons = []
            my_buttons = []
            my_poll = {}
            for option in message.poll.options:
                my_buttons.append([option.text, 0, []])
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=option.text + "(0)", callback_data=PollCallbackData(answer=len(buttons)).pack()
                        )
                    ]
                )
            msg = await message.answer(
                message.poll.question, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            my_poll["question"] = message.poll.question
            my_poll["closed"] = False
            my_poll["message_id"] = msg.message_id
            my_poll["buttons"] = my_buttons

            await poll_service.save_poll(session, message.chat.id, msg.message_id, my_poll)


@update_command_info("/poll", "Создать голование с учетом веса голосов, надо слать в ответ на стандартное голосование")
@router.message(Command(commands=["poll"]))
async def cmd_poll(message: Message, session: AsyncSession, app_context: AppContext):
    if not app_context or not app_context.poll_service:
        raise ValueError("app_context with poll_service required")
    poll_service = cast(Any, app_context.poll_service)
    if message.reply_to_message and message.reply_to_message.poll:
        poll = message.reply_to_message.poll
        buttons = []
        my_buttons = []
        my_poll = {}
        for option in poll.options:
            my_buttons.append([option.text, 0, []])
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=option.text + "(0)", callback_data=PollCallbackData(answer=len(buttons)).pack()
                    )
                ]
            )
        msg = await message.answer(poll.question, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        my_poll["question"] = poll.question
        my_poll["closed"] = False
        my_poll["message_id"] = msg.message_id
        my_poll["buttons"] = my_buttons

        await poll_service.save_poll(session, message.chat.id, msg.message_id, my_poll)
    else:
        await message.answer("Требуется в ответ на голосование")


@update_command_info(
    "/poll_replace_text",
    "Заменить в спец голосовании текст на предлагаемый далее. Использовать /poll_replace_text new_text",
)
@router.message(Command(commands=["poll_replace_text"]))
async def cmd_poll_rt(message: Message, session: AsyncSession, app_context: AppContext):
    if not app_context or not app_context.poll_service:
        raise ValueError("app_context with poll_service required")
    poll_service = cast(Any, app_context.poll_service)
    if message.reply_to_message:
        my_poll = await poll_service.load_poll(session, message.chat.id, message.reply_to_message.message_id)
        command_text = message.text or ""

        if my_poll["closed"]:
            await message.reply("This poll is closed!")
        else:
            my_poll["question"] = command_text[len("/poll_replace_text ") :]

            await poll_service.save_poll(session, message.chat.id, message.reply_to_message.message_id, my_poll)
    else:
        await message.answer("Требуется в ответ на голосование")


@update_command_info("/poll_close", "Закрыть голосование. после этого нельзя голосовать или менять его.")
@router.message(Command(commands=["poll_close"]))
@router.message(Command(commands=["poll_stop"]))
@router.message(Command(commands=["apoll_stop"]))
async def cmd_poll_close(message: Message, session: AsyncSession, bot: Bot, app_context: AppContext):
    if not app_context or not app_context.poll_service:
        raise ValueError("app_context with poll_service required")
    poll_service = cast(Any, app_context.poll_service)
    if message.reply_to_message and message.reply_to_message.poll:
        await bot.stop_poll(message.chat.id, message.reply_to_message.message_id)
        return

    if message.reply_to_message:
        if message.reply_to_message.forward_from_chat and message.reply_to_message.forward_from_message_id:
            message_id = message.reply_to_message.forward_from_message_id
        else:
            message_id = message.reply_to_message.message_id

        my_poll = await poll_service.load_poll(session, message.chat.id, message_id)

        if my_poll["closed"]:
            await message.reply("This poll is closed!")
        else:
            my_poll["closed"] = True

            await poll_service.save_poll(session, message.chat.id, message_id, my_poll)
    else:
        await message.answer("Требуется в ответ на голосование")


@update_command_info(
    "/poll_check",
    "Проверить кто не голосовал. Слать в ответ на спец голосование. "
    "'кто молчит', 'найди молчунов', 'найди безбилетника'",
)
@router.message(Command(commands=["poll_check"]))
async def cmd_poll_check(message: Message, session: AsyncSession, app_context: AppContext):
    if not app_context or not app_context.poll_service or not app_context.voting_service:
        raise ValueError("app_context with poll_service and voting_service required")
    poll_service = cast(Any, app_context.poll_service)
    voting_service = cast(Any, app_context.voting_service)
    chat_id = message.chat.id

    if message.reply_to_message:
        # Original logic used negated ID in mongo
        # Our service load_poll uses -1 * message_id
        # Here we need to manually handle or adjust service.
        # Let's keep it simple for now as it's a specific case.
        forward_origin = message.reply_to_message.forward_origin
        if isinstance(forward_origin, MessageOriginChannel):
            actual_chat_id = forward_origin.chat.id
            actual_msg_id = forward_origin.message_id
        else:
            actual_chat_id = chat_id
            actual_msg_id = message.reply_to_message.message_id

        my_poll = await poll_service.load_poll(session, actual_chat_id, actual_msg_id)

        address_key = chat_to_address.get(actual_chat_id)
        votes_detail = voting_service.get_vote_weights(address_key) if address_key else None
        if address_key and votes_detail:
            all_voters = set(votes_detail.keys())
            with suppress(KeyError):
                all_voters.remove("NEED")

            buttons = my_poll.get("buttons")
            if isinstance(buttons, list):
                for button in buttons:
                    if isinstance(button, list) and len(button) > 2 and isinstance(button[2], list):
                        for voter in button[2]:
                            if not isinstance(voter, str):
                                continue
                            normalized_voter = voter.strip("'")
                            if normalized_voter in all_voters:
                                all_voters.remove(normalized_voter)

            remaining_voters = " ".join(all_voters)
            await message.reply_to_message.reply(f"{remaining_voters}\nСмотрите голосование / Look at the poll")
        else:
            await message.reply_to_message.reply(
                "Данные голосования не найдены или ключ чата отсутствует в chat_to_address"
            )
    else:
        await message.answer("Требуется в ответ на голосование или пересланное голосование из канала")


@router.callback_query(PollCallbackData.filter())
async def cq_join_list(query: CallbackQuery, callback_data: PollCallbackData, app_context: AppContext):
    if not app_context or not app_context.poll_service or not app_context.voting_service:
        raise ValueError("app_context with poll_service and voting_service required")
    poll_service = cast(Any, app_context.poll_service)
    voting_service = cast(Any, app_context.voting_service)
    if not isinstance(query.message, Message):
        await query.answer("Message is not accessible", show_alert=True)
        return False

    answer = callback_data.answer
    user_key = f"@{query.from_user.username.lower()}" if query.from_user.username else str(query.from_user.id)

    my_poll = await poll_service.load_poll(None, query.message.chat.id, query.message.message_id)

    if my_poll["closed"]:
        await query.answer("This poll is closed!", show_alert=True)
    else:
        address = chat_to_address.get(query.message.chat.id)
        local_votes = voting_service.get_vote_weights(address) if address else None
        if not local_votes:
            await query.answer("No vote data for this chat", show_alert=True)
            return False

        need_close = False
        buttons = my_poll.get("buttons")
        if not isinstance(buttons, list) or answer < 0 or answer >= len(buttons):
            await query.answer("Poll data is invalid", show_alert=True)
            return False
        if user_key in local_votes:
            vote_weight_raw = local_votes.get(user_key)
            vote_weight = int(vote_weight_raw) if isinstance(vote_weight_raw, (int, float)) else 0
            if vote_weight <= 0:
                await query.answer("Vote weight is invalid", show_alert=True)
                return False

            current_button = buttons[answer]
            if not (
                isinstance(current_button, list) and len(current_button) > 2 and isinstance(current_button[2], list)
            ):
                await query.answer("Poll data is invalid", show_alert=True)
                return False
            if user_key in current_button[2]:
                current_button[1] -= vote_weight
                current_button[2].remove(user_key)
            else:
                current_button[1] += vote_weight
                current_button[2].append(user_key)
                need_votes = (
                    local_votes.get("NEED", {}).get("75") if isinstance(local_votes.get("NEED"), dict) else None
                )
                if isinstance(need_votes, (int, float)) and current_button[1] >= need_votes:
                    need_close = True
            msg = my_poll["question"] + "\n\n"
            buttons = []
            for idx, button in enumerate(my_poll["buttons"]):
                msg += f"{button[0][:3]} ({button[1]}) : {' '.join(str(v) for v in button[2])}\n"
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=button[0] + f"({button[1]})", callback_data=PollCallbackData(answer=idx).pack()
                        )
                    ]
                )
            msg += (
                f"Need {local_votes['NEED']['50']}({local_votes['NEED']['75']}) votes from {local_votes['NEED']['100']}"
            )

            await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
            if need_close:
                my_poll["closed"] = True

            await poll_service.save_poll(None, query.message.chat.id, query.message.message_id, my_poll)
        else:
            await query.answer("You are't in list!", show_alert=True)
    return True


async def cmd_save_votes(session: AsyncSession, app_context: AppContext):
    if (
        not app_context
        or not app_context.stellar_service
        or not app_context.config_service
        or not app_context.voting_service
    ):
        raise ValueError("app_context with stellar_service, config_service, and voting_service required")
    stellar_service = cast(Any, app_context.stellar_service)
    voting_service = cast(Any, app_context.voting_service)
    vote_list = {}
    for chat_id in chat_to_address:
        address = chat_to_address[chat_id]
        if address in vote_list:
            pass
        else:
            total = 0
            vote_list[address] = {}

            _, signers = await stellar_service.get_balances(address=address, return_signers=True)

            for signer in signers:
                if signer["weight"] > 0:
                    total += signer["weight"]
                    username = await stellar_service.address_id_to_username(signer["key"], full_data=True)

                    key_ = username.lower()
                    vote_list[address][key_] = signer["weight"]

            vote_list[address]["NEED"] = {"50": total // 2 + 1, "75": math.ceil(total * 0.75), "100": total}

    await ConfigRepository(session).async_save_bot_value(0, BotValueTypes.Votes, json.dumps(vote_list))
    voting_service.set_all_vote_weights(vote_list)
    return vote_list


@update_command_info("/poll_reload_vote", "Перечитать голоса из блокчейна")
@router.message(Command(commands=["poll_reload_vote"]))
async def cmd_poll_reload_vote_handler(
    message: Message, session: AsyncSession, app_context: AppContext, skyuser: SkyUser
):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False

    vote_list = await cmd_save_votes(session, app_context)
    entries_with_dots = []

    for key, value in vote_list.items():
        for sub_key in value.keys():
            if ".." in sub_key:
                entries_with_dots.append(sub_key.upper())

    if len(entries_with_dots) > 0:
        await message.reply("Список пользователей не найденых в реестрах:\n" + "\n".join(entries_with_dots))

    await message.reply("reload complete")


@update_command_info("/apoll", "Создает голосование в Ассоциации")
@router.message(Command(commands=["apoll"]))
async def cmd_apoll(message: Message, session: AsyncSession, app_context: AppContext):
    if (
        not app_context
        or not app_context.gspread_service
        or not app_context.stellar_service
        or not app_context.poll_service
    ):
        raise ValueError("app_context with gspread_service, stellar_service, and poll_service required")
    gspread_service = cast(Any, app_context.gspread_service)
    stellar_service = cast(Any, app_context.stellar_service)
    poll_service = cast(Any, app_context.poll_service)
    if message.reply_to_message and message.reply_to_message.poll:
        await message.react([ReactionTypeEmoji(emoji="👾")])
        my_poll = {}

        google_url, google_id = await gspread_service.copy_a_table(message.reply_to_message.poll.question)
        mtlap_votes = await stellar_service.get_mtlap_votes()

        options = []
        options.extend([option.text for option in message.reply_to_message.poll.options])

        await gspread_service.update_a_table_first(
            google_id, message.reply_to_message.poll.question, options, mtlap_votes
        )

        msg = await message.answer_poll(
            question=message.reply_to_message.poll.question,
            options=options,
            allows_multiple_answers=message.reply_to_message.poll.allows_multiple_answers,
            is_anonymous=message.reply_to_message.poll.is_anonymous,
        )
        msg2 = await msg.reply(f"url {google_url}\nData will be here soon", disable_web_page_preview=True)
        if not msg.poll:
            await message.answer("Не удалось создать голосование")
            return
        my_poll["poll_id"] = msg.poll.id
        my_poll["info_chat_id"] = msg2.chat.id
        my_poll["info_message_id"] = msg2.message_id
        my_poll["google_id"] = google_id
        my_poll["google_url"] = google_url

        await poll_service.save_mtla_poll(session, msg.poll.id, my_poll)

        with suppress(TelegramBadRequest):
            await message.reply_to_message.delete()
            await message.delete()
    else:
        await message.answer("Требуется в ответ на голосование")


@router.poll_answer()
async def cmd_poll_answer_handler(poll: PollAnswer, session: AsyncSession, bot: Bot, app_context: AppContext):
    if (
        not app_context
        or not app_context.poll_service
        or not app_context.grist_service
        or not app_context.gspread_service
    ):
        raise ValueError("app_context with poll_service, grist_service, and gspread_service required")
    if not poll.user:
        return
    poll_service = cast(Any, app_context.poll_service)
    grist_service = cast(Any, app_context.grist_service)
    gspread_service = cast(Any, app_context.gspread_service)
    my_poll = await poll_service.load_mtla_poll(session, poll.poll_id)
    user_address_data = await grist_service.load_table_data(MTLGrist.MTLA_USERS, filter_dict={"TGID": [poll.user.id]})

    if not user_address_data:
        with suppress(Exception):
            username = poll.user.username if poll.user.username else poll.user.id
            await bot.send_message(my_poll.get("info_chat_id", MTLChats.ITolstov), f"User @{username} not found")
        return
    else:
        user_address = user_address_data[0]["Stellar"]

    result = await gspread_service.update_a_table_vote(my_poll.get("google_id"), user_address, poll.option_ids)

    msg_text = f'<a href="{my_poll.get("google_url")}">GoogleSheets</a>\n'
    if result:
        for data in result:
            msg_text += f"{data[0]}: {data[1]}\n"

        with suppress(TelegramBadRequest):
            await bot.edit_message_text(
                chat_id=my_poll.get("info_chat_id"),
                message_id=my_poll.get("info_message_id"),
                text=msg_text,
                disable_web_page_preview=True,
            )


@update_command_info("/apoll_check", "Проверка голосования в Ассоциации")
@router.message(Command(commands=["apoll_check"]))
async def cmd_apoll_check_handler(message: Message, session: AsyncSession, app_context: AppContext):
    if not app_context or not app_context.poll_service or not app_context.gspread_service:
        raise ValueError("app_context with poll_service and gspread_service required")
    poll_service = cast(Any, app_context.poll_service)
    gspread_service = cast(Any, app_context.gspread_service)

    if message.reply_to_message and message.reply_to_message.poll:
        await message.react([ReactionTypeEmoji(emoji="👾")])

        my_poll = await poll_service.load_mtla_poll(session, message.reply_to_message.poll.id)
        google_id = my_poll.get("google_id")

        if not google_id:
            await message.reply("Таблица для этого опроса не найдена (возможно, он не был создан ботом).")
            return

        # 1. Fetch current state from Google Sheets
        result, delegates, already_voted_addresses = await gspread_service.check_vote_table(google_id)

        msg_text = " ".join(result)
        msg_text2 = " ".join(delegates)
        msg_text = f"{msg_text} \n --------- delegates --------- \n {msg_text2}"

        if result:
            with suppress(TelegramBadRequest):
                await message.reply(msg_text)
    else:
        await message.answer("Требуется в ответ на голосование")


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router polls was loaded")
