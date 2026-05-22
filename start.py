# Standard library imports
import asyncio
import importlib
import os
from contextlib import suppress

# Third-party imports
import sentry_sdk
import uvloop
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

# Local application imports
from db.session import AsyncSessionPool, async_engine
from db.repositories import ChatsRepository
from middlewares.db import DbSessionMiddleware
from middlewares.emoji_reaction import EmojiReactionMiddleware
from middlewares.message_thread_cache import MessageThreadCacheMiddleware
from middlewares.retry import RetryRequestMiddleware
from middlewares.sentry_error_handler import sentry_error_handler
from middlewares.throttling import ThrottlingMiddleware
from middlewares.app_context import AppContextMiddleware
from middlewares.user_resolver import UserResolverMiddleware
from other.config_reader import config
from other.constants import MTLChats
from other.pyro_tools import pyro_start
from services.command_registry_service import get_pending_commands
from services.health_server import start_health_server
from services.message_thread_cache import RedisMessageThreadCacheService

# Task list for background asyncio tasks - was previously in global_data
global_tasks = []

# Reboot flag - was previously in global_data
_reboot_flag = False

# User cache is handled by spam_status_service inside app_context

GIT_COMMIT = os.environ.get("GIT_COMMIT", "unknown")
logger.info(f"start (commit: {GIT_COMMIT})")


async def set_commands(bot):
    # commands_clear = []
    commands_admin = [
        BotCommand(
            command="start",
            description="Start or ReStart bot",
        ),
        BotCommand(
            command="restart",
            description="ReStart bot",
        ),
        BotCommand(
            command="fee",
            description="check fee",
        ),
    ]
    commands_private = [
        BotCommand(
            command="start",
            description="Start or ReStart bot",
        ),
    ]
    # commands_treasury = [
    #     BotCommand(
    #         command="balance",
    #         description="Show balance",
    #     ),
    # ]

    await bot.set_my_commands(commands=commands_private, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(commands=commands_admin, scope=BotCommandScopeChat(chat_id=84131737))
    # await bot.set_my_commands(commands=commands_treasury, scope=BotCommandScopeChat(chat_id=-1001169382324))


async def on_startup(bot: Bot, dispatcher: Dispatcher):
    await set_commands(bot)
    with suppress(TelegramBadRequest):
        await bot.send_message(chat_id=MTLChats.ITolstov, text=f"Bot started (commit: {GIT_COMMIT})")

    if config.test_mode:
        logger.info("test mode")
        # await pyro_start()
    else:
        await pyro_start()


async def on_shutdown(bot: Bot):
    with suppress(TelegramBadRequest):
        await bot.send_message(chat_id=MTLChats.ITolstov, text="Bot stopped")

    # Stop stellar notification service
    import services.app_context as app_context_module

    if app_context_module.app_context and app_context_module.app_context.stellar_notification_service:
        await app_context_module.app_context.stellar_notification_service.stop()

    for task in global_tasks:
        task.cancel()

    await async_engine.dispose()


async def load_routers(dp: Dispatcher, bot: Bot):
    """Динамическая загрузка и регистрация роутеров"""
    import os

    routers_path = os.path.join(os.path.dirname(__file__), "routers")
    router_modules = []
    registered_handlers = set()  # Для отслеживания уже зарегистрированных обработчиков

    # Загрузка всех модулей роутеров
    for filename in os.listdir(routers_path):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = f"routers.{filename[:-3]}"
            try:
                module = importlib.import_module(module_name)
                if hasattr(module, "register_handlers"):
                    # Проверка на дублирование модуля
                    if module.__name__ in registered_handlers:
                        logger.warning(f"Skipping duplicate router module: {module.__name__}")
                        continue

                    # Установка дефолтного приоритета, если не указан
                    if not hasattr(module.register_handlers, "priority"):
                        module.register_handlers.priority = 50
                    router_modules.append(module)
                    registered_handlers.add(module.__name__)
                    logger.info(f"Found router module {module_name} with priority {module.register_handlers.priority}")
            except Exception as e:
                logger.error(f"Error loading module {module_name}: {e}", exc_info=True)

    # Сортировка модулей по приоритету
    router_modules.sort(key=lambda m: getattr(m.register_handlers, "priority", 50))

    # Регистрация роутеров в порядке приоритета
    for module in router_modules:
        try:
            logger.debug(f"Registering handlers from {module.__name__}")
            module.register_handlers(dp, bot)
            logger.info(f"Successfully registered handlers from {module.__name__}")
        except Exception as e:
            logger.error(f"Error registering handlers from {module.__name__}: {e}", exc_info=True)

    logger.info(f"Total router modules loaded: {len(router_modules)}")


async def main():
    logger.add("logs/skynet.log", rotation="1 MB", level="INFO")

    # Запуск бота
    engine = create_engine(config.postgres_url, pool_pre_ping=True, max_overflow=50)
    # Creating DB connections pool
    db_pool = sessionmaker(bind=engine)

    # Creating bot and its dispatcher
    if config.telegram_api_url:
        api_server = TelegramAPIServer.from_base(config.telegram_api_url, is_local=True)
        session: AiohttpSession = AiohttpSession(api=api_server)
        logger.info(f"Using local Telegram Bot API: {config.telegram_api_url}")
    else:
        session = AiohttpSession()
    session.middleware(RetryRequestMiddleware())
    if config.test_mode:
        bot = Bot(
            token=config.test_token.get_secret_value(), default=DefaultBotProperties(parse_mode="HTML"), session=session
        )
        logger.info("start test")
    else:
        bot = Bot(
            token=config.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode="HTML"), session=session
        )

    redis = Redis.from_url(config.redis_url)
    storage = RedisStorage(redis=redis)
    dp = Dispatcher(storage=storage)

    # Настройка middleware
    app_context_middleware = AppContextMiddleware(bot)
    dp.message.middleware(DbSessionMiddleware(db_pool))
    dp.callback_query.middleware(DbSessionMiddleware(db_pool, lazy=True))
    dp.inline_query.middleware(DbSessionMiddleware(db_pool))
    dp.chat_member.middleware(DbSessionMiddleware(AsyncSessionPool))
    dp.channel_post.middleware(DbSessionMiddleware(db_pool))
    dp.edited_channel_post.middleware(DbSessionMiddleware(db_pool))
    dp.poll_answer.middleware(DbSessionMiddleware(db_pool))
    dp.message_reaction.middleware(DbSessionMiddleware(db_pool))

    dp.message.middleware(app_context_middleware)
    dp.callback_query.middleware(app_context_middleware)
    dp.inline_query.middleware(app_context_middleware)
    dp.chat_member.middleware(app_context_middleware)
    dp.channel_post.middleware(app_context_middleware)
    dp.edited_channel_post.middleware(app_context_middleware)
    dp.poll_answer.middleware(app_context_middleware)
    dp.message_reaction.middleware(app_context_middleware)

    app_context_middleware.app_context.message_thread_cache_service = RedisMessageThreadCacheService(redis)
    dp.message.middleware(MessageThreadCacheMiddleware())

    # UserResolverMiddleware resolves user_id from channel links
    user_resolver_middleware = UserResolverMiddleware(app_context_middleware.app_context, bot)
    dp.message.middleware(user_resolver_middleware)
    dp.callback_query.middleware(user_resolver_middleware)
    dp.chat_member.middleware(user_resolver_middleware)
    dp.message_reaction.middleware(user_resolver_middleware)

    dp.message.middleware(ThrottlingMiddleware(redis=redis))
    dp.message.middleware(EmojiReactionMiddleware())

    dp["dbsession_pool"] = db_pool
    dp["app_context"] = app_context_middleware.app_context

    # Update global singleton for modules that import app_context directly
    import services.app_context as app_context_module

    app_context_module.app_context = app_context_middleware.app_context

    global_tasks.append(asyncio.create_task(load_globals(AsyncSessionPool, bot, app_context_middleware.app_context)))

    # Start health server for Docker healthcheck
    _health_runner = await start_health_server(app_context_middleware.app_context.bot_state_service)

    # Initialize and start Stellar notification service
    app_context_middleware.app_context.init_stellar_notification_service(bot, db_pool)
    stellar_service = app_context_middleware.app_context.stellar_notification_service
    if stellar_service:
        await stellar_service.start_server()
        if not config.test_mode:
            # Initial sync of subscriptions
            global_tasks.append(asyncio.create_task(stellar_service.sync_subscriptions()))
            # Periodic sync task
            global_tasks.append(asyncio.create_task(stellar_service.periodic_sync_task(interval_hours=1)))

    # Загрузка и регистрация роутеров
    await load_routers(dp, bot)

    # Reload commands into command_registry after routers are loaded
    # (decorators @update_command_info populate _pending_commands at import time)
    pending_commands = get_pending_commands()
    if pending_commands:
        app_context_middleware.app_context.command_registry.load_commands(pending_commands)
        logger.info(f"Loaded {len(pending_commands)} commands into command_registry")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    dp.errors.register(sentry_error_handler)

    # Запускаем бота и пропускаем все накопленные входящие
    # Да, этот метод можно вызвать даже если у вас поллинг
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info(dp.resolve_used_update_types())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def load_globals(session_pool, bot: Bot, app_context):
    async with session_pool() as session:
        users = await ChatsRepository(session).async_load_bot_users()
    if app_context and app_context.spam_status_service:
        try:
            app_context.spam_status_service.preload_statuses({user.user_id: user.user_type for user in users})
        except ValueError as e:
            logger.warning(f"spam_status_service preload failed: {e}")
    with suppress(TelegramBadRequest):
        await bot.send_message(chat_id=MTLChats.ITolstov, text="globals loaded")


