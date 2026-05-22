# routers/admin_panel.py
"""Admin panel for chat management in private messages and admin reload in groups."""

import html
import json
from contextlib import suppress
from typing import Any, cast

from aiogram import Router, Bot, F
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, User
from aiogram.utils.text_decorations import html_decoration
from loguru import logger
from sqlalchemy.orm import Session

from db.repositories import ConfigRepository
from other.constants import BotValueTypes
from services.command_registry_service import update_command_info
from services.app_context import AppContext
from services.feature_flags import FEATURE_TO_ENUM, FeatureFlagsService
from services.telegram_utils import get_chat_info

router = Router()


# ============ Callback Data ============


class AdminCallback(CallbackData, prefix="adm"):
    """Callback data for admin panel navigation."""

    action: str  # list, menu, flags, welcome, toggle, edit, del
    chat_id: int = 0
    param: str = ""
    page: int = 0  # pagination for chat list


# ============ FSM States ============


class AdminPanelStates(StatesGroup):
    """FSM states for admin panel text input."""

    waiting_welcome_message = State()
    waiting_welcome_button = State()


# ============ Feature Flag Labels ============

FEATURE_LABELS = {
    "captcha": "Captcha",
    "moderate": "Moderate",
    "no_first_link": "No First Link",
    "reply_only": "Reply Only",
    "listen": "Listen",
    "auto_all": "Auto All",
    "save_last_message_date": "Save Last Msg Date",
    "join_request_captcha": "Join Request Captcha",
    "full_data": "Full Data",
    "first_vote": "First Vote",
    "need_decode": "Need Decode",
    "delete_income": "Delete Income",
    "entry_channel": "Entry Channel",
    "notify_join": "Notify Join Request",
    "selfmod": "Self-Moderation (vote-based)",
}

# Features that require skynet_admin to toggle (hidden from regular admins)
SKYNET_ONLY_FEATURES: set[str] = {"full_data", "listen"}


def get_feature_description(feature_key: str, app_context: AppContext) -> str:
    """Get feature description from command_registry by cmd_list."""
    if not app_context or not app_context.command_registry:
        return ""

    command_registry = cast(Any, app_context.command_registry)
    for cmd in command_registry.get_all_commands().values():
        if feature_key in cmd.cmd_list:
            return cmd.description
    return ""


# ============ Chat Title Cache ============

_chat_titles: dict[int, str] = {}
_inaccessible_chats: set[int] = set()
_chat_owners: dict[int, int | None] = {}  # chat_id -> owner_user_id (or None if no owner)


# ============ Helper Functions ============


def mark_chat_inaccessible(chat_id: int, session: Session | None = None) -> None:
    """Mark chat as inaccessible. Optionally save to DB."""
    _inaccessible_chats.add(chat_id)
    if session:
        try:
            # Save to DB as JSON list
            ConfigRepository(session).save_bot_value(
                0, BotValueTypes.Inaccessible, json.dumps(list(_inaccessible_chats))
            )
        except Exception as e:
            logger.error(f"Failed to save inaccessible chats: {e}")


def is_chat_accessible(chat_id: int) -> bool:
    """Check if chat is accessible (not in inaccessible list)."""
    return chat_id not in _inaccessible_chats


def unmark_chat_accessible(chat_id: int, session: Session | None = None) -> None:
    """Remove chat from inaccessible list (it's accessible now)."""
    if chat_id not in _inaccessible_chats:
        return
    _inaccessible_chats.discard(chat_id)
    if session:
        try:
            ConfigRepository(session).save_bot_value(
                0, BotValueTypes.Inaccessible, json.dumps(list(_inaccessible_chats))
            )
        except Exception as e:
            logger.error(f"Failed to save inaccessible chats: {e}")


async def async_unmark_chat_accessible(chat_id: int, session) -> None:
    """Remove chat from inaccessible list and save it using async DB session."""
    if chat_id not in _inaccessible_chats:
        return
    _inaccessible_chats.discard(chat_id)
    try:
        await ConfigRepository(session).async_save_bot_value(
            0, BotValueTypes.Inaccessible, json.dumps(list(_inaccessible_chats))
        )
    except Exception as e:
        logger.error(f"Failed to save inaccessible chats: {e}")


def load_inaccessible_chats(chat_ids: list[int]) -> None:
    """Load inaccessible chats from DB (called at startup)."""
    _inaccessible_chats.clear()
    _inaccessible_chats.update(chat_ids)


