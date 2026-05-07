"""Self-moderation router: vote-based join/mute/kick handling.

Wires aiogram events to ``SelfmodService``:
- Join vote is started from ``routers/welcome.py`` via ``begin_join_vote``.
- Mute vote is started by a 👾 reaction on a chat message (handled here).
- Vote callbacks tally yes/no and apply outcomes (lift/ban/mute/kick).
- Every lifecycle event is logged to ``MTLChats.SpamGroup``.
"""

from __future__ import annotations

import html
from contextlib import suppress
from datetime import datetime
from typing import Any, cast

from aiogram import Router, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageReactionUpdated,
    ReactionTypeEmoji,
    User,
)
from loguru import logger
from sqlalchemy.orm import Session

from db.repositories import ConfigRepository
from other.aiogram_tools import ChatInOption, get_username_link
from other.constants import BotValueTypes, MTLChats
from services.app_context import AppContext
from services.selfmod_service import (
    SelfmodService,
    VoteState,
    mute_duration_for_level,
)


router = Router()

EYES_EMOJI = "👾"
DEFAULT_THREAD_ID = 0


class SelfmodVoteCallback(CallbackData, prefix="selfm"):
    """Vote button payload."""

    yes: bool
    msg_id: int  # id of the voting message itself


# ----------------------------------------------------------------------
# Keyboard / message rendering
# ----------------------------------------------------------------------


def _vote_kb(state: VoteState) -> InlineKeyboardMarkup:
    yes_label = f"Accept ({state.yes()})"
    no_label = f"Reject ({state.no()})"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=yes_label,
                    callback_data=SelfmodVoteCallback(yes=True, msg_id=state.vote_msg_id).pack(),
                ),
                InlineKeyboardButton(
                    text=no_label,
                    callback_data=SelfmodVoteCallback(yes=False, msg_id=state.vote_msg_id).pack(),
                ),
            ]
        ]
    )


def _vote_text(state: VoteState) -> str:
    if state.kind == "join":
        header = f"{state.target_mention} wants to join. Vote:"
    elif state.kind == "mute":
        header = f"Mute vote against {state.target_mention}:"
    else:
        header = f"Kick vote against {state.target_mention} (3rd offense):"

    yes_list = [state.voter_mentions.get(str(uid), str(uid)) for uid in state.yes_voters]
    no_list = [state.voter_mentions.get(str(uid), str(uid)) for uid in state.no_voters]
    yes_block = "\n".join(yes_list) if yes_list else "—"
    no_block = "\n".join(no_list) if no_list else "—"
    return f"{header}\n\n<b>Accept ({state.yes()}):</b>\n{yes_block}\n\n<b>Reject ({state.no()}):</b>\n{no_block}"


# ----------------------------------------------------------------------
# Spam-chat event log
# ----------------------------------------------------------------------


def _format_event(event_type: str, chat: Any, state: VoteState, **extra: Any) -> str:
    chat_title = html.escape(chat.title or str(chat.id)) if chat else str(state.chat_id)
    parts = [
        f"<b>selfmod / {html.escape(event_type)}</b>",
        f"chat: {chat_title} ({state.chat_id})",
        f"target: {state.target_mention} ({state.target_user_id})",
        f"votes: yes={state.yes()} no={state.no()}",
    ]
    for key, value in extra.items():
        parts.append(f"{html.escape(key)}: {html.escape(str(value))}")
    return "\n".join(parts)


async def _log(bot: Bot, text: str) -> None:
    with suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.send_message(MTLChats.SpamGroup, text, parse_mode="HTML", disable_web_page_preview=True)


async def _archive_and_delete_vote(bot: Bot, state: VoteState) -> None:
    """Forward the voting message (with full voter list) to SpamGroup, then delete it."""
    with suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.forward_message(MTLChats.SpamGroup, state.chat_id, state.vote_msg_id)
    with suppress(TelegramBadRequest):
        await bot.delete_message(state.chat_id, state.vote_msg_id)


# ----------------------------------------------------------------------
# Public helpers used by other routers (welcome.py)
# ----------------------------------------------------------------------


async def begin_join_vote(bot: Bot, chat: Any, user: User, app_context: AppContext) -> None:
    """Restrict the new member and start a join vote in the chat."""
    if not app_context or not app_context.selfmod_service:
        raise ValueError("app_context with selfmod_service required")
    selfmod_service = cast(SelfmodService, app_context.selfmod_service)
    chat_id = chat.id
    with suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.restrict_chat_member(
            chat_id,
            user.id,
            permissions=ChatPermissions(can_send_messages=False, can_send_media_messages=False),
        )
    mention = get_username_link(user)
    msg = await bot.send_message(
        chat_id,
        f"{mention} wants to join. Vote below — any chat member can participate.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    state = await selfmod_service.start_vote(
        kind="join",
        chat_id=chat_id,
        vote_msg_id=msg.message_id,
        target_user_id=user.id,
        target_mention=mention,
    )
    with suppress(TelegramBadRequest):
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=_vote_text(state),
            parse_mode="HTML",
            reply_markup=_vote_kb(state),
        )
    await _log(bot, _format_event("join_vote_started", chat, state))