def add_bot_users(session: Session, user_id: int, username: str | None, new_user_type: int = 0):
    """Добавляет или обновляет пользователя в списке с логированием"""
    try:
        from services import app_context as app_context_module

        if app_context_module.app_context and app_context_module.app_context.spam_status_service:
            app_context_module.app_context.spam_status_service.preload_statuses({user_id: new_user_type})
    except Exception as e:
        logger.warning(f"spam_status_service cache update failed: {e}")
    ChatsRepository(session).save_bot_user(user_id, username, new_user_type)


async def async_add_bot_users(session: AsyncSession, user_id: int, username: str | None, new_user_type: int = 0):
    """Add or update bot user using async SQLAlchemy session."""
    try:
        from services import app_context as app_context_module

        if app_context_module.app_context and app_context_module.app_context.spam_status_service:
            app_context_module.app_context.spam_status_service.preload_statuses({user_id: new_user_type})
    except Exception as e:
        logger.warning(f"spam_status_service cache update failed: {e}")
    await ChatsRepository(session).async_save_bot_user(user_id, username, new_user_type)


if __name__ == "__main__":
    if len(config.sentry_dsn) > 20:
        sentry_sdk.init(
            dsn=config.sentry_dsn,
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
        )
    else:
        logger.warning("sentry_dsn is bad. Not start it")
    try:
        # import logging
        # logging.basicConfig(level=logging.DEBUG)
        uvloop.install()
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.error("Exit")
    except Exception as e:
        if not _reboot_flag:
            logger.exception(e)
            raise e
