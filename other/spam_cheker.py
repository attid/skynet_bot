import asyncio
import re

import aiohttp
from loguru import logger

from other.config_reader import config

CAS_API_URL = "https://api.cas.chat/check"
CAS_TIMEOUT = aiohttp.ClientTimeout(total=10)
LOLS_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Security-relevant problems are reported once per kind so a broken upstream
# does not flood the log/Sentry on every new chat member.
_warned_once: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key in _warned_once:
        return
    _warned_once.add(key)
    logger.warning(message)


def _cas_api_key() -> str | None:
    key = config.cas_api_key
    if key is None:
        return None
    value = key.get_secret_value().strip()
    return value or None


def _cas_api_url() -> str:
    return (config.cas_api_url or CAS_API_URL).strip()


def is_mixed_word(word):
    # Проверяем наличие русских букв
    contains_cyrillic = bool(re.search("[а-яА-Я]", word))
    # Проверяем наличие цифр
    contains_digit = bool(re.search("[0-9@]", word))
    # Проверяем наличие латинских букв
    contains_latin = bool(re.search("[a-zA-Z]", word))

    # Считаем слово "смешанным", если оно содержит русские буквы и (цифры или латинские буквы)
    return contains_cyrillic and (contains_digit or contains_latin)


spam_phrases = [
    "команду",
    "команда",
    "доход",
    "без опыта",
    "лс",
    "личку",
    "прибыль",
    "проект",
    "предложение",
    "тестирование",
    "день",
    "заработка",
    "заработок",
    "процент",
    "пишите",
    "18",
    "связкизарабатывать",
    "подробности",
]

for i in range(1, 20):
    spam_phrases.append(f"{i}oo")
    spam_phrases.append(f"{i}оо")


def contains_spam_phrases(text, phrases=None, threshold=3):
    if phrases is None:
        phrases = spam_phrases

    words = re.findall(r"\b\w+\b", text.lower())

    count = sum(phrase in words for phrase in phrases)
    if "+" in text:
        count += 1
    # print(f'count: {count}')
    return count >= threshold


async def combo_check_spammer(user_id):
    """Return True when the user is banned in CAS (Combot Anti-Spam).

    CAS requires an API key (Combot API key) for every request; send it in the
    Authorization header so the secret never leaks into URLs or logs.
    A failed check is treated as "not banned" and never raises.
    """
    api_key = _cas_api_key()
    if api_key is None:
        _warn_once("cas_missing_key", "CAS check skipped: CAS_API_KEY is not configured")
        return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _cas_api_url(),
                params={"user_id": user_id},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=CAS_TIMEOUT,
            ) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    return bool(data.get("ok"))
                if response.status in (401, 403):
                    _warn_once(
                        "cas_unauthorized",
                        f"CAS check rejected the API key (status {response.status}): verify CAS_API_KEY",
                    )
                    return False
                _warn_once(f"cas_status_{response.status}", f"CAS check failed with status code: {response.status}")
                return False
    except asyncio.TimeoutError:
        _warn_once("cas_timeout", "CAS check timed out")
    except aiohttp.ClientError as e:
        _warn_once("cas_network", f"CAS check network error: {e}")
    except Exception as e:
        _warn_once(f"cas_error_{type(e).__name__}", f"Unexpected error in CAS check: {e}")
    return False


async def lols_check_spammer(user_id):
    try:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"https://api.lols.bot/account?id={user_id}", timeout=LOLS_TIMEOUT) as response:
                    if response.status == 200:
                        data = await response.json()
                        # {"ok":true,"user_id":8099459603,"banned":true}
                        if data.get("ok") and data.get("banned"):
                            return True
                    else:
                        logger.error(f"API request failed with status code: {response.status}")
            except aiohttp.ClientError as e:
                logger.error(f"Network error occurred: {str(e)}")
            except asyncio.TimeoutError:
                logger.error("Request timed out")
    except Exception as e:
        logger.error(f"Unexpected error in combo_check_spam: {str(e)}")
    return False


if __name__ == "__main__":
    test = """
Ищу людей, кто заинтересован в дополнительном доходе, онлайн формат, от 18 лет. За деталями обращайтесь в лс
"""

    # print(contains_spam_phrases(test))
    # print(asyncio.run(talk_check_spam(test)))
    print(asyncio.run(lols_check_spammer(5953807506)))
    print(asyncio.run(lols_check_spammer(84131737)))