async def get_chat_title(
    chat_id: int, bot: Bot, session: Session | None = None, app_context: AppContext | None = None
) -> str | None:
    """Get chat title from cache, database, or API. Returns None if chat inaccessible."""
    # Skip inaccessible chats
    if chat_id in _inaccessible_chats:
        return None

    if chat_id in _chat_titles:
        return _chat_titles[chat_id]

    # Try database first, fallback to API
    if app_context and app_context.db_service:
        title, _ = await get_chat_info(chat_id, bot, app_context.db_service)
        if title:
            _chat_titles[chat_id] = title
            return title
        else:
            mark_chat_inaccessible(chat_id, session)
            return None

    # Fallback: direct API call if no db_service available
    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or str(chat_id)
        _chat_titles[chat_id] = title
        return title
    except (TelegramBadRequest, TelegramForbiddenError):
        mark_chat_inaccessible(chat_id, session)
        return None


def _is_skynet_admin(user: User, app_context: AppContext) -> bool:
    """Check if user is a skynet admin."""
    if not app_context or not app_context.admin_service:
        return False
    username = user.username
    if not username:
        return False
    return app_context.admin_service.is_skynet_admin(username)


def _sync_feature_toggle(app_context: AppContext, feature: str, chat_id: int, enabled: bool) -> None:
    """Sync feature toggle to specialized DI services that maintain their own state.

    Some features have side-effects beyond the feature_flags boolean cache:
    they maintain separate in-memory state in dedicated services (e.g.
    NotificationService._notify_join dict). This function mirrors the logic
    from multi_handler._sync_toggle_addition / _sync_toggle_removal.
    """
    enum_key = FEATURE_TO_ENUM.get(feature)
    if enum_key is None:
        return

    if enabled:
        if enum_key == BotValueTypes.FirstVote and app_context.voting_service:
            app_context.voting_service.enable_first_vote(chat_id)
        elif enum_key == BotValueTypes.NeedDecode and app_context.bot_state_service:
            app_context.bot_state_service.mark_needs_decode(chat_id)
        elif enum_key == BotValueTypes.NotifyJoin and app_context.notification_service:
            app_context.notification_service.set_join_notify(chat_id, "1")
        elif enum_key == BotValueTypes.DeleteIncome and app_context.config_service:
            app_context.config_service.set_delete_income(chat_id, "1")
    else:
        if enum_key == BotValueTypes.FirstVote and app_context.voting_service:
            app_context.voting_service.disable_first_vote(chat_id)
        elif enum_key == BotValueTypes.NeedDecode and app_context.bot_state_service:
            app_context.bot_state_service.clear_needs_decode(chat_id)
        elif enum_key == BotValueTypes.NotifyJoin and app_context.notification_service:
            app_context.notification_service.disable_join_notify(chat_id)
        elif enum_key == BotValueTypes.DeleteIncome and app_context.config_service:
            app_context.config_service.remove_delete_income(chat_id)


def _format_admin_name(admin_user: User) -> str:
    """Format admin name for notification message (HTML-safe)."""
    if admin_user.username:
        return f"@{html_decoration.quote(admin_user.username)}"
    name = admin_user.first_name or ""
    if admin_user.last_name:
        name = f"{name} {admin_user.last_name}"
    return html_decoration.quote(name.strip() or str(admin_user.id))


async def _get_chat_owner_id(bot: Bot, chat_id: int) -> int | None:
    """Get chat owner ID with caching."""
    if chat_id in _chat_owners:
        return _chat_owners[chat_id]

    try:
        admins = await bot.get_chat_administrators(chat_id)
        owner = next((a for a in admins if a.status == "creator"), None)
        owner_id = owner.user.id if owner else None
        _chat_owners[chat_id] = owner_id
        return owner_id
    except (TelegramBadRequest, TelegramForbiddenError):
        _chat_owners[chat_id] = None
        mark_chat_inaccessible(chat_id)
        return None


