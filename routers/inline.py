from aiogram import Bot, Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from services.app_context import AppContext

router = Router()

# Cache for username -> chat_id resolution
_username_cache: dict[str, int] = {}


def _get_commands_dict(app_context):
    """Get commands dict from DI service. Raises error if app_context not available."""
    if not app_context or not app_context.command_registry:
        raise ValueError("app_context with command_registry required")
    # Convert CommandInfo objects to legacy format for compatibility
    commands = app_context.command_registry.get_all_commands()
    return {
        name: {"info": cmd.description, "cmd_type": cmd.cmd_type, "cmd_list": cmd.cmd_list[0] if cmd.cmd_list else ""}
        for name, cmd in commands.items()
    }


def _check_alert_me(app_context, chat_id: int, user_id: int) -> bool:
    """Check if user has alert_me enabled for the chat using DI service."""
    if not app_context or not app_context.notification_service:
        raise ValueError("app_context with notification_service required")
    alert_config = app_context.notification_service.get_alert_config(chat_id)
    if alert_config and isinstance(alert_config, list):
        return user_id in alert_config
    return False


def _get_attr_list(app_context, attr_name: str):
    """Get attribute list from app_context services."""
    if not app_context:
        raise ValueError("app_context required")
    # For alert_me, use notification_service
    if attr_name == "alert_me":
        if not app_context.notification_service:
            raise ValueError("app_context with notification_service required")
        return app_context.notification_service.get_all_alerts()
    # For other attributes, use feature_flags or config_service as appropriate
    # Return empty dict as safe default - the service should provide the data
    if app_context.feature_flags:
        return app_context.feature_flags.get_feature_list(attr_name)
    return {}


async def _resolve_chat_id(bot: Bot, identifier: str) -> int:
    """Resolve username or numeric ID to chat_id."""
    identifier = identifier.strip()

    # Try numeric ID first
    try:
        if identifier.startswith("-100"):
            return int(identifier)
        elif identifier.lstrip("-").isdigit():
            return int(f"-100{identifier}")
    except ValueError:
        pass

    # Try username (with or without @)
    username = identifier.lstrip("@").lower()
    if not username:
        return 0

    # Check cache
    if username in _username_cache:
        return _username_cache[username]

    # Resolve via API
    try:
        chat = await bot.get_chat(f"@{username}")
        _username_cache[username] = chat.id
        return chat.id
    except Exception:
        return 0


@router.inline_query()
async def inline_handler(
    inline_query: InlineQuery,
    session: AsyncSession,
    bot: Bot,
    app_context: Optional[AppContext] = None,
):
    try:
        if not app_context:
            logger.error("app_context is None in inline_handler!")
            return await inline_query.answer([], cache_time=60)

        switch_text = "По Вашему запросу найдено :"
        answers = []
        query_text = inline_query.query.upper()
        query_arr = query_text.split(" ") if 0 < len(query_text) else []
        user_id = inline_query.from_user.id
        chat_id = 0
        if query_arr:
            # Try to resolve first word as chat identifier (number or @username)
            chat_id = await _resolve_chat_id(bot, query_arr[0])
            if chat_id != 0:
                query_text = " ".join(query_arr[1:]).upper()

        # Empty query means show all commands
        show_all = len(query_text.strip()) == 0

        commands_dict = _get_commands_dict(app_context)

        for key, value in commands_dict.items():
            if show_all or (query_text in key.upper()) or (query_text in value["info"].upper()):
                ico = ""
                if (value["cmd_type"] > 0) and (chat_id < 0):
                    attr_list = _get_attr_list(app_context, value["cmd_list"])
                    if value["cmd_type"] in (1, 2):
                        ico = "🟢 " if chat_id in attr_list else "🔴 "
                    if value["cmd_type"] in (3,):
                        # For cmd_type 3, check nested structure: {chat_id: [user_ids]}
                        in_list = False
                        if chat_id in attr_list:
                            chat_users = attr_list[chat_id]
                            if isinstance(chat_users, list):
                                in_list = user_id in chat_users
                        ico = "🟢 " if in_list else "🔴 "

                answers.append(
                    InlineQueryResultArticle(
                        id=str(len(answers)),
                        title=ico + value["info"],
                        description=key,
                        input_message_content=InputTextMessageContent(message_text=key),
                    )
                )
        return await inline_query.answer(
            answers[:50], cache_time=60, switch_pm_text=switch_text, switch_pm_parameter="xz"
        )
    except Exception as e:
        logger.exception(f"Error in inline_handler: {e}")
        return await inline_query.answer([], cache_time=60)


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router inline was loaded")