async def begin_mute_vote(
    bot: Bot,
    chat: Any,
    target_user_id: int,
    target_mention: str,
    target_msg_id: int,
    app_context: AppContext,
) -> None:
    if not app_context or not app_context.selfmod_service:
        raise ValueError("app_context with selfmod_service required")
    selfmod_service = cast(SelfmodService, app_context.selfmod_service)
    chat_id = chat.id
    msg = await bot.send_message(
        chat_id,
        f"Mute vote against {target_mention} — react with the buttons below.",
        parse_mode="HTML",
        reply_to_message_id=target_msg_id,
        disable_web_page_preview=True,
    )
    state = await selfmod_service.start_vote(
        kind="mute",
        chat_id=chat_id,
        vote_msg_id=msg.message_id,
        target_user_id=target_user_id,
        target_mention=target_mention,
        target_msg_id=target_msg_id,
    )
    with suppress(TelegramBadRequest):
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=_vote_text(state),
            parse_mode="HTML",
            reply_markup=_vote_kb(state),
        )
    await _log(bot, _format_event("mute_vote_started", chat, state))


async def _begin_kick_vote(bot: Bot, chat: Any, parent: VoteState, app_context: AppContext) -> None:
    selfmod_service = cast(SelfmodService, app_context.selfmod_service)
    chat_id = chat.id
    msg = await bot.send_message(
        chat_id,
        f"Kick vote against {parent.target_mention} (3rd offense in 90 days):",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    state = await selfmod_service.start_vote(
        kind="kick",
        chat_id=chat_id,
        vote_msg_id=msg.message_id,
        target_user_id=parent.target_user_id,
        target_mention=parent.target_mention,
    )
    with suppress(TelegramBadRequest):
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=_vote_text(state),
            parse_mode="HTML",
            reply_markup=_vote_kb(state),
        )
    await _log(bot, _format_event("kick_vote_started", chat, state))


# ----------------------------------------------------------------------
# Outcome appliers
# ----------------------------------------------------------------------


_FULL_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_other_messages=True,
    can_send_polls=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
    can_change_info=False,
    can_pin_messages=False,
)


async def _apply_join_approve(bot: Bot, chat: Any, state: VoteState, app_context: AppContext) -> None:
    selfmod_service = cast(SelfmodService, app_context.selfmod_service)
    with suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.restrict_chat_member(state.chat_id, state.target_user_id, permissions=_FULL_PERMS)
    await _log(bot, _format_event("join_vote_approved", chat, state))
    await _archive_and_delete_vote(bot, state)
    await selfmod_service.close_vote(state.chat_id, state.vote_msg_id)


async def _apply_join_reject(bot: Bot, chat: Any, state: VoteState, app_context: AppContext) -> None:
    selfmod_service = cast(SelfmodService, app_context.selfmod_service)
    with suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.ban_chat_member(state.chat_id, state.target_user_id)
    await _log(bot, _format_event("join_vote_rejected", chat, state))
    await _archive_and_delete_vote(bot, state)
    await selfmod_service.close_vote(state.chat_id, state.vote_msg_id)


async def _apply_mute_approve(bot: Bot, session: Session, chat: Any, state: VoteState, app_context: AppContext) -> None:
    selfmod_service = cast(SelfmodService, app_context.selfmod_service)
    admin_service = cast(Any, app_context.admin_service)
    level = await selfmod_service.add_warning(state.chat_id, state.target_user_id)
    duration = mute_duration_for_level(level)
    if duration is None:
        # Level 3+ → escalate to kick vote, do not apply mute now.
        await _log(bot, _format_event("mute_vote_approved", chat, state, level=level, action="escalate"))
        await _archive_and_delete_vote(bot, state)
        await selfmod_service.close_vote(state.chat_id, state.vote_msg_id)
        await _begin_kick_vote(bot, chat, state, app_context)
        return

    end_time = datetime.now() + duration
    end_iso = end_time.isoformat()
    chat_thread_key = f"{state.chat_id}-{DEFAULT_THREAD_ID}"
    if admin_service is not None:
        admin_service.set_user_mute_by_key(chat_thread_key, state.target_user_id, end_iso, state.target_mention)
        all_mutes = admin_service.get_all_topic_mutes()
        import json as _json

        ConfigRepository(session).save_bot_value(0, BotValueTypes.TopicMutes, _json.dumps(all_mutes))

    with suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.restrict_chat_member(
            state.chat_id,
            state.target_user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=end_time,
        )
    await _log(bot, _format_event("mute_vote_approved", chat, state, level=level, duration=str(duration)))
    await _archive_and_delete_vote(bot, state)
    await selfmod_service.close_vote(state.chat_id, state.vote_msg_id)


