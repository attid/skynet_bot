# services/config_service.py
"""Configuration service with dependency injection."""

from enum import Enum
from typing import Any, Optional, Union
from threading import Lock

from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories import ConfigRepository
from other.constants import BotValueTypes
from services.interfaces.repositories import IConfigRepository
from shared.domain.config import BotConfig

# Build reverse mapping: snake_case string -> BotValueTypes enum
# e.g. "entry_channel" -> BotValueTypes.EntryChannel
_STR_TO_ENUM: dict[str, BotValueTypes] = {}
for _member in BotValueTypes:
    # Convert CamelCase to snake_case
    _name = _member.name
    _snake = "".join(f"_{c.lower()}" if c.isupper() else c for c in _name).lstrip("_")
    _STR_TO_ENUM[_snake] = _member


def _resolve_key(key: Union[str, Enum, int]) -> Union[Enum, int, str]:
    """Convert string key to BotValueTypes enum if possible."""
    if isinstance(key, str):
        return _STR_TO_ENUM.get(key, key)
    return key


def _cache_key(key: Union[str, Enum, int]) -> str:
    """Normalize key to cache-compatible string."""
    if isinstance(key, Enum):
        return key.name
    return str(key)


class ConfigService:
    """
    Service for bot configuration management.

    Replaces direct global_data.db_service access.
    """

    def __init__(self, config_repo: Optional[IConfigRepository] = None):
        self._repo = config_repo
        self._cache: dict[int, BotConfig] = {}
        self._lock = Lock()

        # In-memory caches for per-chat configurations
        self._welcome_messages: dict[int, Any] = {}
        self._welcome_buttons: dict[int, Any] = {}
        self._delete_income: dict[int, Any] = {}
        self._entry_channels: dict[int, Any] = {}

    def get_config(self, chat_id: int) -> BotConfig:
        """
        Get configuration for chat (cached).

        Returns BotConfig domain object with all settings.
        """
        with self._lock:
            if chat_id in self._cache:
                return self._cache[chat_id]

        # Load all settings for chat
        settings = {}
        if self._repo:
            for key in self._get_common_keys():
                value = self._repo.load_bot_value(chat_id, _resolve_key(key))
                if value is not None:
                    settings[key] = value

        config = BotConfig(chat_id=chat_id, settings=settings)

        with self._lock:
            self._cache[chat_id] = config

        return config

    def save_value(self, chat_id: int, key: Union[str, Enum, int], value: Any) -> bool:
        """Save configuration value."""
        if not self._repo:
            return False
        result = self._repo.save_bot_value(chat_id, _resolve_key(key), value)

        # Update cache
        with self._lock:
            if chat_id in self._cache:
                self._cache[chat_id].set(_cache_key(key), value)

        return result

    def load_value(self, chat_id: int, key: Union[str, Enum, int], default: Any = None) -> Any:
        """Load configuration value."""
        if not self._repo:
            return default
        return self._repo.load_bot_value(chat_id, _resolve_key(key), default)

    def remove_value(self, chat_id: int, key: str) -> bool:
        """Remove configuration value."""
        if not self._repo:
            return False
        # Save None to effectively remove
        result = self._repo.save_bot_value(chat_id, _resolve_key(key), None)

        # Update cache
        with self._lock:
            if chat_id in self._cache:
                self._cache[chat_id].remove(key)

        return result

    def get_chats_with_feature(self, feature_key: Union[str, Enum, int]) -> list[int]:
        """Get all chat IDs with specific feature enabled."""
        if not self._repo:
            return []
        chat_ids = self._repo.get_chat_ids_by_key(_resolve_key(feature_key))
        # Filter to only those with truthy values
        return [cid for cid in chat_ids if self.load_value(cid, feature_key)]

    def invalidate_cache(self, chat_id: Optional[int] = None) -> None:
        """Invalidate cache for specific chat or all."""
        with self._lock:
            if chat_id is not None:
                self._cache.pop(chat_id, None)
            else:
                self._cache.clear()

    def is_feature_enabled(self, chat_id: int, feature: str) -> bool:
        """Check if feature is enabled for chat."""
        config = self.get_config(chat_id)
        return bool(config.get(feature, False))

    def get_cached_count(self) -> int:
        """Get number of cached configs (for monitoring)."""
        with self._lock:
            return len(self._cache)

    # Welcome messages methods
    def get_welcome_message(self, chat_id: int) -> Optional[str]:
        """Get welcome message template for chat."""
        with self._lock:
            return self._welcome_messages.get(chat_id)

    def set_welcome_message(self, chat_id: int, message: str) -> None:
        """Set welcome message for chat cache."""
        with self._lock:
            self._welcome_messages[chat_id] = message

    async def async_set_welcome_message(self, chat_id: int, message: str, session: AsyncSession | None = None) -> None:
        """Set welcome message for chat. Saves to DB if async session provided."""
        with self._lock:
            self._welcome_messages[chat_id] = message

        if session is not None:
            await ConfigRepository(session).async_save_bot_value(chat_id, BotValueTypes.WelcomeMessage, message)

    def remove_welcome_message(self, chat_id: int) -> None:
        """Remove welcome message from chat cache."""
        with self._lock:
            self._welcome_messages.pop(chat_id, None)

    async def async_remove_welcome_message(self, chat_id: int, session: AsyncSession | None = None) -> None:
        """Remove welcome message for chat. Removes from DB if async session provided."""
        with self._lock:
            self._welcome_messages.pop(chat_id, None)

        if session is not None:
            await ConfigRepository(session).async_save_bot_value(chat_id, BotValueTypes.WelcomeMessage, None)

    def load_welcome_messages(self, data: dict[int, Any]) -> None:
        """Bulk load welcome messages from global_data."""
        with self._lock:
            self._welcome_messages.update(data)

    # Welcome button methods
    def get_welcome_button(self, chat_id: int) -> Optional[Any]:
        """Get welcome button config for chat."""
        with self._lock:
            return self._welcome_buttons.get(chat_id)

    def set_welcome_button(self, chat_id: int, button: Any) -> None:
        """Set welcome button config for chat cache."""
        with self._lock:
            self._welcome_buttons[chat_id] = button

    async def async_set_welcome_button(self, chat_id: int, button: Any, session: AsyncSession | None = None) -> None:
        """Set welcome button config for chat. Saves to DB if async session provided."""
        with self._lock:
            self._welcome_buttons[chat_id] = button

        if session is not None:
            await ConfigRepository(session).async_save_bot_value(chat_id, BotValueTypes.WelcomeButton, button)

    def remove_welcome_button(self, chat_id: int) -> None:
        """Remove welcome button config from chat cache."""
        with self._lock:
            self._welcome_buttons.pop(chat_id, None)

    async def async_remove_welcome_button(self, chat_id: int, session: AsyncSession | None = None) -> None:
        """Remove welcome button config for chat. Removes from DB if async session provided."""
        with self._lock:
            self._welcome_buttons.pop(chat_id, None)

        if session is not None:
            await ConfigRepository(session).async_save_bot_value(chat_id, BotValueTypes.WelcomeButton, None)

    def load_welcome_buttons(self, data: dict[int, Any]) -> None:
        """Bulk load welcome buttons from global_data."""
        with self._lock:
            self._welcome_buttons.update(data)

    # Delete income methods
    def get_delete_income(self, chat_id: int) -> Optional[Any]:
        """Get delete income config for chat."""
        with self._lock:
            return self._delete_income.get(chat_id)

    def set_delete_income(self, chat_id: int, config: Any) -> None:
        """Set delete income config for chat cache."""
        with self._lock:
            self._delete_income[chat_id] = config

    async def async_set_delete_income(self, chat_id: int, config: Any, session: AsyncSession | None = None) -> None:
        """Set delete income config for chat. Saves to DB if async session provided."""
        with self._lock:
            self._delete_income[chat_id] = config

        if session is not None:
            await ConfigRepository(session).async_save_bot_value(chat_id, BotValueTypes.DeleteIncome, config)

    def remove_delete_income(self, chat_id: int) -> None:
        """Remove delete income config from chat cache."""
        with self._lock:
            self._delete_income.pop(chat_id, None)

    async def async_remove_delete_income(self, chat_id: int, session: AsyncSession | None = None) -> None:
        """Remove delete income config for chat. Removes from DB if async session provided."""
        with self._lock:
            self._delete_income.pop(chat_id, None)

        if session is not None:
            await ConfigRepository(session).async_save_bot_value(chat_id, BotValueTypes.DeleteIncome, None)

    def load_delete_income(self, data: dict[int, Any]) -> None:
        """Bulk load delete income configs from global_data."""
        with self._lock:
            self._delete_income.update(data)

    # Entry channel methods
    def get_entry_channel(self, chat_id: int) -> Optional[Any]:
        """Get required entry channel for chat."""
        with self._lock:
            return self._entry_channels.get(chat_id)

    def set_entry_channel(self, chat_id: int, channel: Any) -> None:
        """Set required entry channel for chat cache."""
        with self._lock:
            self._entry_channels[chat_id] = channel

    def remove_entry_channel(self, chat_id: int) -> None:
        """Remove required entry channel from chat cache."""
        with self._lock:
            self._entry_channels.pop(chat_id, None)

    def load_entry_channels(self, data: dict[int, Any]) -> None:
        """Bulk load required entry channels."""
        with self._lock:
            self._entry_channels.update(data)

    def _get_common_keys(self) -> list[str]:
        """Get list of common config keys to preload."""
        return [
            "captcha",
            "moderate",
            "welcome_message",
            "entry_channel",
            "no_first_link",
            "reply_only",
            "listen",
            "auto_all",
            "save_last_message_date",
            "join_request_captcha",
            "full_data",
        ]
