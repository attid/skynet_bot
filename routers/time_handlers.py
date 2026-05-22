import asyncio
import json
from datetime import datetime
import random
from typing import Any, Optional, cast
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from other import aiogram_tools
from db.repositories import MessageRepository
from other.config_reader import config
from other.grist_tools import grist_manager, MTLGrist
from other.loguru_tools import safe_catch_async, safe_catch
from other.pyro_tools import remove_deleted_users
from scripts.check_stellar import cmd_check_grist, cmd_check_bot
from other.constants import MTLChats
from scripts.update_report import lite_report
from services.database_service import DatabaseService
from services.telegram_utils import get_chat_info


@safe_catch_async
async def cmd_send_message_test(bot: Bot):
    master_chat_id: int = MTLChats.TestGroup
    # FOND
    time = datetime.now().time()
    rand = random.randint(2, 10)
    # job = scheduler.get_job('test')
    await bot.send_message(master_chat_id, f"{time} {rand=} job.next_run_time")
    # job.reschedule('interval', minutes=rand)
    # if rand == 10:
    #    job.pause()


# async def cmd_send_message_key_rate(dp: Dispatcher):
#    logger.info(f'cmd_send_message_singers')
#    await dp.bot.send_message(MTLChats.SignGroup, show_key_rate(''), message_thread_id=59558)


@safe_catch_async
async def cmd_send_message_start_month(bot: Bot):
    logger.info("cmd_send_message_singers")
    await bot.send_message(
        MTLChats.SignGroup, "Не пора ли с кучицы и GPA денег стрясти ? /all", message_thread_id=59558
    )


@safe_catch_async
async def cmd_send_message_1m(bot: Bot, session_pool):
    async with session_pool() as session:
        for record in await MessageRepository(session).async_load_new_messages():
            record_any = cast(Any, record)
            try:
                if record_any.update_id > 0:
                    reply_markup = None
                    button_json_raw = cast(str, record_any.button_json or "")
                    if len(button_json_raw) > 10:
                        button_json = json.loads(button_json_raw)
                        reply_markup = InlineKeyboardMarkup(
                            inline_keyboard=[[InlineKeyboardButton(text=button_json["text"], url=button_json["link"])]]
                        )

                    await bot.edit_message_text(
                        chat_id=cast(int, record_any.user_id),
                        message_id=cast(int, record_any.update_id),
                        text=cast(str, record_any.text),
                        disable_web_page_preview=True,
                        reply_markup=reply_markup,
                    )
                else:
                    topic_id = cast(int, record_any.topic_id) if cast(int, record_any.topic_id) > 0 else None
                    await bot.send_message(
                        cast(int, record_any.user_id),
                        cast(str, record_any.text),
                        disable_notification=cast(int, record_any.use_alarm) == 0,
                        disable_web_page_preview=True,
                        message_thread_id=topic_id,
                    )

                record_any.was_send = 1
                await session.commit()
            except Exception as ex:
                record_any.was_send = 2
                await session.commit()
                logger.error(f"Error in cmd_send_message_1m: {ex} {record}")


@safe_catch_async
async def time_check_ledger(bot: Bot, session_pool):
    return  # Todo: fix it to NATS
    # with session_pool() as session:
    #     saved_ledger = int(db_load_bot_value_ext(session, 0, BotValueTypes.LastLedger, '45407700'))
    #     async with aiohttp.ClientSession() as httpsession:
    #         async with httpsession.get(config.horizon_url) as resp:
    #             json_resp = await resp.json()
    #             core_latest_ledger = int(json_resp['history_latest_ledger'])
    #             if core_latest_ledger > saved_ledger + 10:
    #                 db_send_admin_message(session,
    #                                       f'Отставание от горизонта больше чем {core_latest_ledger - saved_ledger}')
    #     queue_size = db_get_ledger_count(session)
    #     if queue_size > 10:
    #         db_send_admin_message(session, f'Очередь в обработке ledger {queue_size}!')


@safe_catch_async
async def time_clear(bot: Bot, db_service: Optional[DatabaseService] = None):
    chats = await grist_manager.load_table_data(MTLGrist.CONFIG_auto_clean, filter_dict={"enabled": [True]})
    for chat in chats:
        try:
            chat_id = chat["chat_id"]
            # Get chat info from database first, fallback to API
            chat_title = str(chat_id)
            if db_service:
                title, _ = await get_chat_info(chat_id, bot, db_service)
                if title:
                    chat_title = title
            else:
                chat_info = await bot.get_chat(chat_id)
                chat_title = chat_info.full_name

            count = await remove_deleted_users(chat_id)
            if count and count > 0:
                await bot.send_message(
                    MTLChats.SpamGroup,
                    f"Finished removing deleted users from {chat_title}. \n Total deleted users: {count}",
                )
        except Exception as e:
            logger.error(f"Error in cmd_delete_dead_members: {e}")
            await bot.send_message(MTLChats.ITolstov, f"An error occurred while removing deleted users: {str(e)}")
        await asyncio.sleep(30)


