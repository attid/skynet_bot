import os
from dataclasses import dataclass

import aiohttp
from aiogram.types import User
from loguru import logger

from other.config_reader import config

EURMTL_BOT_CONFIRM_URL = "https://eurmtl.me/login/bot/confirm"


@dataclass(frozen=True)
class BotLoginConfirmResult:
    success: bool
    status: int | None = None


def _confirm_url() -> str:
    return os.getenv("EURMTL_BOT_CONFIRM_URL", EURMTL_BOT_CONFIRM_URL)


def build_bot_login_payload(token: str, user: User, auth_date: int) -> dict[str, object]:
    return {
        "token": token,
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name or "",
        "username": user.username,
        "photo_url": None,
        "auth_date": auth_date,
    }


async def confirm_eurmtl_bot_login(token: str, user: User, auth_date: int) -> BotLoginConfirmResult:
    payload = build_bot_login_payload(token, user, auth_date)
    headers = {
        "Authorization": f"Bearer {config.eurmtl_key}",
        "Content-Type": "application/json",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(_confirm_url(), json=payload, headers=headers) as response:
                if 200 <= response.status < 300:
                    return BotLoginConfirmResult(success=True, status=response.status)
                logger.warning("EURMTL bot login confirm rejected with status {}", response.status)
                return BotLoginConfirmResult(success=False, status=response.status)
    except (aiohttp.ClientError, TimeoutError) as exc:
        logger.warning("EURMTL bot login confirm failed: {}", exc)
        return BotLoginConfirmResult(success=False)