async def _apply_mute_reject(bot: Bot, chat: Any, state: VoteState, app_context: AppContext) -> None:
    selfmod_service = cast(SelfmodService, app_context.selfmod_service)
    await _log(bot, _format_event("mute_vote_rejected", chat, state))
    await _archive_and_delete_vote(bot, state)
    await selfmod_service.close_vote(state.chat_id, state.vote_msg_id)


async def _apply_kick_approve(bot: Bot, chat: Any, state: VoteState, app_context: AppContext) -> None:
    selfmod_service = cast(SelfmodService, app_context.selfmod_service)
    with suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.ban_chat_member(state.chat_id, state.target_user_id)
    await _log(bot, _format_event("kick_vote_approved", chat, state))
    await _archive_and_delete_vote(bot, state)
    await selfmod_service.close_vote(state.chat_id, state.vote_msg_id)


# ----------------------------------------------------------------------
# Vote callback
# ----------------------------------------------------------------------


@router.callback_query(SelfmodVoteCallback.filter())
async def cb_selfmod_vote(
    query: CallbackQuery,
    callback_data: SelfmodVoteCallback,
    bot: Bot,
    session: Session,
    app_context: AppContext,
) -> None:
    if not app_context or not app_context.selfmod_service:
        await query.answer("Service unavailable.", show_alert=True)
        return
    selfmod_service = cast(SelfmodService, app_context.selfmod_service)
    if not isinstance(query.message, Message):
        await query.answer("Vote message not accessible.", show_alert=True)
        return

    chat = query.message.chat
    chat_id = chat.id
    vote_msg_id = callback_data.msg_id
    state = selfmod_service.get_vote(chat_id, vote_msg_id)
    if state is None:
        await query.answer("This vote is closed.", show_alert=True)
        return
    voter = query.from_user
    if voter.id == state.target_user_id:
        await query.answer("You cannot vote on yourself.", show_alert=True)
        return

    voter_mention = get_username_link(voter)
    result = await selfmod_service.cast(chat_id, vote_msg_id, voter.id, voter_mention, callback_data.yes)
    if result is None:
        await query.answer("This vote is closed.", show_alert=True)
        return
    if result.already_voted:
        await query.answer("You have already voted.", show_alert=True)
        return

    state = result.state
    with suppress(TelegramBadRequest):
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=vote_msg_id,
            text=_vote_text(state),
            parse_mode="HTML",
            reply_markup=_vote_kb(state),
        )
    await query.answer("Vote counted.")

    if result.outcome is None:
        return
    if state.kind == "join":
        if result.outcome == "approve":
            await _apply_join_approve(bot, chat, state, app_context)
        else:
            await _apply_join_reject(bot, chat, state, app_context)
    elif state.kind == "mute":
        if result.outcome == "approve":
            await _apply_mute_approve(bot, session, chat, state, app_context)
        else:
            await _apply_mute_reject(bot, chat, state, app_context)
    elif state.kind == "kick":
        if result.outcome == "approve":
            await _apply_kick_approve(bot, chat, state, app_context)
        else:
            await _log(bot, _format_event("kick_vote_rejected", chat, state))
            await _archive_and_delete_vote(bot, state)
            await selfmod_service.close_vote(chat_id, vote_msg_id)


# ----------------------------------------------------------------------
# 👾 reaction → start mute vote
# ----------------------------------------------------------------------


@router.message_reaction(ChatInOption("selfmod"))
async def selfmod_reaction(
    message: MessageReactionUpdated,
    bot: Bot,
    app_context: AppContext,
) -> bool:
    if not app_context or not app_context.selfmod_service:
        return False
    selfmod_service = cast(SelfmodService, app_context.selfmod_service)
    cache_service = (
        cast(Any, app_context.message_thread_cache_service) if app_context.message_thread_cache_service else None
    )

    reactor = message.user
    if reactor is None or reactor.is_bot:
        return False
    if not message.new_reaction:
        return False
    triggered = any(isinstance(r, ReactionTypeEmoji) and r.emoji == EYES_EMOJI for r in message.new_reaction)
    if not triggered:
        return False

    if cache_service is None:
        return False
    ctx = await cache_service.get_message_context(message.chat.id, message.message_id)
    if not ctx:
        logger.debug(
            "selfmod_reaction skipped: no cached context chat={} msg={}",
            message.chat.id,
            message.message_id,
        )
        return False
    target_user_id = ctx.get("user_id")
    if not target_user_id or target_user_id == reactor.id:
        return False
    if selfmod_service.has_active_mute_vote(message.chat.id, target_user_id):
        return False

    target_username = ctx.get("username")
    target_full_name = ctx.get("full_name") or "user"
    if target_username:
        target_mention = f"@{target_username} {html.escape(str(target_full_name))}"
    else:
        target_mention = f'<a href="tg://user?id={target_user_id}">{html.escape(str(target_full_name))}</a>'

    await begin_mute_vote(
        bot=bot,
        chat=message.chat,
        target_user_id=int(target_user_id),
        target_mention=target_mention,
        target_msg_id=message.message_id,
        app_context=app_context,
    )
    return True


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router selfmod was loaded")