@safe_catch_async
async def time_usdm_daily(session_pool, bot: Bot):
    from services.app_context import app_context

    stellar_service = app_context.stellar_service
    if not stellar_service:
        logger.error("StellarService is not initialized in AppContext")
        return

    async with session_pool() as session:
        # новая запись
        # ('mtl div 17/12/2021')
        div_list_id = await stellar_service.create_list(session, datetime.now().strftime("usdm div %d/%m/%Y"), 6)
        logger.info(f"Start div pays №{div_list_id}. Step (1/7)")
        result = await stellar_service.calc_usdm_daily(session, div_list_id)
        logger.info(f"Found {len(result)} addresses. Try gen xdr.")
        total_div_sum = sum(record[2] for record in result)
        total_div_sum_str = f"{total_div_sum:.2f}"

        i = 1

        while i > 0:
            i = await stellar_service.gen_xdr(session, div_list_id)
            logger.info(f"Div part done. Need {i} more. Step (3/7)")

        logger.info("Try send div transactions. Step (4/7)")
        i = 1
        e = 1
        while i > 0:
            try:
                i = await stellar_service.send_by_list_id(session, div_list_id)
                logger.info(f"Part done. Need {i} more. Step (5/7)")
            except Exception as err:
                logger.info(str(err))
                logger.error(f"Got error. New attempt {e}. Step (6/7)")
                e += 1
                await asyncio.sleep(10)
                if e > 20:
                    return

        logger.info("All work done. Step (7/7)")
        balances = cast(
            dict[str, Any], await stellar_service.get_balances(stellar_service.addresses.public_usdm_div) or {}
        )
        usdm_left = float(balances.get("USDM", 0)) if balances else 0
        usdm_left_str = f"{usdm_left:.2f}"

        msg = (
            f"Start div pays №{div_list_id}.\n"
            f"Found {len(result)} addresses.\n"
            f"Total payouts sum: {total_div_sum_str}.\n"
            f"Осталось {usdm_left_str} USDM\n"
            f"All work done."
        )
        await bot.send_message(MTLChats.USDMMGroup, msg)


@safe_catch
def scheduler_jobs(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    session_pool,
    db_service: Optional[DatabaseService] = None,
    async_session_pool=None,
):
    message_session_pool = async_session_pool or session_pool
    usdm_session_pool = async_session_pool or session_pool
    check_bot_session_pool = async_session_pool or session_pool
    report_session_pool = async_session_pool or session_pool
    scheduler.add_job(
        cmd_send_message_1m, "interval", seconds=10, args=(bot, message_session_pool), misfire_grace_time=360
    )

    scheduler.add_job(
        cmd_send_message_start_month, "cron", day=1, hour=8, minute=10, args=(bot,), misfire_grace_time=360
    )
    ###########
    # m h  dom mon dow   command

    # Задача проверки транзакций Stellar - отключена, заменена на webhook
    # через stellar_notification_service
    # scheduler.add_job(cmd_check_cron_transaction, "interval", minutes=30, args=(session_pool,),
    #                   misfire_grace_time=360, jitter=120)

    # 30 */3 * * * /home/skynet_bot/deploy/check_stellar.sh check_grist
    scheduler.add_job(cmd_check_grist, "interval", hours=3, minutes=30, misfire_grace_time=360, jitter=120)

    # Задача проверки бота Stellar три раза в день
    # 10 */6 * * * /home/skynet_bot/deploy/check_stellar.sh check_bot
    scheduler.add_job(
        cmd_check_bot,
        "interval",
        hours=6,
        minutes=10,
        args=(check_bot_session_pool,),
        misfire_grace_time=360,
        jitter=120,
    )

    # Другие задачи
    # 17 8 * * * /home/skynet_bot/deploy/mtl_backup.sh > /dev/null*
    # 25 8 * * * /home/skynet_bot/deploy/report.sh > /dev/null
    scheduler.add_job(lite_report, "cron", hour=8, minute=10, args=(report_session_pool,), misfire_grace_time=360)

    scheduler.add_job(time_clear, "interval", hours=10, args=(bot, db_service), misfire_grace_time=360, jitter=120)
    # 30 */8 * * * /opt/firebird/bin/isql -i /db/archive.sql

    ##scheduler.add_job(cmd_send_message_test, "interval", minutes=1, args=(bot,), id='test')
    #### scheduler.add_job(cmd_send_message_10m, "interval", minutes=10, jitter=120, args=(dp,))
    #### scheduler.add_job(cmd_send_message_8h, "interval", hours=8, jitter=800, args=(dp,))
    ### scheduler.add_job(cmd_send_message_key_rate, "cron", day_of_week='fri', hour=8, minute=10, args=(dp,))

    # usdm divs
    scheduler.add_job(time_usdm_daily, "cron", hour=4, minute=4, args=(usdm_session_pool, bot), misfire_grace_time=360)
    ### job.args = (dp, 25,)
    ### await cmd_send_message_10м(dp)


def register_handlers(dp, bot):
    if config.test_mode:
        return
    scheduler = AsyncIOScheduler(timezone="Europe/Podgorica")  # str(tzlocal.get_localzone()))
    aiogram_tools.scheduler = scheduler
    scheduler.start()
    db_service = DatabaseService()
    from db.session import AsyncSessionPool

    scheduler_jobs(scheduler, bot, AsyncSessionPool, db_service, AsyncSessionPool)

    logger.info("router time_handlers was loaded")


cast(Any, register_handlers).priority = 90
