"""In-memory duplicate burst detector for first-message spam bypass.

Spammers send several identical (1:1) messages right after joining to bypass
antispam bots that only inspect the first message. This service tracks recent
messages of NEW users per (chat_id, user_id) and reports a burst when the same
normalized text repeats within the configured window. The router is responsible
for passing only NEW users here and for acting on BurstHit (delete copies,
restrict, log to the spam group).
"""

import time
from dataclasses import dataclass


@dataclass
class BurstRecord:
    """A tracked message of a NEW user and (optionally) its first-vote panel."""

    message_id: int
    normalized_text: str
    created_at: float
    panel_message_id: int | None = None


@dataclass
class BurstHit:
    """Duplicate burst detected by BurstSpamService.register."""

    chat_id: int
    user_id: int
    records: list[BurstRecord]
    copies: int


class BurstSpamService:
    """Tracks recent messages of NEW users and detects identical-text bursts."""

    def __init__(self, window_seconds: int = 600, min_text_length: int = 20, max_records_per_user: int = 10):
        self._window = window_seconds
        self._min_text_length = min_text_length
        self._max_records = max_records_per_user
        self._records: dict[tuple[int, int], list[BurstRecord]] = {}

    @staticmethod
    def normalize_text(text: str) -> str:
        """Casefold and collapse whitespace so 1:1 copies compare equal."""
        return " ".join(text.casefold().split())

    def _prune(self, key: tuple[int, int], now: float) -> None:
        records = self._records.get(key)
        if not records:
            self._records.pop(key, None)
            return
        fresh = [record for record in records if now - record.created_at <= self._window]
        if fresh:
            self._records[key] = fresh
        else:
            self._records.pop(key, None)

    def register(
        self, chat_id: int, user_id: int, message_id: int, text: str, now: float | None = None
    ) -> BurstHit | None:
        """Track a NEW user's message.

        Returns BurstHit when the same normalized text was already registered
        for this (chat, user) within the window; the hit carries the previous
        copies (with their vote panels) to delete. Short texts are ignored so
        common replies cannot trigger a false positive.
        """
        normalized = self.normalize_text(text or "")
        if len(normalized) < self._min_text_length:
            return None
        current_time = time.time() if now is None else now
        key = (chat_id, user_id)
        self._prune(key, current_time)
        records = self._records.setdefault(key, [])
        current = BurstRecord(message_id=message_id, normalized_text=normalized, created_at=current_time)
        matched = [record for record in records if record.normalized_text == normalized]
        if matched:
            # Keep tracking the triggering message so any further copy bursts on its own.
            self._records[key] = [current]
            return BurstHit(chat_id=chat_id, user_id=user_id, records=matched, copies=len(matched) + 1)
        records.append(current)
        if len(records) > self._max_records:
            del records[: len(records) - self._max_records]
        return None

    def register_panel(self, chat_id: int, user_id: int, message_id: int, panel_message_id: int) -> None:
        """Attach a first-vote panel message to a tracked message so a burst can delete it."""
        for record in self._records.get((chat_id, user_id), []):
            if record.message_id == message_id:
                record.panel_message_id = panel_message_id
                return
