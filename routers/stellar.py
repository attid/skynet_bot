from datetime import datetime
import re
from urllib.parse import quote
from typing import Any, cast

from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.enums import ChatMemberStatus
from aiogram.types import Message, FSInputFile
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from other.aiogram_tools import describe_reply_dump, extract_reply_url, message_full_text
from other.config_reader import start_path
from other.constants import MTLChats
from other.utils import float2str
from services.command_registry_service import update_command_info
from services.skyuser import SkyUser

router = Router()

# Raw XDR is a long base64 blob; a replied message with such a token is decoded too.
_XDR_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=]{32,}$")


def _is_full_data(app_context: Any, chat_id: int) -> bool:
    """Resolve the per-chat ``full_data`` flag from the feature-flag service."""
    feature_flags = getattr(app_context, "feature_flags", None)
    if feature_flags is None:
        return False
    try:
        return bool(feature_flags.is_full_data(chat_id))
    except Exception:
        logger.exception("decode: cannot resolve full_data flag, chat={}", chat_id)
        return False


def _resolve_decode_argument(message: Message) -> tuple[str | None, str]:
    """Pick what to decode: command argument first, then the replied message.

    Returns:
        ``(argument, source)`` where source is ``command``, ``reply_url``,
        ``reply_xdr`` or ``none``.
    """
    tokens = (message.text or "").split(maxsplit=1)
    if len(tokens) > 1 and tokens[1].strip():
        return tokens[1].split()[0], "command"

    reply = message.reply_to_message
    if reply is not None:
        url = extract_reply_url(message)
        if url:
            return url, "reply_url"
        reply_text = message_full_text(reply).strip()
        if _XDR_TOKEN_RE.match(reply_text):
            return reply_text, "reply_xdr"
    return None, "none"


def _describe_message(message: Message) -> str:
    """Compact message context for logs (chat, forum thread, replied message)."""
    reply = message.reply_to_message
    return (
        f"chat={message.chat.id if message.chat else None} "
        f"thread={message.message_thread_id} topic={message.is_topic_message} "
        f"msg={message.message_id} reply_msg={reply.message_id if reply else None}"
    )


