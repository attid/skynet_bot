import asyncio
import html
import json
import math
import re
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

# Weighted poll progress indicators (set on the source post/command, never posted as text).
# Channels where a posted poll is turned into a weighted poll.
WEIGHTED_POLL_CHANNELS = (-1001649743884, -1001837984392, -1002042260878, -1002210483308)

PROGRESS_EMOJI = "👀"
DONE_EMOJI = "👌"
FAILED_EMOJI = "⚠️"

VOTE_RECALC_TIMEOUT = 30
VOTE_REPORT_CHAT_ID = MTLChats.ITolstov
VOTE_REPORT_LIMIT = 20
MAX_LINK_CANDIDATES = 3
# Keeps the rendered poll under Telegram's 4096 char limit for large communities.
MESSAGE_TEXT_BUDGET = 3500
MIN_VOTERS_IN_MESSAGE_CHARS = 120
NEED_LINE_RESERVE = 80

# Serialize blockchain/Grist reloads so concurrent polls do not hammer the network.
# Created lazily: a lock bound to a dead event loop (tests, restarts) must never poison the bot.
_recount_lock: asyncio.Lock | None = None
_recount_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_recount_lock() -> asyncio.Lock:
    """
    Return a lock bound to the running loop.

    The loop is tracked explicitly: ``asyncio.Lock._loop`` stays None while nobody waits on the
    lock, so it cannot be used to detect a stale binding (a recreated lock would break exclusion).
    """
    global _recount_lock, _recount_lock_loop
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _recount_lock is None or _recount_lock_loop is not loop:
        _recount_lock = asyncio.Lock()
        _recount_lock_loop = loop
    return _recount_lock


