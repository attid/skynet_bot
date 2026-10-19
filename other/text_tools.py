import re
from loguru import logger

DEFAULT_URL_HOST = "eurmtl.me"

# Trailing characters that are almost never part of an URL copied from a chat
# message: "(см. https://eurmtl.me/...)", "https://eurmtl.me/...)." and so on.
_URL_TRAILING_CHARS = ").,;:!?»«\"'…]}>"


def extract_url(msg: str | None, surl: str = DEFAULT_URL_HOST, allow_scheme_less: bool = False) -> str | None:
    """Extract the first http(s) URL of ``surl`` host from a text.

    Args:
        msg: Text to search in (message text, caption, ...).
        surl: Host to look for, e.g. ``eurmtl.me``. ``None`` matches any host.
        allow_scheme_less: Also match ``eurmtl.me/sign_tools/...`` without
            ``https://`` prefix and normalize it to a full URL.

    Returns:
        The URL without trailing punctuation, or ``None`` when nothing found.
    """
    if not msg:
        return None
    try:
        if surl:
            host = rf"(?:[A-Za-z0-9-]+\.)*{re.escape(surl)}"
        else:
            host = r"[A-Za-z0-9.-]+"
        scheme = r"(?:https?://)?" if allow_scheme_less else r"https?://"
        search_result = re.search(rf"{scheme}{host}[^\s]*", msg, re.IGNORECASE)
        if not search_result:
            return None
        url = search_result.group(0).rstrip(_URL_TRAILING_CHARS)
        if allow_scheme_less and not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        return url or None
    except Exception:
        logger.exception("Error extracting URL from text")
        return None