async def notify_owner_about_settings_change(
    bot: Bot, chat_id: int, admin_user: User, change_description: str, app_context: AppContext | None = None
) -> None:
    """Notify chat owner about settings change by admin.

    Sends a notification to the chat owner when an admin changes settings.
    Does nothing if:
    - Owner cannot be determined
    - Admin is the owner (no need to notify themselves)
    - Owner is unreachable (silently fails)
    """
    try:
        # Don't notify if owner is unknown or is the admin making changes
        owner_id = await _get_chat_owner_id(bot, chat_id)
        if not owner_id or owner_id == admin_user.id:
            return

        # Get chat info for title - database first, then API
        chat_title = str(chat_id)
        if app_context and app_context.db_service:
            title, _ = await get_chat_info(chat_id, bot, app_context.db_service)
            if title:
                chat_title = title
        else:
            try:
                chat = await bot.get_chat(chat_id)
                chat_title = chat.title or str(chat_id)
            except (TelegramBadRequest, TelegramForbiddenError):
                pass

        admin_name = _format_admin_name(admin_user)
        msg = (
            f"Настройки чата <b>{html_decoration.quote(chat_title)}</b> изменены ({admin_name}):\n{change_description}"
        )

        await bot.send_message(owner_id, msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        # Owner unreachable - silently ignore
        logger.debug(f"Failed to notify owner: {e}")
        pass


async def get_user_admin_chats(
    user_id: int, app_context: AppContext, bot: Bot, session: Session | None = None
) -> list[tuple[int, str]]:
    """
    Get list of chats where user is an administrator.

    Uses admin_service cache for admin check, cached or parallel API calls for titles.
    Filters out inaccessible chats.
    Returns list of tuples: (chat_id, chat_title)
    """
    import asyncio

    if not app_context or not app_context.admin_service:
        return []

    # Get chats where user is admin from cache (fast)
    admin_service = cast(Any, app_context.admin_service)
    with admin_service._lock:
        all_chats = list(admin_service._admins.keys())

    # Filter out inaccessible chats early
    user_chats = [
        chat_id
        for chat_id in all_chats
        if admin_service.is_chat_admin(chat_id, user_id) and is_chat_accessible(chat_id)
    ]

    if not user_chats:
        return []

    # Fetch titles (from cache, database, or API in parallel)
    async def fetch_chat_info(chat_id: int) -> tuple[int, str] | None:
        title = await get_chat_title(chat_id, bot, session, app_context)
        return (chat_id, title) if title else None

    results = await asyncio.gather(*[fetch_chat_info(cid) for cid in user_chats])
    chats = [r for r in results if r is not None]
    # Sort by title alphabetically (case-insensitive)
    return sorted(chats, key=lambda x: x[1].lower())


async def verify_admin_via_api(user_id: int, chat_id: int, bot: Bot) -> bool:
    """Check if user is admin via Telegram API (real-time check)."""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        return any(admin.user.id == user_id for admin in admins)
    except TelegramBadRequest:
        return False


# ============ Keyboard Builders ============

CHATS_PER_PAGE = 10


def chat_list_kb(chats: list[tuple[int, str]], page: int = 0) -> InlineKeyboardMarkup:
    """Build keyboard with chat selection buttons (paginated)."""
    total = len(chats)
    total_pages = (total + CHATS_PER_PAGE - 1) // CHATS_PER_PAGE  # ceil division

    # Ensure page is within bounds
    page = max(0, min(page, total_pages - 1)) if total_pages > 0 else 0

    start = page * CHATS_PER_PAGE
    end = start + CHATS_PER_PAGE
    page_chats = chats[start:end]

    buttons = []
    for chat_id, title in page_chats:
        # Truncate long titles
        display_title = title[:20] + "..." if len(title) > 20 else title
        buttons.append(
            [
                InlineKeyboardButton(
                    text=display_title, callback_data=AdminCallback(action="menu", chat_id=chat_id).pack()
                )
            ]
        )

    # Add navigation buttons if needed
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(text="<< Prev", callback_data=AdminCallback(action="list", page=page - 1).pack())
            )
        nav_row.append(
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=AdminCallback(action="noop").pack())
        )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(text="Next >>", callback_data=AdminCallback(action="list", page=page + 1).pack())
            )
        buttons.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def chat_menu_kb(chat_id: int) -> InlineKeyboardMarkup:
    """Build main menu keyboard for a chat."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Feature Flags", callback_data=AdminCallback(action="flags", chat_id=chat_id).pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="Welcome Settings", callback_data=AdminCallback(action="welcome", chat_id=chat_id).pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="Remove Dead Users", callback_data=AdminCallback(action="dead", chat_id=chat_id).pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="Selfmod Stats",
                    callback_data=AdminCallback(action="selfmod_stats", chat_id=chat_id).pack(),
                )
            ],
            [InlineKeyboardButton(text="<< Back", callback_data=AdminCallback(action="list").pack())],
        ]
    )


def feature_flags_kb(
    chat_id: int, feature_flags: FeatureFlagsService, is_skynet_admin: bool = False
) -> InlineKeyboardMarkup:
    """Build keyboard with feature toggle buttons.

    Skynet-only features are hidden from regular admins.
    """
    buttons = []

    for feature_key, label in FEATURE_LABELS.items():
        if feature_key in SKYNET_ONLY_FEATURES and not is_skynet_admin:
            continue

        is_enabled = feature_flags.is_enabled(chat_id, feature_key)
        status_icon = "🟢" if is_enabled else "🔴"

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{status_icon} {label}",
                    callback_data=AdminCallback(action="info", chat_id=chat_id, param=feature_key).pack(),
                ),
                InlineKeyboardButton(
                    text=status_icon,
                    callback_data=AdminCallback(action="toggle", chat_id=chat_id, param=feature_key).pack(),
                ),
            ]
        )

    buttons.append(
        [InlineKeyboardButton(text="<< Back", callback_data=AdminCallback(action="menu", chat_id=chat_id).pack())]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _preview_text(value: Any, max_length: int) -> str:
    """Return shortened string value for admin UI."""
    raw = "" if value is None else str(value)
    if not raw:
        return "Not set"

    normalized = raw.replace("\r\n", "\n").strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3] + "..."


def _format_welcome_settings(chat_id: int, title: str, app_context: AppContext) -> list[str]:
    """Build display lines for welcome settings."""
    welcome_msg = app_context.config_service.get_welcome_message(chat_id) if app_context.config_service else None
    welcome_btn = app_context.config_service.get_welcome_button(chat_id) if app_context.config_service else None

    msg_display = _preview_text(welcome_msg, 450)
    btn_display = _preview_text(welcome_btn, 120)

    return [
        f"Welcome Settings: {html.escape(title)}",
        "",
        f"Message: {html.escape(msg_display)}",
        f"Button: {html.escape(btn_display)}",
    ]


def _build_welcome_edit_prompt(chat_id: int, edit_type: str, app_context: AppContext | None) -> str:
    """Build a contextual prompt with current value for editing."""
    if not app_context or not app_context.config_service:
        return (
            "Send the new welcome message.\n\nYou can use {name} for user's name.\n\nSend /cancel to cancel."
            if edit_type == "msg"
            else "Send the button text.\n\nSend /cancel to cancel."
        )

    if edit_type == "msg":
        current = _preview_text(app_context.config_service.get_welcome_message(chat_id), 1200)
        return (
            "Edit welcome message.\n"
            f"Current:\n{current}\n\n"
            "You can use {name} for user's name.\n"
            "Send /cancel to cancel."
        )

    current = _preview_text(app_context.config_service.get_welcome_button(chat_id), 120)
    return f"Edit welcome button.\nCurrent: {current}\n\nSend /cancel to cancel."


def welcome_kb(chat_id: int) -> InlineKeyboardMarkup:
    """Build keyboard for welcome settings."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Edit Message", callback_data=AdminCallback(action="edit", chat_id=chat_id, param="msg").pack()
                ),
                InlineKeyboardButton(
                    text="Edit Button", callback_data=AdminCallback(action="edit", chat_id=chat_id, param="btn").pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Delete Welcome",
                    callback_data=AdminCallback(action="del", chat_id=chat_id, param="welcome").pack(),
                )
            ],
            [InlineKeyboardButton(text="<< Back", callback_data=AdminCallback(action="menu", chat_id=chat_id).pack())],
        ]
    )