# Mobile keyboards capitalize the first letter, so link parsing must ignore case.
_TME_PRIVATE_LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/c/(\d+)(?:/\d+)?/(\d+)/?(?:[?#]\S*)?$", re.IGNORECASE
)
# A token with a numeric message id is meant as a message link, unlike a plain channel link.
_MESSAGE_LINK_HINT_PATTERN = re.compile(r"/(?:c/\d+|@?[A-Za-z0-9_]+)/\d+", re.IGNORECASE)

_TME_PUBLIC_LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?(?!c/)@?([A-Za-z0-9_]+)(?:/\d+)?/(\d+)/?(?:[?#]\S*)?$",
    re.IGNORECASE,
)


async def _set_reaction(message: Message, emoji: str) -> None:
    """Set a reaction as a progress indicator. Failures are non-fatal (no rights in channel)."""
    try:
        await message.react([ReactionTypeEmoji(emoji=emoji)])
    except Exception as exc:
        logger.warning("cannot set reaction {} on message {}: {}", emoji, message.message_id, exc)


def _is_valid_button(button: Any) -> bool:
    """A stored option must look like [text, weight, [voters]]."""
    return isinstance(button, list) and len(button) >= 3 and isinstance(button[2], list)


def _normalize_user_key(value: Any) -> str:
    """Single source of truth for voter keys: no quotes/spaces, lowercase."""
    if isinstance(value, str):
        return value.strip(" '\t").lower()
    return str(value)


def _unresolved_user_keys(vote_list: dict | None) -> list[str]:
    """Collect unique shortened (unresolved) names from a recount result."""
    if not isinstance(vote_list, dict):
        return []
    entries: set[str] = set()
    for value in vote_list.values():
        if not isinstance(value, dict):
            continue
        for sub_key in value:
            if isinstance(sub_key, str) and ".." in sub_key:
                # Keep the entry compact: only the shortened address, no explanatory tail.
                entries.add(sub_key.split()[0].upper())
    return sorted(entries)


def _format_unresolved(entries: list[str]) -> str:
    """Format the unresolved name list with escaping and a hard length limit."""
    lines = [f"Список пользователей не найденных в реестрах ({len(entries)}):"]
    lines.extend(html.escape(entry) for entry in entries[:VOTE_REPORT_LIMIT])
    if len(entries) > VOTE_REPORT_LIMIT:
        lines.append(f"... ещё {len(entries) - VOTE_REPORT_LIMIT}")
    return "\n".join(lines)


async def _notify_admin_unresolved(bot: Bot, vote_list: dict, context: str) -> None:
    """Report unresolved voters to the admin DM only. Never posts to the source chat."""
    entries = _unresolved_user_keys(vote_list)
    if not entries:
        return
    await _send_admin_message(bot, f"{html.escape(context)}\n{_format_unresolved(entries)}")


async def _notify_admin_failure(bot: Bot, context: str) -> None:
    """Tell the admin that weights could not be refreshed before the poll was created."""
    text = (
        f"{html.escape(context)}\n"
        "Пересчёт весов не удался (таймаут или ошибка блокчейна/Grist). "
        "Опрос создан на предыдущих весах, проверьте их через /poll_reload_vote."
    )
    await _send_admin_message(bot, text)


async def _send_admin_message(bot: Bot, text: str) -> None:
    """Send a service message to the admin DM; never break the poll flow because of a blocked bot."""
    try:
        await bot.send_message(VOTE_REPORT_CHAT_ID, text)
    except Exception as exc:
        logger.warning("cannot notify admin {}: {}", VOTE_REPORT_CHAT_ID, exc)


async def _recount_vote_weights(app_context: AppContext) -> dict | None:
    """
    Recalculate weighted votes right before a poll is created.

    Returns the vote list on success and None when the reload failed or timed out.
    Timeout also covers waiting for the lock, so concurrent poll creation stays bounded.
    """
    try:
        async with asyncio.timeout(VOTE_RECALC_TIMEOUT):
            return await cmd_save_votes(app_context)
    except TimeoutError:
        logger.warning("vote weights recount timed out after {}s", VOTE_RECALC_TIMEOUT)
    except Exception:
        logger.exception("vote weights recount failed")
    return None


def _recalculate_button_weights(buttons: list, local_votes: dict) -> tuple[list[tuple[str, int, int]], list[str]]:
    """
    Rebuild every option sum from the stored voter list using the current weights.

    Returns tuples of (option_text, before, after) plus names that lost their weight.
    """
    report: list[tuple[str, int, int]] = []
    lost_weight: list[str] = []
    for button in buttons:
        if not _is_valid_button(button):
            continue
        try:
            before = int(button[1])
        except (TypeError, ValueError):
            before = 0
        total = 0
        normalized_users: dict[str, None] = {}
        for user in button[2]:
            if not isinstance(user, (str, int)) or (isinstance(user, str) and not user.strip()):
                continue
            # Stored names come from older polls too: they may carry quotes, spaces or odd casing.
            user_key = _normalize_user_key(user)
            if not user_key:
                continue
            if user_key in normalized_users:
                # A duplicated voter must not inflate the option sum.
                continue
            normalized_users[user_key] = None
            raw_weight = local_votes.get(user_key)
            weight = int(raw_weight) if isinstance(raw_weight, (int, float)) else 0
            if weight > 0:
                total += weight
            else:
                lost_weight.append(user_key)
        button[1] = total
        # Normalized names are written back, otherwise the click handler cannot toggle
        # the voter off again (it compares the raw stored name with a normalized key).
        button[2] = list(normalized_users)
        report.append((str(button[0]), before, total))
    return report, lost_weight


def _render_poll_view(my_poll: dict, local_votes: dict) -> tuple[str, InlineKeyboardMarkup]:
    """Render the weighted poll message the same way the click handler does."""
    # Bot-wide parse mode is HTML, so every dynamic part must be escaped.
    text = html.escape(str(my_poll.get("question", ""))) + "\n\n"
    keyboard = []
    raw_buttons = my_poll["buttons"]
    valid_indexes = [idx for idx, button in enumerate(raw_buttons) if _is_valid_button(button)]
    # Reserve room for the trailing "Need ..." line and keep the whole text under the limit.
    budget = MESSAGE_TEXT_BUDGET - len(text) - NEED_LINE_RESERVE
    for position, idx in enumerate(valid_indexes):
        button = raw_buttons[idx]
        label = str(button[0])
        suffix = f"({button[1]})"
        # Telegram limits button text to 64 characters.
        button_text = f"{label[: max(0, 64 - len(suffix))]}{suffix}"
        prefix = f"{html.escape(label[:3])} {suffix} : "
        voter_names = [str(v) for v in button[2]]
        allowed = max(MIN_VOTERS_IN_MESSAGE_CHARS, budget // max(1, len(valid_indexes) - position))
        voters = ""
        shown = 0
        for name in voter_names:
            candidate = f"{voters} {name}".strip()
            if len(prefix) + len(candidate) + 12 > allowed:
                break
            voters = candidate
            shown += 1
        if shown < len(voter_names):
            voters += f" +{len(voter_names) - shown}"
        line = f"{prefix}{html.escape(voters)}\n"
        budget -= len(line)
        text += line
        keyboard.append([InlineKeyboardButton(text=button_text, callback_data=PollCallbackData(answer=idx).pack())])
    raw_need = local_votes.get("NEED")
    need: dict = raw_need if isinstance(raw_need, dict) else {}
    text += f"Need {need.get('50', 0)}({need.get('75', 0)}) votes from {need.get('100', 0)}"
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


async def _parse_poll_link(bot: Bot, link: str) -> tuple[int, int] | None:
    """Parse a t.me message link into (chat_id, message_id)."""
    private_match = _TME_PRIVATE_LINK_PATTERN.match(link)
    if private_match:
        return int(f"-100{private_match.group(1)}"), int(private_match.group(2))

    public_match = _TME_PUBLIC_LINK_PATTERN.match(link)
    if not public_match:
        return None

    username = public_match.group(1)
    try:
        chat = await bot.get_chat(f"@{username}")
    except Exception as exc:
        logger.warning("cannot resolve public chat @{}: {}", username, exc)
        return None
    return chat.id, int(public_match.group(2))


def _link_candidates(message: Message) -> list[str]:
    """Collect telegram link candidates from formatted entities and plain text tokens."""
    candidates: list[str] = []
    source_text = message.text or message.caption or ""
    for entity in (message.entities or []) + (message.caption_entities or []):
        entity_url = getattr(entity, "url", None)
        if entity_url:
            candidates.append(entity_url)
        elif getattr(entity, "type", None) == "url":
            # Entity offsets are UTF-16 based, extract_from decodes them correctly.
            candidates.append(entity.extract_from(source_text))
    parts = (message.text or message.caption or "").split(maxsplit=1)
    if len(parts) >= 2:
        # Admins paste links with comments or wrapped as "< link >".
        candidates.extend(token.strip("<>'\"()[],. ") for token in parts[1].split())
    unique: dict[str, None] = {}
    for token in candidates:
        clean = token.strip("<>'\"()[],. ")
        if ("t.me" in clean.lower() or "telegram.me" in clean.lower()) and clean not in unique:
            unique[clean] = None
    return list(unique)


async def _resolve_poll_key(bot: Bot, message: Message) -> tuple[int, int] | None:
    """
    Resolve (chat_id, message_id) of a stored weighted poll.

    An explicit t.me link argument wins; otherwise a reply to a forwarded channel post is used
    (same approach as /poll_check).
    """
    # Telegram link candidates: formatted entities first, then plain text tokens.
    # The number of resolutions is capped, every public link costs a Telegram API call.
    broken_link = False
    for token in _link_candidates(message)[:MAX_LINK_CANDIDATES]:
        link_key = await _parse_poll_link(bot, token)
        if link_key:
            return link_key
        if _MESSAGE_LINK_HINT_PATTERN.search(token):
            # A message link was given but it does not point at a poll: never recount a random one.
            broken_link = True
    if broken_link:
        return None

    reply = message.reply_to_message
    if reply is not None:
        forward_origin = reply.forward_origin
        if isinstance(forward_origin, MessageOriginChannel):
            return forward_origin.chat.id, forward_origin.message_id
        # Weighted polls live in groups/channels only, a plain reply in DM cannot point to one.
        if message.chat.type != "private":
            return message.chat.id, reply.message_id
    return None


def _format_initial_text(question: str, local_votes: dict | None) -> str:
    """Question plus current thresholds, so the poll shows fresh NEED right away."""
    text = html.escape(str(question or ""))
    raw_need = local_votes.get("NEED") if isinstance(local_votes, dict) else None
    need: dict = raw_need if isinstance(raw_need, dict) else {}
    if need:
        text += f"\n\nNeed {need.get('50', 0)}({need.get('75', 0)}) votes from {need.get('100', 0)}"
    return text


def _local_votes_for_chat(app_context: AppContext, chat_id: int) -> dict | None:
    """Current weights for the chat, from memory: valid both after a recount and after a failed one."""
    address = chat_to_address.get(chat_id)
    voting_service = getattr(app_context, "voting_service", None)
    if not address or not voting_service:
        return None
    return voting_service.get_vote_weights(address)


async def _publish_weighted_poll(
    message: Message,
    bot: Bot,
    poll: Any,
    local_votes: dict | None,
    chat_id: int,
    poll_service: Any,
    notify_admin: bool = True,
) -> bool:
    """Create the button message and persist the poll; returns False when publishing failed."""
    buttons = []
    my_buttons = []
    for option in poll.options:
        my_buttons.append([option.text, 0, []])
        suffix = f"({0})"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{option.text[: max(0, 64 - len(suffix))]}{suffix}",
                    callback_data=PollCallbackData(answer=len(buttons)).pack(),
                )
            ]
        )
    msg: Message | None = None
    try:
        msg = await message.answer(
            _format_initial_text(poll.question, local_votes),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        my_poll = {"question": poll.question, "closed": False, "message_id": msg.message_id, "buttons": my_buttons}
        # Committed in its own session: the buttons are clickable before the handler ends,
        # and a later handler failure must not leave a poll in the chat that is missing in the DB.
        await poll_service.save_poll(None, chat_id, msg.message_id, my_poll)
    except Exception:
        logger.exception("cannot publish weighted poll in chat {}", chat_id)
        if msg is not None:
            # The poll is not stored, so its buttons would only answer "This poll is closed!".
            with suppress(Exception):
                await msg.delete()
        if notify_admin:
            await _set_reaction(message, FAILED_EMOJI)
            await _send_admin_message(bot, "Опрос не создан: не удалось отправить или сохранить. Подробности в логах.")
        return False
    return True


async def _create_weighted_poll(
    message: Message,
    bot: Bot,
    poll: Any,
    app_context: AppContext,
    poll_service: Any,
    context: str,
) -> bool:
    """Recount weights, publish the poll and report the outcome (used by channel and chat paths)."""
    await _set_reaction(message, PROGRESS_EMOJI)
    vote_list = await _recount_vote_weights(app_context)
    published = await _publish_weighted_poll(
        message,
        bot,
        poll,
        _local_votes_for_chat(app_context, message.chat.id),
        message.chat.id,
        poll_service,
    )
    if not published:
        return False
    await _set_reaction(message, DONE_EMOJI if vote_list is not None else FAILED_EMOJI)
    if vote_list is not None:
        await _notify_admin_unresolved(bot, vote_list, context)
    else:
        await _notify_admin_failure(bot, context)
    return True


@router.channel_post(F.poll)
async def channel_post(message: Message, bot: Bot, app_context: AppContext):
    if not app_context or not app_context.poll_service:
        raise ValueError("app_context with poll_service required")
    poll_service = cast(Any, app_context.poll_service)
    if message.chat.id in WEIGHTED_POLL_CHANNELS:
        if message.poll:
            await _create_weighted_poll(
                message,
                bot,
                message.poll,
                app_context,
                poll_service,
                f"Пересчёт весов при создании опроса в канале {message.chat.id} (пост {message.message_id})",
            )


@update_command_info("/poll", "Создать голование с учетом веса голосов, надо слать в ответ на стандартное голосование")
@router.message(Command(commands=["poll"]))
async def cmd_poll(message: Message, bot: Bot, app_context: AppContext):
    if not app_context or not app_context.poll_service:
        raise ValueError("app_context with poll_service required")
    poll_service = cast(Any, app_context.poll_service)
    if message.reply_to_message and message.reply_to_message.poll:
        poll = message.reply_to_message.poll
        # Only chats from chat_to_address have weighted votes; any other chat must not trigger a recount.
        weighted_chat = message.chat.id in chat_to_address
        if weighted_chat:
            await _create_weighted_poll(
                message,
                bot,
                poll,
                app_context,
                poll_service,
                context=f"Создание опроса в чате {message.chat.id}",
            )
        else:
            await _publish_weighted_poll(
                message,
                bot,
                poll,
                None,
                message.chat.id,
                poll_service,
                notify_admin=False,
            )
    else:
        await message.answer("Требуется в ответ на голосование")


@update_command_info(
    "/poll_replace_text",
    "Заменить в спец голосовании текст на предлагаемый далее. Использовать /poll_replace_text new_text",
)
@router.message(Command(commands=["poll_replace_text"]))
async def cmd_poll_rt(message: Message, app_context: AppContext):
    if not app_context or not app_context.poll_service:
        raise ValueError("app_context with poll_service required")
    poll_service = cast(Any, app_context.poll_service)
    if message.reply_to_message:
        my_poll = await poll_service.load_poll(None, message.chat.id, message.reply_to_message.message_id)
        command_text = message.text or ""

        if my_poll["closed"]:
            await message.reply("This poll is closed!")
        else:
            my_poll["question"] = command_text[len("/poll_replace_text ") :]

            await poll_service.save_poll(None, message.chat.id, message.reply_to_message.message_id, my_poll)
    else:
        await message.answer("Требуется в ответ на голосование")


@update_command_info("/poll_close", "Закрыть голосование. после этого нельзя голосовать или менять его.")
@router.message(Command(commands=["poll_close"]))
@router.message(Command(commands=["poll_stop"]))
@router.message(Command(commands=["apoll_stop"]))
async def cmd_poll_close(message: Message, bot: Bot, app_context: AppContext):
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

        my_poll = await poll_service.load_poll(None, message.chat.id, message_id)

        if my_poll["closed"]:
            await message.reply("This poll is closed!")
        else:
            my_poll["closed"] = True

            await poll_service.save_poll(None, message.chat.id, message_id, my_poll)
    else:
        await message.answer("Требуется в ответ на голосование")


@update_command_info(
    "/poll_check",
    "Проверить кто не голосовал. Слать в ответ на спец голосование. "
    "'кто молчит', 'найди молчунов', 'найди безбилетника'",
)
@router.message(Command(commands=["poll_check"]))
async def cmd_poll_check(message: Message, app_context: AppContext):
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

        my_poll = await poll_service.load_poll(None, actual_chat_id, actual_msg_id)

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
            view_text, view_keyboard = _render_poll_view(my_poll, local_votes)
            await query.message.edit_text(view_text, reply_markup=view_keyboard)
            if need_close:
                my_poll["closed"] = True

            await poll_service.save_poll(None, query.message.chat.id, query.message.message_id, my_poll)
        else:
            await query.answer("You are't in list!", show_alert=True)
    return True


async def cmd_save_votes(app_context: AppContext):
    """
    Recalculate weighted votes and persist them.

    Weights are global bot state, so they are always written in their own session with an immediate
    commit: neither the request transaction nor a later handler failure can affect them.
    The lock keeps poll creation and /poll_reload_vote from hitting Horizon/Grist simultaneously.
    """
    async with _get_recount_lock():
        return await _recalculate_votes(app_context)


async def _recalculate_votes(app_context: AppContext):
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
    for address in dict.fromkeys(chat_to_address.values()):
        total = 0
        vote_list[address] = {}

        _, signers = await stellar_service.get_balances(address=address, return_signers=True)

        for signer in signers:
            if signer["weight"] > 0:
                total += signer["weight"]
                username = await stellar_service.address_id_to_username(signer["key"], full_data=True)

                key_ = _normalize_user_key(username)
                vote_list[address][key_] = signer["weight"]

        vote_list[address]["NEED"] = {
            "50": total // 2 + 1 if total else 0,
            "75": math.ceil(total * 0.75) if total else 0,
            "100": total,
        }

    from db.session import AsyncSessionPool

    async with AsyncSessionPool() as owned_session:
        await ConfigRepository(owned_session).async_save_bot_value(0, BotValueTypes.Votes, json.dumps(vote_list))
        await owned_session.commit()
    voting_service.set_all_vote_weights(vote_list)
    return vote_list


@update_command_info("/poll_reload_vote", "Перечитать голоса из блокчейна")
@router.message(Command(commands=["poll_reload_vote"]))
async def cmd_poll_reload_vote_handler(
    message: Message,
    app_context: AppContext,
    skyuser: SkyUser,
):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False

    try:
        # Bounded: a hung Horizon call must not keep the recount lock forever.
        async with asyncio.timeout(VOTE_RECALC_TIMEOUT):
            vote_list = await cmd_save_votes(app_context)
    except TimeoutError:
        logger.warning("poll_reload_vote timed out after {}s", VOTE_RECALC_TIMEOUT)
        await message.reply("Не удалось обновить веса: таймаут, попробуйте позже")
        return False
    except Exception as exc:
        logger.exception("poll_reload_vote failed")
        await message.reply(f"Не удалось обновить веса: {html.escape(str(exc))}")
        return False

    entries_with_dots = _unresolved_user_keys(vote_list)

    if len(entries_with_dots) > 0:
        await message.reply(_format_unresolved(entries_with_dots))

    await message.reply("reload complete")


@update_command_info(
    "/poll_recount", "Пересчитать веса в опросе по актуальным весам (ответ на пересланный из канала опрос или ссылка)"
)
@router.message(Command(commands=["poll_recount"]))
async def cmd_poll_recount_handler(
    message: Message,
    bot: Bot,
    app_context: AppContext,
    skyuser: SkyUser,
):
    if not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False

    if not app_context or not app_context.poll_service or not app_context.voting_service:
        raise ValueError("app_context with poll_service and voting_service required")
    poll_service = cast(Any, app_context.poll_service)
    voting_service = cast(Any, app_context.voting_service)

    poll_key = await _resolve_poll_key(bot, message)
    if not poll_key:
        await message.reply(
            "Нужен ответ на пересланный из канала опрос или ссылка на сообщение с кнопками. "
            "Для опросов из групп/супергрупп пересылка не сохраняет исходный id — используйте ссылку: "
            "/poll_recount https://t.me/c/1234567890/42"
        )
        return False

    chat_id, message_id = poll_key
    address = chat_to_address.get(chat_id)
    if not address:
        await message.reply(f"Чат {chat_id} не поддерживает взвешенные голосования")
        return False

    my_poll = await poll_service.load_poll(None, chat_id, message_id)
    if not isinstance(my_poll, dict) or not isinstance(my_poll.get("buttons"), list) or not my_poll["buttons"]:
        await message.reply(f"Опрос не найден: chat_id={chat_id}, message_id={message_id}")
        return False

    # Closed polls are never touched, no matter what.
    if my_poll.get("closed"):
        await message.reply("Голосование закрыто, ничего не меняю.")
        return False

    local_votes = voting_service.get_vote_weights(address)
    if not local_votes:
        await message.reply("Нет данных о весах для этого чата, сначала обновите их через /poll_reload_vote")
        return False

    report, lost_weight = _recalculate_button_weights(my_poll["buttons"], local_votes)
    if not report:
        # Rewriting a poll with no valid option would wipe its buttons in Telegram.
        await message.reply("В опросе нет валидных кнопок для пересчёта, ничего не меняю.")
        return False
    # Saved in its own committed session: a failed message edit must never roll the recount back.
    await poll_service.save_poll(None, chat_id, message_id, my_poll)

    lines = [f"{option}: {before} → {after}" for option, before, after in report]
    text = "Пересчёт весов:\n" + "\n".join(lines)
    lost_names = sorted(set(lost_weight))
    if lost_names:
        text += f"\nОбнулены (нет веса): {', '.join(lost_names[:VOTE_REPORT_LIMIT])}"
        if len(lost_names) > VOTE_REPORT_LIMIT:
            text += f" ... ещё {len(lost_names) - VOTE_REPORT_LIMIT}"

    view_text, view_keyboard = _render_poll_view(my_poll, local_votes)
    edit_status = "updated"
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=view_text,
            reply_markup=view_keyboard,
        )
        text += "\nСообщение обновлено."
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            edit_status = "not_modified"
            text += "\nСообщение уже содержит актуальные данные."
        else:
            edit_status = "failed"
            logger.warning("poll recount: cannot edit message chat_id={} message_id={}: {}", chat_id, message_id, exc)
            text += "\nПересчёт сохранён, но сообщение обновить не удалось."
    except Exception as exc:
        # 403/404/429, network errors: none of them may break an already saved recount.
        edit_status = "failed"
        logger.warning("poll recount: cannot edit message chat_id={} message_id={}: {}", chat_id, message_id, exc)
        text += "\nПересчёт сохранён, но сообщение обновить не удалось."

    logger.info(
        "poll recount chat_id={} message_id={} report={} lost={} edit={}",
        chat_id,
        message_id,
        report,
        lost_names,
        edit_status,
    )
    await message.reply(html.escape(text))


@update_command_info("/apoll", "Создает голосование в Ассоциации")
@router.message(Command(commands=["apoll"]))
async def cmd_apoll(message: Message, app_context: AppContext):
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

        await poll_service.save_mtla_poll(None, msg.poll.id, my_poll)

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
async def cmd_apoll_check_handler(message: Message, app_context: AppContext):
    if not app_context or not app_context.poll_service or not app_context.gspread_service:
        raise ValueError("app_context with poll_service and gspread_service required")
    poll_service = cast(Any, app_context.poll_service)
    gspread_service = cast(Any, app_context.gspread_service)

    if message.reply_to_message and message.reply_to_message.poll:
        await message.react([ReactionTypeEmoji(emoji="👾")])

        my_poll = await poll_service.load_mtla_poll(None, message.reply_to_message.poll.id)
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
