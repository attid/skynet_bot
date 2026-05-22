# services/spam_status_service.py
"""Spam status service with dependency injection."""

from typing import Optional
from threading import Lock

from shared.domain.user import User, SpamStatus
from services.interfaces.repositories import IChatsRepository


class SpamStatusService:
    """
    Service for spam status management with thread-safe caching.

    Uses BotUsers.user_type as spam status:
    0 = new, 1 = good, 2 = bad.
    """

    def __init__(self, chats_repo: IChatsRepository | None = None):
        self._repo = chats_repo
        self._cache: dict[int, SpamStatus] = {}
        self._name_cache: dict[str, str] = {}
        self._lock = Lock()

    def get_status(self, user_id: int) -> SpamStatus:
        """Get spam status with caching (thread-safe)."""
        with self._lock:
            if user_id in self._cache:
                return self._cache[user_id]

        user_record = self._repo.get_user_by_id(user_id) if self._repo else None
        if user_record:
            status_value = getattr(user_record, "user_type", SpamStatus.NEW.value)
        else:
            status_value = SpamStatus.NEW.value

        try:
            status = SpamStatus(status_value)
        except ValueError:
            status = SpamStatus.NEW
        with self._lock:
            self._cache[user_id] = status

        return status

    def get_user(self, user_id: int, username: Optional[str] = None) -> User:
        """Get User domain object with spam status."""
        status = self.get_status(user_id)
        return User(user_id=user_id, username=username, spam_status=status)

    def set_status(self, user_id: int, status: SpamStatus) -> None:
        """Update spam status in cache and database."""
        with self._lock:
            self._cache[user_id] = status
        if self._repo:
            self._repo.save_user_type(user_id, status.value)

    def is_good(self, user_id: int) -> bool:
        """Check if user is good."""
        return self.get_status(user_id) == SpamStatus.GOOD

    def is_bad(self, user_id: int) -> bool:
        """Check if user is bad."""
        return self.get_status(user_id) == SpamStatus.BAD

    def is_new(self, user_id: int) -> bool:
        """Check if user is new."""
        return self.get_status(user_id) == SpamStatus.NEW

    def mark_good(self, user_id: int) -> None:
        """Mark user as good."""
        self.set_status(user_id, SpamStatus.GOOD)

    def mark_bad(self, user_id: int) -> None:
        """Mark user as bad."""
        self.set_status(user_id, SpamStatus.BAD)

    def mark_new(self, user_id: int) -> None:
        """Mark user as new."""
        self.set_status(user_id, SpamStatus.NEW)

    def clear_cache(self) -> None:
        """Clear spam status cache."""
        with self._lock:
            self._cache.clear()

    def invalidate_user(self, user_id: int) -> None:
        """Remove specific user from cache."""
        with self._lock:
            self._cache.pop(user_id, None)

    def preload_statuses(self, statuses: dict[int, int]) -> None:
        """Bulk load spam statuses into cache."""
        with self._lock:
            for user_id, status in statuses.items():
                try:
                    self._cache[user_id] = SpamStatus(status)
                except ValueError:
                    self._cache[user_id] = SpamStatus.NEW

    def get_cached_count(self) -> int:
        """Get number of cached users (for monitoring)."""
        with self._lock:
            return len(self._cache)

    # Name cache methods
    def cache_name(self, key: str, name: str) -> None:
        """Cache a name for user_id or address."""
        with self._lock:
            self._name_cache[key] = name

    def get_cached_name(self, key: str) -> Optional[str]:
        """Get cached name by user_id or address."""
        with self._lock:
            return self._name_cache.get(key)

    def load_name_cache(self, names: dict[str, str]) -> None:
        """Bulk load name cache."""
        with self._lock:
            self._name_cache = names.copy()

    def get_all_names(self) -> dict[str, str]:
        """Get all cached names."""
        with self._lock:
            return self._name_cache.copy()