# ============ Command Handler ============


@update_command_info("/admin", "Admin panel for chat management (use in private chat)")
@router.message(Command(commands=["admin"]), F.chat.type == ChatType.PRIVATE)
async def cmd_admin(message: Message, session: Session, bot: Bot, app_context: AppContext):
    """Entry point for admin panel - shows list of chats where user is admin.

    Usage:
        /admin - show list of all chats
        /admin @username - go directly to chat settings
        /admin -100123456 - go directly to chat settings by ID
    """
    if not app_context or not app_context.admin_service:
        await message.answer("Service unavailable.")
        return

    if not message.from_user:
        await message.answer("Cannot identify user.")
        return
    user_id = message.from_user.id

    # Check for direct chat argument
    args = (message.text or "").split(maxsplit=1)
    if len(args) > 1:
        chat_arg = args[1].strip()
        target_chat_id = None

        try:
            if chat_arg.startswith("@"):
                # Username - resolve via API
                chat_info = await bot.get_chat(chat_arg)
                target_chat_id = chat_info.id
            elif chat_arg.lstrip("-").isdigit():
                # Numeric chat ID
                target_chat_id = int(chat_arg)
        except (TelegramBadRequest, TelegramForbiddenError, ValueError):
            await message.answer(f"Chat not found: {chat_arg}")
            return

        if target_chat_id:
            # Verify user is admin
            if not await verify_admin_via_api(user_id, target_chat_id, bot):
                await message.answer("You are not an admin of this chat.")
                return

            title = await get_chat_title(target_chat_id, bot, session, app_context)
            if not title:
                await message.answer("Chat not accessible.")
                return

            await message.answer(f"Settings: {title}", reply_markup=chat_menu_kb(target_chat_id))
            return

    # No argument - show chat list
    chats = await get_user_admin_chats(user_id, app_context, bot, session)

    if not chats:
        await message.answer("You are not an admin in any chats managed by this bot.")
        return

    await message.answer(f"Select a chat to manage ({len(chats)} total):", reply_markup=chat_list_kb(chats, page=0))