@update_command_info("/fee", "показать комиссию в стелларе")
@router.message(Command(commands=["fee"]))
async def cmd_fee(message: Message, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    fee = await ctx.stellar_service.check_fee()
    await message.answer("Комиссия (мин и мах) " + fee)


@update_command_info("/decode", "декодирует xdr использовать: /decode xdr где ")
@router.message(Command(commands=["decode"]))
async def cmd_decode(message: Message, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    argument, source = _resolve_decode_argument(message)
    full_data = _is_full_data(ctx, message.chat.id if message.chat else 0)
    logger.debug(
        "decode: {} source={} full_data={} text={!r} reply_text={!r}",
        _describe_message(message),
        source,
        full_data,
        message.text,
        message_full_text(message.reply_to_message) if message.reply_to_message else None,
    )

    if not argument:
        logger.info(
            "decode: nothing to decode, {} | {}",
            _describe_message(message),
            describe_reply_dump(message),
        )
        await message.reply(
            "Не вижу, что декодировать. Пришли <code>/decode XDR</code> или "
            "<code>/decode ссылка на тулзу</code>, либо ответь командой на сообщение со ссылкой."
        )
        return

    try:
        if "eurmtl.me" in argument:
            logger.debug("decode: fetching url {}", argument)
            msg = await ctx.stellar_service.check_url_xdr(argument, full_data=full_data)
        else:
            msg = await ctx.stellar_service.decode_xdr(argument, full_data=full_data)
        msg = "\n".join(msg)
    except Exception as e:
        logger.exception(
            "decode failed: {} source={} full_data={} argument={!r}",
            _describe_message(message),
            source,
            full_data,
            argument,
        )
        await message.reply(f"Не смог декодировать: {type(e).__name__}: {e}"[:4000])
        return

    if not msg:
        logger.info("decode: empty result, {} argument={!r}", _describe_message(message), argument)
        await message.reply("Декодировать нечего — пустой результат.")
        return

    await ctx.utils_service.multi_reply(message, msg)


@update_command_info("/show_bim", "показать инфо по БДM")
@router.message(Command(commands=["show_bim"]))
async def rt_show_bim_msg(message: Message, session: AsyncSession, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    res = await ctx.stellar_service.show_bim(session)
    await message.answer(res)


@update_command_info("/balance", "Показать сколько денег или мулек(EURMTL) в кубышке")
@router.message(Command(commands=["balance"]))
async def cmd_show_balance(message: Message, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    result = await ctx.stellar_service.get_cash_balance(message.chat.id)
    from other.img_tools import create_image_with_text

    create_image_with_text(result, image_size=(550, None))
    await message.answer_photo(FSInputFile(start_path + "/data/output_image.png"))


@router.message(Command(commands=["do_council"]))
async def cmd_do_council(message: Message, session: AsyncSession, app_context=None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    addresses = ctx.stellar_service.addresses
    assets = ctx.stellar_service.assets

    balance = await ctx.stellar_service.get_balances(addresses.public_council)
    eurmtl_balance = float(balance.get("EURMTL", 0) or 0)
    if eurmtl_balance > 5:
        swap_xdr = await ctx.stellar_service.build_swap_xdr(
            source_address=addresses.public_council,
            send_asset=assets.eurmtl_asset,
            send_amount=float2str(eurmtl_balance),
            receive_asset=assets.labr_asset,
            receive_amount="0.0000001",
        )
        signed_swap = ctx.stellar_service.sign(swap_xdr)
        await ctx.stellar_service.async_submit(signed_swap)
        balance = await ctx.stellar_service.get_balances(addresses.public_council)

    labr_balance = float(balance.get("LABR", 0) or 0)
    if labr_balance <= 1:
        await message.reply(f"Low balance at {addresses.public_council} can`t pay")
        return
    url = "https://labrdistributiontx-e62teamaya-lm.a.run.app/?address=" + addresses.public_council

    response = await ctx.web_service.get(url, return_type="json")

    distribution_message = "Distribution:\n"
    for address, amount in response.data["distribution"].items():
        shortened_address = address[:4] + ".." + address[-4:]
        distribution_message += f"{shortened_address}: {amount}\n"

    await message.answer(distribution_message)

    signed = ctx.stellar_service.sign(response.data["xdr"])
    await ctx.stellar_service.async_submit(signed)
    await message.answer("Work done.")


@router.message(Command(commands=["do_bim"]))
async def cmd_do_bim(message: Message, session: AsyncSession, app_context=None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    addresses = ctx.stellar_service.addresses
    balance = await ctx.stellar_service.get_balances(addresses.public_bod_eur)

    if int(balance.get("EURMTL", 0)) < 10:
        await message.reply(f"Low balance at {addresses.public_bod_eur} can`t pay BIM")
        return

    # новая запись
    list_id = await ctx.stellar_service.create_list(session, datetime.now().strftime("Basic Income %d/%m/%Y"), 1)

    lines = []
    msg = await message.answer(ctx.utils_service.add_text(lines, 1, f"Start BDM pays. PayID №{list_id}. Step (1/7)"))

    result = await ctx.stellar_service.calc_bim_pays(session, list_id)

    await msg.edit_text(ctx.utils_service.add_text(lines, 2, f"Found {len(result)} addresses. Try gen xdr. Step (2/7)"))

    i = 1
    while i > 0:
        i = await ctx.stellar_service.gen_xdr(session, list_id)
        await msg.edit_text(ctx.utils_service.add_text(lines, 3, f"Part done. Need {i} more. Step (3/7)"))

    await msg.edit_text(ctx.utils_service.add_text(lines, 4, "Try send transactions. Step (4/7)"))
    i = 1
    e = 1
    while i > 0:
        try:
            i = await ctx.stellar_service.send_by_list_id(session, list_id)
            await msg.edit_text(ctx.utils_service.add_text(lines, 5, f"Part done. Need {i} more. Step (5/7)"))
        except Exception:
            await msg.edit_text(ctx.utils_service.add_text(lines, 6, f"Got error. New attempt {e}. Step (6/7)"))
            e += 1
    await msg.edit_text(ctx.utils_service.add_text(lines, 7, "BDM. Work done. Step (7/7)"))


@update_command_info("/do_resend", "Переотправить транзакцию. Только для админов")
@router.message(Command(commands=["do_resend"]))
async def cmd_do_key_rate(message: Message, session: AsyncSession, app_context=None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False

    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    parts = (message.text or "").split()
    if len(parts) > 1:
        list_id = int(parts[1])
        lines = []
        msg = await message.answer(ctx.utils_service.add_text(lines, 1, f"Start resend. PayID №{list_id}. Step (1/6)"))

        await msg.edit_text(ctx.utils_service.add_text(lines, 3, "Try send transactions. Step (2/6)"))
        i = 1
        e = 1
        while i > 0:
            try:
                i = await ctx.stellar_service.send_by_list_id(session, list_id)
                await msg.edit_text(ctx.utils_service.add_text(lines, 4, f"Part done. Need {i} more. Step (3/6)"))
            except Exception as err:
                await msg.edit_text(ctx.utils_service.add_text(lines, 5, f"Got error. New attempt {e}. Step (4/6)"))
                logger.info(f"249 line error {err}")
                e += 1
        await msg.edit_text(ctx.utils_service.add_text(lines, 6, "Resend. Work done. Step (5/6)"))


@router.message(Command(commands=["do_all"]))
async def cmd_do_all(message: Message, session: AsyncSession, app_context=None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False

    await cmd_do_div(message, session=session, app_context=app_context, skyuser=skyuser)
    await cmd_do_sats_div(message, session=session, app_context=app_context, skyuser=skyuser)
    await rt_show_bim_msg(message, session=session, app_context=app_context)
    await cmd_do_bim(message, session=session, app_context=app_context, skyuser=skyuser)


@update_command_info("/do_div", "начать выплаты дивидентов")
@router.message(Command(commands=["do_div"]))
async def cmd_do_div(message: Message, session: AsyncSession, app_context=None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return

    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    addresses = ctx.stellar_service.addresses
    balance = await ctx.stellar_service.get_balances(addresses.public_div)

    if int(balance.get("EURMTL", 0)) < 10:
        await message.reply(f"Low balance at {addresses.public_div} can`t pay divs")
        return

    div_list_id = await ctx.stellar_service.create_list(session, datetime.now().strftime("mtl div %d/%m/%Y"), 0)
    donate_list_id = await ctx.stellar_service.create_list(session, datetime.now().strftime("donate %d/%m/%Y"), 0)

    lines = []
    msg = await message.answer(
        ctx.utils_service.add_text(
            lines, 1, f"Start div pays №{div_list_id} donate pays №{donate_list_id}. Step (1/12)"
        )
    )

    result = await ctx.stellar_service.calc_divs(session, div_list_id, donate_list_id)

    await msg.edit_text(
        ctx.utils_service.add_text(lines, 2, f"Found {len(result)} addresses. Try gen xdr. Step (2/12)")
    )

    i = 1

    while i > 0:
        i = await ctx.stellar_service.gen_xdr(session, div_list_id)
        await msg.edit_text(ctx.utils_service.add_text(lines, 3, f"Div part done. Need {i} more. Step (3/12)"))

    i = 1
    while i > 0:
        i = await ctx.stellar_service.gen_xdr(session, donate_list_id)
        await msg.edit_text(ctx.utils_service.add_text(lines, 4, f"Donate part done. Need {i} more. Step (4/12)"))

    await msg.edit_text(ctx.utils_service.add_text(lines, 5, "Try send div transactions. Step (5/12)"))
    i = 1
    e = 1
    while i > 0:
        try:
            i = await ctx.stellar_service.send_by_list_id(session, div_list_id)
            await msg.edit_text(ctx.utils_service.add_text(lines, 6, f"Part done. Need {i} more. Step (6/12)"))
        except Exception as err:
            logger.info(str(err))
            await msg.edit_text(ctx.utils_service.add_text(lines, 7, f"Got error. New attempt {e}. Step (7/12)"))
            e += 1
    await msg.edit_text(ctx.utils_service.add_text(lines, 8, "All work done. Step (8/12)"))

    await msg.edit_text(ctx.utils_service.add_text(lines, 9, "Try send donate transactions. Step (9/12)"))
    i = 1
    e = 1
    while i > 0:
        try:
            i = await ctx.stellar_service.send_by_list_id(session, donate_list_id)
            await msg.edit_text(ctx.utils_service.add_text(lines, 10, f"Part done. Need {i} more. Step (10/12)"))
        except Exception:
            await msg.edit_text(ctx.utils_service.add_text(lines, 11, f"Got error. New attempt {e}. Step (11/12)"))
            e += 1
    await msg.edit_text(ctx.utils_service.add_text(lines, 12, "All work done. Step (12/12)"))


@update_command_info("/do_sats_div", "выплата дивидентов в satsmtl")
@router.message(Command(commands=["do_sats_div"]))
async def cmd_do_sats_div(message: Message, session: AsyncSession, app_context=None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return

    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    addresses = ctx.stellar_service.addresses
    balance = await ctx.stellar_service.get_balances(addresses.public_div)

    if int(balance.get("SATSMTL", 0)) < 100:
        await message.reply(f"Low sats balance at {addresses.public_div} can`t pay divs")
        return

    div_list_id = await ctx.stellar_service.create_list(session, datetime.now().strftime("mtl div %d/%m/%Y"), 4)

    lines = []
    msg = await message.answer(ctx.utils_service.add_text(lines, 1, f"Start div pays №{div_list_id}. Step (1/12)"))

    result = await ctx.stellar_service.calc_sats_divs(session, div_list_id)

    await msg.edit_text(
        ctx.utils_service.add_text(lines, 2, f"Found {len(result)} addresses. Try gen xdr. Step (2/12)")
    )

    i = 1

    while i > 0:
        i = await ctx.stellar_service.gen_xdr(session, div_list_id)
        await msg.edit_text(ctx.utils_service.add_text(lines, 3, f"Div part done. Need {i} more. Step (3/12)"))

    await msg.edit_text(ctx.utils_service.add_text(lines, 4, "Try send div transactions. Step (4/12)"))
    i = 1
    e = 1
    while i > 0:
        try:
            i = await ctx.stellar_service.send_by_list_id(session, div_list_id)
            await msg.edit_text(ctx.utils_service.add_text(lines, 5, f"Part done. Need {i} more. Step (5/12)"))
        except Exception as err:
            logger.info(str(err))
            await msg.edit_text(ctx.utils_service.add_text(lines, 6, f"Got error. New attempt {e}. Step (6/12)"))
            e += 1
    await msg.edit_text(ctx.utils_service.add_text(lines, 7, "All work done. Step (7/12)"))


@router.message(Command(commands=["do_usdm_div"]))
async def cmd_do_usdm_div(message: Message, session: AsyncSession, app_context=None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return

    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    addresses = ctx.stellar_service.addresses
    balance = await ctx.stellar_service.get_balances(addresses.public_div)

    if int(balance.get("USDM", 0)) < 10:
        await message.reply(f"Low usdm balance at {addresses.public_div} can`t pay divs")
        return

    div_list_id = await ctx.stellar_service.create_list(session, datetime.now().strftime("mtl div %d/%m/%Y"), 5)

    lines = []
    msg = await message.answer(ctx.utils_service.add_text(lines, 1, f"Start div pays №{div_list_id}. Step (1/12)"))

    result = await ctx.stellar_service.calc_usdm_divs(session, div_list_id)

    await msg.edit_text(
        ctx.utils_service.add_text(lines, 2, f"Found {len(result)} addresses. Try gen xdr. Step (2/12)")
    )

    i = 1

    while i > 0:
        i = await ctx.stellar_service.gen_xdr(session, div_list_id)
        await msg.edit_text(ctx.utils_service.add_text(lines, 3, f"Div part done. Need {i} more. Step (3/12)"))

    await msg.edit_text(ctx.utils_service.add_text(lines, 4, "Try send div transactions. Step (4/12)"))
    i = 1
    e = 1
    while i > 0:
        try:
            i = await ctx.stellar_service.send_by_list_id(session, div_list_id)
            await msg.edit_text(ctx.utils_service.add_text(lines, 5, f"Part done. Need {i} more. Step (5/12)"))
        except Exception as err:
            logger.info(str(err))
            await msg.edit_text(ctx.utils_service.add_text(lines, 6, f"Got error. New attempt {e}. Step (6/12)"))
            e += 1
    await msg.edit_text(ctx.utils_service.add_text(lines, 7, "All work done. Step (7/12)"))


@update_command_info("/do_usdm_usdm_div_daily", "выплата дивидентов в usdm от usdm")
@router.message(Command(commands=["do_usdm_usdm_div_daily"]))
async def cmd_do_usdm_usdm_div(
    message: Message, session: AsyncSession, app_context=None, skyuser: SkyUser | None = None
):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return

    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    addresses = ctx.stellar_service.addresses
    balance = await ctx.stellar_service.get_balances(addresses.public_usdm_div)

    if int(balance.get("USDM", 0)) < 100:
        await message.reply(f"Low usdm balance at {addresses.public_usdm_div} can`t pay divs")
        return

    div_list_id = await ctx.stellar_service.create_list(session, datetime.now().strftime("usdm div %d/%m/%Y"), 6)

    lines = []
    msg = await message.answer(ctx.utils_service.add_text(lines, 1, f"Start div pays №{div_list_id}. Step (1/12)"))

    result = await ctx.stellar_service.calc_usdm_daily(session, div_list_id)

    await msg.edit_text(
        ctx.utils_service.add_text(lines, 2, f"Found {len(result)} addresses. Try gen xdr. Step (2/12)")
    )

    i = 1

    while i > 0:
        i = await ctx.stellar_service.gen_xdr(session, div_list_id)
        await msg.edit_text(ctx.utils_service.add_text(lines, 3, f"Div part done. Need {i} more. Step (3/12)"))

    await msg.edit_text(ctx.utils_service.add_text(lines, 4, "Try send div transactions. Step (4/12)"))
    i = 1
    e = 1
    while i > 0:
        try:
            i = await ctx.stellar_service.send_by_list_id(session, div_list_id)
            await msg.edit_text(ctx.utils_service.add_text(lines, 5, f"Part done. Need {i} more. Step (5/12)"))
        except Exception as err:
            logger.info(str(err))
            await msg.edit_text(ctx.utils_service.add_text(lines, 6, f"Got error. New attempt {e}. Step (6/12)"))
            e += 1
    await msg.edit_text(ctx.utils_service.add_text(lines, 7, "All work done. Step (7/12)"))


@update_command_info("/do_usdm_usdm_div_test", "test выплата дивидентов в usdm от usdm")
@router.message(Command(commands=["do_usdm_usdm_div_test"]))
async def cmd_do_usdm_usdm_div_test(message: Message, session: AsyncSession, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    if message.chat.id != MTLChats.USDMMGroup:
        await message.reply("Wrong chat")
        return

    parts = (message.text or "").split()
    test_sum = float(parts[1]) if len(parts) > 1 else 1000

    calc = await ctx.stellar_service.calc_usdm_usdm_divs(
        session=session,
        div_list_id=0,
        test_sum=test_sum,
        test_for_address="GCLQ6TKOOJW33ABVG5D5KKJBZANSDW46BCXTSQ3TKLRYFPAVFZENUMON",
    )
    # [['GCLQ6TKOOJW33ABVG5D5KKJBZANSDW46BCXTSQ3TKLRYFPAVFZENUMON', 1000.0, 5.97253, 5.97253, 0]]
    await message.answer(f"current balance {calc[0][1]}\npay from {test_sum} will be {calc[0][2]}")


def _vote_xdr_summary(result: Any) -> str:
    """Describe what the vote XDR builder actually changed."""
    updated = getattr(result, "updated", []) or []
    skipped = getattr(result, "skipped", []) or []
    if not updated:
        return f"Изменений нет: все {len(skipped)} аккаунтов уже в нужном состоянии."
    return f"Обновлено аккаунтов: {len(updated)}, без изменений: {len(skipped)}."


@update_command_info("/get_vote_fund_xdr", "сделать транзакцию на обновление голосов фонда")
@router.message(Command(commands=["get_vote_fund_xdr"]))
async def cmd_get_vote_fund_xdr(message: Message, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    parts = (message.text or "").split()
    if len(parts) > 1:
        result = await ctx.stellar_service.get_new_vote_all_mtl(parts[1])
        await _send_vote_xdr(message, ctx, result)
        return

    await message.answer("Делаю транзакции подождите несколько секунд")
    result = await ctx.stellar_service.get_new_vote_all_mtl("")
    await _send_vote_xdr(message, ctx, result)


async def _send_vote_xdr(message: Message, ctx: Any, result: Any) -> None:
    """Send the vote XDR (as text or file) plus a short summary of the changes."""
    summary = _vote_xdr_summary(result)
    xdr = getattr(result, "xdr", None)
    if not xdr:
        await message.answer(summary)
        return
    if len(xdr) > 4000:
        await ctx.utils_service.answer_text_file(message, xdr, "vote_fund_xdr.txt")
    else:
        await message.answer(xdr)
    await message.answer(summary)


@update_command_info(
    "/get_btcmtl_xdr", "use - /get_btcmtl_xdr 0.001 XXXXXXX \n where 0.001 sum, XXXXXXXX address to send BTCMTL"
)
@router.message(Command(commands=["get_btcmtl_xdr"]))
async def cmd_get_btcmtl_xdr(message: Message, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    arg = (message.text or "").split()
    if len(arg) > 1:
        memo = None if len(arg) < 3 else " ".join(arg[3:])
        xdr = await ctx.stellar_service.get_btcmtl_xdr(float2str(arg[1]), arg[2], memo)
        decoded = await ctx.stellar_service.decode_xdr(xdr=xdr)

        await ctx.utils_service.multi_answer(message, xdr)
        await ctx.utils_service.multi_answer(message, "\n".join(decoded))
    else:
        await ctx.utils_service.multi_answer(
            message, "use -  /get_btcmtl_xdr 0.001 XXXXXXX \n where 0.001 sum, XXXXXXXX address to send BTCMTL"
        )


@router.message(Command(commands=["get_damircoin_xdr"]))
async def cmd_get_damircoin_xdr(message: Message, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    arg = (message.text or "").split()
    if len(arg) > 1:
        xdr = await ctx.stellar_service.get_damircoin_xdr(int(arg[1]))
        decoded = await ctx.stellar_service.decode_xdr(xdr=xdr)

        await ctx.utils_service.multi_answer(message, xdr)
        await ctx.utils_service.multi_answer(message, "\n".join(decoded))
    else:
        await ctx.utils_service.multi_answer(message, "use -  /get_damircoin_xdr 123 \n where 123 sum in EURMTL")


@router.message(Command(commands=["get_agora_xdr"]))
async def cmd_get_agora_xdr(message: Message, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    xdr = await ctx.stellar_service.get_agora_xdr()
    decoded = await ctx.stellar_service.decode_xdr(xdr=xdr)

    await ctx.utils_service.multi_answer(message, xdr)
    await ctx.utils_service.multi_answer(message, "\n".join(decoded))


@update_command_info("/get_chicago_xdr", "Делает транзакцию кешбека для chicago")
@router.message(Command(commands=["get_chicago_xdr"]))
async def cmd_get_chicago_xdr(message: Message, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    result = await ctx.stellar_service.get_chicago_xdr()

    xdr = result[-1]
    await ctx.utils_service.multi_answer(message, "\n".join(result[:-1]))
    if len(xdr) < 4000:
        await ctx.utils_service.multi_answer(message, xdr)
    else:
        text = (
            "Не могу отправить xdr вы можете получить его по ссылке "
            + f'<a href="https://eurmtl.me/sign_tools?xdr={quote(xdr)}">xdr</a>'
        )
        await message.answer(text)

    decoded = await ctx.stellar_service.decode_xdr(xdr=xdr)

    await ctx.utils_service.multi_answer(message, "\n".join(decoded))


@router.message(Command(commands=["get_toc_xdr"]))
async def cmd_get_toc_xdr(message: Message, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    arg = (message.text or "").split()
    if len(arg) > 1:
        xdr = await ctx.stellar_service.get_toc_xdr(int(arg[1]))
        decoded = await ctx.stellar_service.decode_xdr(xdr=xdr)

        await ctx.utils_service.multi_answer(message, xdr)
        await ctx.utils_service.multi_answer(message, "\n".join(decoded))
    else:
        await ctx.utils_service.multi_answer(message, "use -  /get_toc_xdr 123 \n where 123 sum in EURMTL")


@update_command_info("/update_airdrops", "Обновить файл airdrops")
@router.message(Command(commands=["update_airdrops"]))
async def cmd_update_airdrops(message: Message, app_context=None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return False

    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    await message.answer("Запускаю полное обновление")
    await ctx.report_service.update_airdrop()
    await message.answer("Обновление завершено")


@router.message(Command(commands=["update_fest"]))
async def cmd_update_fest(message: Message, session: AsyncSession, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    await message.answer("Запускаю полное обновление")
    await ctx.report_service.update_fest(session)
    await message.answer("Обновление завершено")


@update_command_info("/show_data", "Показать какие данные есть в стеларе на этот адрес. Use: /show_data public_key")
@update_command_info("/show_data bdm", "Показать какие данные есть в стеларе по боду")
@update_command_info("/show_data delegate", "Показать какие данные есть в стеларе по делегированию")
@update_command_info("/show_data donate", "Показать какие данные есть в стеларе по донатам в правительство")
@router.message(Command(commands=["show_data"]))
async def route_show_data(message: Message, app_context=None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    parts = (message.text or "").split()
    if len(parts) > 1:
        result = await ctx.stellar_service.show_data(parts[1])

        if len(result) == 0:
            await message.reply("Data not found")
        else:
            await ctx.utils_service.multi_reply(message, "\n".join(result))
        return
    # else
    await message.reply("Wrong format. Use: /show_data public_key")


@router.message(Command(commands=["update_bim1"]))
async def cmd_update_bim1(message: Message, bot: Bot, app_context=None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    agc = await ctx.gspread_service.authorize()

    wks = await (await agc.open("MTL_BIM_register")).worksheet("List")
    update_list = []
    data = await wks.get_all_values()
    for record in data[2:]:
        new_data = None
        if record[3]:
            try:
                chat_member = await bot.get_chat_member(chat_id=MTLChats.ShareholderGroup, user_id=int(record[3]))
                new_data = chat_member.status not in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]
            except Exception:
                new_data = False
        update_list.append([new_data])

    await wks.update(range_name="S3", values=update_list)
    await message.reply("Done")


@router.message(Command(commands=["check_bim"]))
async def cmd_check_bim(message: Message, app_context=None, skyuser: SkyUser | None = None):
    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    cmd = (message.text or "").split()
    if len(cmd) > 1 and cmd[1][0] == "@":
        if not skyuser or not skyuser.is_skynet_admin():
            await message.reply("You are not my admin.")
            return
        msg = await ctx.gspread_service.check_bim(user_id_or_name=cmd[1][1:])
    else:
        if not message.from_user:
            await message.reply("Cannot identify user.")
            return
        msg = await ctx.gspread_service.check_bim(user_id_or_name=message.from_user.id)

    await message.reply(msg)


@router.message(Command(commands=["check_mtlap"]))
async def cmd_check_mtlap(message: Message, app_context=None, skyuser: SkyUser | None = None):
    if not skyuser or not skyuser.is_skynet_admin():
        await message.reply("You are not my admin.")
        return

    if not app_context:
        raise ValueError("app_context required")
    ctx = cast(Any, app_context)
    key = ctx.stellar_service.find_public_key(message.text)

    if key is None and message.reply_to_message:
        key = ctx.stellar_service.find_public_key(message.reply_to_message.text)

    if key is None:
        await message.reply("Wrong format. Use: /check_mtlap public_key")
        return

    msg = await ctx.stellar_service.check_mtlap(key)
    await message.reply(msg)


def register_handlers(dp, bot):
    dp.include_router(router)
    logger.info("router stellar was loaded")