@router.message(Command(commands=["admin"]), F.chat.type != ChatType.PRIVATE)
async def cmd_admin_reload(message: Message, session: Session, bot: Bot, app_context: AppContext):
    """Reload admin list for current chat (group command)."""
    if not app_context or not app_context.admin_service:
        return
    admin_service = app_context.admin_service

    chat_id = message.chat.id

    try:
        members = await bot.get_chat_administrators(chat_id)
        new_admins = [member.user.id for member in members]

        # Update cache
        admin_service.set_chat_admins(chat_id, new_admins)

        # Save to DB
        ConfigRepository(session).save_bot_value(chat_id, BotValueTypes.Admins, json.dumps(new_admins))

        reply = await message.reply("OK")

        # Delete both messages after 5 seconds
        if app_context.utils_service:
            utils_service = cast(Any, app_context.utils_service)
            await utils_service.sleep_and_delete(message, 5)
            await utils_service.sleep_and_delete(reply, 5)

    except TelegramBadRequest as e:
        logger.error(f"Failed to reload admins for chat {chat_id}: {e}")


# ============ Navigation Callbacks ============


@router.callback_query(AdminCallback.filter(F.action == "noop"))
async def cb_noop(query: CallbackQuery):
    """No-op callback for static buttons like page counter."""
    await query.answer()


@router.callback_query(AdminCallback.filter(F.action == "list"))
async def cb_show_chat_list(
    query: CallbackQuery, callback_data: AdminCallback, session: Session, bot: Bot, app_context: AppContext
):
    """Show list of chats where user is admin (paginated)."""
    if not app_context or not app_context.admin_service:
        await query.answer("Service unavailable.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return

    user_id = query.from_user.id
    chats = await get_user_admin_chats(user_id, app_context, bot, session)

    if not chats:
        await query.answer("You are not an admin in any chats.", show_alert=True)
        return

    page = callback_data.page
    with suppress(TelegramBadRequest):
        await query.message.edit_text(
            f"Select a chat to manage ({len(chats)} total):", reply_markup=chat_list_kb(chats, page)
        )
    await query.answer()


@router.callback_query(AdminCallback.filter(F.action == "menu"))
async def cb_show_chat_menu(
    query: CallbackQuery, callback_data: AdminCallback, session: Session, bot: Bot, app_context: AppContext
):
    """Show main menu for selected chat."""
    chat_id = callback_data.chat_id
    user_id = query.from_user.id
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return

    if not await verify_admin_via_api(user_id, chat_id, bot):
        await query.answer("You are not an admin of this chat.", show_alert=True)
        return

    title = await get_chat_title(chat_id, bot, session, app_context)
    if not title:
        await query.answer("Chat not accessible.", show_alert=True)
        return

    with suppress(TelegramBadRequest):
        await query.message.edit_text(f"Settings: {title}", reply_markup=chat_menu_kb(chat_id))
    await query.answer()


# ============ Feature Flags Callbacks ============


@router.callback_query(AdminCallback.filter(F.action == "flags"))
async def cb_show_feature_flags(
    query: CallbackQuery, callback_data: AdminCallback, session: Session, bot: Bot, app_context: AppContext
):
    """Show feature flags for selected chat."""
    if not app_context or not app_context.feature_flags:
        await query.answer("Service unavailable.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return

    chat_id = callback_data.chat_id
    skynet = _is_skynet_admin(query.from_user, app_context)

    title = await get_chat_title(chat_id, bot, session, app_context)
    if not title:
        await query.answer("Chat not accessible.", show_alert=True)
        return

    with suppress(TelegramBadRequest):
        await query.message.edit_text(
            f"Feature Flags: {title}",
            reply_markup=feature_flags_kb(chat_id, app_context.feature_flags, is_skynet_admin=skynet),
        )
    await query.answer()


@router.callback_query(AdminCallback.filter(F.action == "toggle"))
async def cb_toggle_feature(
    query: CallbackQuery, callback_data: AdminCallback, session: Session, bot: Bot, app_context: AppContext
):
    """Toggle a feature flag."""
    if not app_context or not app_context.feature_flags:
        await query.answer("Service unavailable.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return

    chat_id = callback_data.chat_id
    feature = callback_data.param
    feature_flags = app_context.feature_flags
    skynet = _is_skynet_admin(query.from_user, app_context)

    # Block skynet-only features for regular admins
    if feature in SKYNET_ONLY_FEATURES and not skynet:
        await query.answer("Only skynet admins can toggle this feature.", show_alert=True)
        return

    # Toggle the feature with DB persistence (persist=False because we
    # write to DB ourselves via ConfigRepository, matching handle_command)
    current = feature_flags.is_enabled(chat_id, feature)
    new_state = not current
    feature_flags.set_feature(chat_id, feature, new_state, persist=False)

    # Persist to DB
    enum_key = FEATURE_TO_ENUM.get(feature)
    if enum_key is not None:
        db_value = "1" if new_state else None
        ConfigRepository(session).save_bot_value(chat_id, enum_key, db_value)

    # Sync with specialized DI services for features that have side-effects
    _sync_feature_toggle(app_context, feature, chat_id, new_state)

    title = await get_chat_title(chat_id, bot, session, app_context) or str(chat_id)

    # Update keyboard
    with suppress(TelegramBadRequest):
        await query.message.edit_text(
            f"Feature Flags: {title}",
            reply_markup=feature_flags_kb(chat_id, feature_flags, is_skynet_admin=skynet),
        )

    label = FEATURE_LABELS.get(feature, feature)
    status = "enabled" if new_state else "disabled"
    await query.answer(f"{label} {status}")

    # Notify owner about settings change
    await notify_owner_about_settings_change(
        bot,
        chat_id,
        query.from_user,
        f"Флаг <code>{html_decoration.quote(feature)}</code>: {'включен' if new_state else 'выключен'}",
        app_context,
    )


@router.callback_query(AdminCallback.filter(F.action == "info"))
async def cb_feature_info(query: CallbackQuery, callback_data: AdminCallback, app_context: AppContext):
    """Show feature description in alert popup."""
    feature = callback_data.param
    label = FEATURE_LABELS.get(feature, feature)
    description = get_feature_description(feature, app_context)

    if description:
        text = f"{label}\n\n{description}"
    else:
        text = f"{label}\n\nОписание недоступно."

    await query.answer(text, show_alert=True)


# ============ Welcome Settings Callbacks ============


@router.callback_query(AdminCallback.filter(F.action == "welcome"))
async def cb_show_welcome_settings(
    query: CallbackQuery, callback_data: AdminCallback, session: Session, bot: Bot, app_context: AppContext
):
    """Show welcome settings for selected chat."""
    if not app_context or not app_context.config_service:
        await query.answer("Service unavailable.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return

    chat_id = callback_data.chat_id

    title = await get_chat_title(chat_id, bot, session, app_context)
    if not title:
        await query.answer("Chat not accessible.", show_alert=True)
        return

    text_parts = _format_welcome_settings(chat_id, title, app_context)

    with suppress(TelegramBadRequest):
        await query.message.edit_text(
            "\n".join(text_parts), reply_markup=welcome_kb(chat_id), parse_mode=ParseMode.HTML
        )
    await query.answer()


# ============ Remove Dead Users Callback ============


@router.callback_query(AdminCallback.filter(F.action == "dead"))
async def cb_remove_dead_users(query: CallbackQuery, callback_data: AdminCallback, bot: Bot, app_context: AppContext):
    """Remove deleted users from chat."""
    if not app_context or not app_context.group_service:
        await query.answer("Service unavailable.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return

    chat_id = callback_data.chat_id
    group_service = cast(Any, app_context.group_service)

    await query.answer("Starting to remove deleted users...", show_alert=True)

    try:
        count = await group_service.remove_deleted_users(chat_id)
        await query.message.answer(f"Finished removing deleted users.\nTotal removed: {count}")

        # Notify owner about settings change
        await notify_owner_about_settings_change(
            bot, chat_id, query.from_user, f"Удалены неактивные пользователи: {count}", app_context
        )
    except Exception as e:
        logger.error(f"Error removing dead users from {chat_id}: {e}")
        await query.message.answer(f"Error: {e}")


@router.callback_query(AdminCallback.filter(F.action == "edit"))
async def cb_edit_welcome(
    query: CallbackQuery, callback_data: AdminCallback, state: FSMContext, app_context: AppContext
):
    """Start editing welcome message or button."""
    chat_id = callback_data.chat_id
    edit_type = callback_data.param  # "msg" or "btn"
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return

    # Store chat_id in FSM state
    await state.update_data(edit_chat_id=chat_id)

    if edit_type == "msg":
        await state.set_state(AdminPanelStates.waiting_welcome_message)
    else:  # btn
        await state.set_state(AdminPanelStates.waiting_welcome_button)

    prompt = _build_welcome_edit_prompt(chat_id, edit_type, app_context)

    with suppress(TelegramBadRequest):
        await query.message.edit_text(prompt)
    await query.answer()


@router.callback_query(AdminCallback.filter(F.action == "del"))
async def cb_delete_welcome(
    query: CallbackQuery, callback_data: AdminCallback, session: Session, bot: Bot, app_context: AppContext
):
    """Delete welcome settings."""
    if not app_context or not app_context.config_service:
        await query.answer("Service unavailable.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return

    chat_id = callback_data.chat_id

    # Delete welcome settings from cache and DB
    app_context.config_service.remove_welcome_message(chat_id, session)
    app_context.config_service.remove_welcome_button(chat_id, session)

    await query.answer("Welcome settings deleted.")

    # Notify owner about settings change
    await notify_owner_about_settings_change(
        bot, chat_id, query.from_user, "Удалены настройки приветствия", app_context
    )

    # Return to chat menu
    title = await get_chat_title(chat_id, bot, session, app_context) or str(chat_id)

    with suppress(TelegramBadRequest):
        await query.message.edit_text(f"Settings: {title}", reply_markup=chat_menu_kb(chat_id))


# ============ FSM Handlers ============


@router.message(Command(commands=["cancel"]), F.chat.type == ChatType.PRIVATE)
async def cmd_cancel(message: Message, state: FSMContext):
    """Cancel current FSM operation."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Nothing to cancel.")
        return

    await state.clear()
    await message.answer("Cancelled. Use /admin to start again.")


@router.message(AdminPanelStates.waiting_welcome_message, F.chat.type == ChatType.PRIVATE)
async def process_welcome_message(
    message: Message, state: FSMContext, session: Session, bot: Bot, app_context: AppContext
):
    """Process new welcome message input."""
    if not app_context or not app_context.config_service:
        await message.answer("Service unavailable.")
        await state.clear()
        return

    data = await state.get_data()
    chat_id = data.get("edit_chat_id")

    if not chat_id:
        await message.answer("Error: chat not found. Use /admin to start again.")
        await state.clear()
        return

    # Save welcome message to cache and DB
    new_message = message.html_text or message.text or message.caption or ""
    app_context.config_service.set_welcome_message(chat_id, new_message, session)

    await state.clear()

    title = await get_chat_title(chat_id, bot, session, app_context) or str(chat_id)
    text_parts = _format_welcome_settings(chat_id, title, app_context)
    with suppress(TelegramBadRequest):
        await message.answer("\n".join(text_parts), reply_markup=welcome_kb(chat_id), parse_mode=ParseMode.HTML)

    # Notify owner about settings change
    if message.from_user:
        await notify_owner_about_settings_change(
            bot, chat_id, message.from_user, "Изменено приветственное сообщение", app_context
        )


@router.message(AdminPanelStates.waiting_welcome_button, F.chat.type == ChatType.PRIVATE)
async def process_welcome_button(
    message: Message, state: FSMContext, session: Session, bot: Bot, app_context: AppContext
):
    """Process new welcome button input."""
    if not app_context or not app_context.config_service:
        await message.answer("Service unavailable.")
        await state.clear()
        return

    data = await state.get_data()
    chat_id = data.get("edit_chat_id")

    if not chat_id:
        await message.answer("Error: chat not found. Use /admin to start again.")
        await state.clear()
        return

    button_text = (message.text or "").strip()

    if not button_text:
        await message.answer("Button text cannot be empty. Try again or send /cancel.")
        return

    # Save welcome button to cache and DB (stored as plain text)
    app_context.config_service.set_welcome_button(chat_id, button_text, session)

    await state.clear()

    title = await get_chat_title(chat_id, bot, session, app_context) or str(chat_id)
    text_parts = _format_welcome_settings(chat_id, title, app_context)
    with suppress(TelegramBadRequest):
        await message.answer("\n".join(text_parts), reply_markup=welcome_kb(chat_id), parse_mode=ParseMode.HTML)

    # Notify owner about settings change
    if message.from_user:
        await notify_owner_about_settings_change(
            bot, chat_id, message.from_user, "Изменена кнопка приветствия", app_context
        )


# ============ Selfmod Stats Sub-page ============


def _selfmod_stats_kb(chat_id: int, warnings: dict[int, int]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for user_id, count in sorted(warnings.items(), key=lambda x: -x[1]):
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"Reset {user_id} ({count})",
                    callback_data=AdminCallback(action="selfmod_reset", chat_id=chat_id, param=str(user_id)).pack(),
                )
            ]
        )
    buttons.append(
        [InlineKeyboardButton(text="<< Back", callback_data=AdminCallback(action="menu", chat_id=chat_id).pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(AdminCallback.filter(F.action == "selfmod_stats"))
async def cb_selfmod_stats(
    query: CallbackQuery, callback_data: AdminCallback, session: Session, bot: Bot, app_context: AppContext
):
    """Show selfmod warnings for the chat."""
    if not app_context or not app_context.selfmod_service:
        await query.answer("Selfmod service unavailable.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return

    chat_id = callback_data.chat_id
    title = await get_chat_title(chat_id, bot, session, app_context) or str(chat_id)
    selfmod_service = cast(Any, app_context.selfmod_service)
    warnings = await selfmod_service.list_warnings(chat_id)

    if not warnings:
        text = f"Selfmod stats: {html.escape(title)}\n\nNo active warnings (last 90 days)."
    else:
        lines = [f"Selfmod stats: {html.escape(title)}", "", "Active warnings (last 90 days):"]
        for uid, count in sorted(warnings.items(), key=lambda x: -x[1]):
            lines.append(f"• <code>{uid}</code> — {count} warning(s)")
        text = "\n".join(lines)

    with suppress(TelegramBadRequest):
        await query.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=_selfmod_stats_kb(chat_id, warnings)
        )
    await query.answer()


@router.callback_query(AdminCallback.filter(F.action == "selfmod_reset"))
async def cb_selfmod_reset(
    query: CallbackQuery, callback_data: AdminCallback, session: Session, bot: Bot, app_context: AppContext
):
    """Reset warnings for a specific user."""
    if not app_context or not app_context.selfmod_service:
        await query.answer("Selfmod service unavailable.", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer("Message not accessible.", show_alert=True)
        return

    chat_id = callback_data.chat_id
    try:
        target_user_id = int(callback_data.param)
    except (TypeError, ValueError):
        await query.answer("Invalid target.", show_alert=True)
        return

    selfmod_service = cast(Any, app_context.selfmod_service)
    await selfmod_service.reset_warnings(chat_id, target_user_id)

    title = await get_chat_title(chat_id, bot, session, app_context) or str(chat_id)
    warnings = await selfmod_service.list_warnings(chat_id)

    if not warnings:
        text = f"Selfmod stats: {html.escape(title)}\n\nNo active warnings (last 90 days)."
    else:
        lines = [f"Selfmod stats: {html.escape(title)}", "", "Active warnings (last 90 days):"]
        for uid, count in sorted(warnings.items(), key=lambda x: -x[1]):
            lines.append(f"• <code>{uid}</code> — {count} warning(s)")
        text = "\n".join(lines)

    with suppress(TelegramBadRequest):
        await query.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=_selfmod_stats_kb(chat_id, warnings)
        )
    await query.answer(f"Warnings reset for {target_user_id}")

    # Log to spam-chat
    with suppress(TelegramBadRequest, TelegramForbiddenError):
        from other.constants import MTLChats as _MTLChats

        actor = f"@{query.from_user.username}" if query.from_user.username else str(query.from_user.id)
        await bot.send_message(
            _MTLChats.SpamGroup,
            f"<b>selfmod / warnings_reset</b>\nchat: {html.escape(title)} ({chat_id})\n"
            f"target: <code>{target_user_id}</code>\nactor: {html.escape(actor)}",
            parse_mode=ParseMode.HTML,
        )

    await notify_owner_about_settings_change(
        bot, chat_id, query.from_user, f"Сброшены selfmod-предупреждения для {target_user_id}", app_context
    )


# ============ Register Handlers ============


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router admin_panel was loaded")
