# services/feature_flags.py
"""Feature flags service replacing global_data feature lists."""

from typing import Optional
from dataclasses import dataclass
from threading import Lock

from other.constants import BotValueTypes
from services.config_service import ConfigService


@dataclass
class ChatFeatures:
    """Feature flags for a specific chat."""

    chat_id: int
    captcha: bool = False
    moderate: bool = False
    no_first_link: bool = False
    reply_only: bool = False
    listen: bool = False
    auto_all: bool = False
    save_last_message_date: bool = False
    join_request_captcha: bool = False
    full_data: bool = False
    first_vote: bool = False
    need_decode: bool = False
    delete_income: bool = False
    entry_channel: bool = False
    notify_join: bool = False
    notify_message: bool = False
    selfmod: bool = False


# Mapping from feature name to BotValueTypes enum
FEATURE_TO_ENUM = {
    "captcha": BotValueTypes.Captcha,
    "moderate": BotValueTypes.Moderate,
    "no_first_link": BotValueTypes.NoFirstLink,
    "reply_only": BotValueTypes.ReplyOnly,
    "listen": BotValueTypes.Listen,
    "auto_all": BotValueTypes.AutoAll,
    "save_last_message_date": BotValueTypes.SaveLastMessageDate,
    "join_request_captcha": BotValueTypes.JoinRequestCaptcha,
    "full_data": BotValueTypes.FullData,
    "first_vote": BotValueTypes.FirstVote,
    "need_decode": BotValueTypes.NeedDecode,
    "delete_income": BotValueTypes.DeleteIncome,
    "entry_channel": BotValueTypes.EntryChannel,
    "notify_join": BotValueTypes.NotifyJoin,
    "notify_message": BotValueTypes.NotifyMessage,
    "selfmod": BotValueTypes.Selfmod,
}


class FeatureFlagsService:
    """
    Service for chat feature flags.

    Replaces global_data lists like captcha, moderate, no_first_link, etc.
    Provides a clean interface for checking and toggling features.
    """

    FEATURE_KEYS = list(FEATURE_TO_ENUM.keys())

    def __init__(self, config_service: ConfigService):
        self._config = config_service
        self._cache: dict[int, ChatFeatures] = {}
        self._lock = Lock()

    def get_features(self, chat_id: int) -> ChatFeatures:
        """Get all feature flags for chat."""
        with self._lock:
            if chat_id in self._cache:
                return self._cache[chat_id]

        features = ChatFeatures(chat_id=chat_id)

        for key in self.FEATURE_KEYS:
            enum_key = FEATURE_TO_ENUM[key]
            value = self._config.load_value(chat_id, enum_key, False)
            setattr(features, key, bool(value))

        with self._lock:
            self._cache[chat_id] = features

        return features

    def is_enabled(self, chat_id: int, feature: str) -> bool:
        """Check if specific feature is enabled for chat."""
        if feature not in self.FEATURE_KEYS:
            return False
        features = self.get_features(chat_id)
        return getattr(features, feature, False)

    def enable(self, chat_id: int, feature: str) -> bool:
        """Enable feature for chat."""
        return self.set_feature(chat_id, feature, True)

    def disable(self, chat_id: int, feature: str) -> bool:
        """Disable feature for chat."""
        return self.set_feature(chat_id, feature, False)

    def set_feature(self, chat_id: int, feature: str, enabled: bool, persist: bool = True) -> bool:
        """Enable or disable feature for chat."""
        if feature not in FEATURE_TO_ENUM:
            return False

        if persist:
            enum_key = FEATURE_TO_ENUM[feature]
            self._config.save_value(chat_id, enum_key, enabled)

        # Update cache (create entry if not exists)
        with self._lock:
            if chat_id not in self._cache:
                self._cache[chat_id] = ChatFeatures(chat_id=chat_id)
            setattr(self._cache[chat_id], feature, enabled)

        return True

    def toggle(self, chat_id: int, feature: str) -> bool:
        """Toggle feature state. Returns new state."""
        current = self.is_enabled(chat_id, feature)
        self.set_feature(chat_id, feature, not current)
        return not current

    def get_chats_with_feature(self, feature: str) -> list[int]:
        """Get all chat IDs with feature enabled from cache."""
        if feature not in FEATURE_TO_ENUM:
            return []
        with self._lock:
            return [chat_id for chat_id, features in self._cache.items() if getattr(features, feature, False)]

    def get_feature_list(self, feature: str) -> list[int]:
        """Get list of chat IDs with feature enabled.

        Alias for get_chats_with_feature for backward compatibility with inline.py.
        """
        return self.get_chats_with_feature(feature)

    def invalidate_cache(self, chat_id: Optional[int] = None) -> None:
        """Invalidate cache."""
        with self._lock:
            if chat_id is not None:
                self._cache.pop(chat_id, None)
            else:
                self._cache.clear()

    # Convenience methods for common features
    def is_captcha_enabled(self, chat_id: int) -> bool:
        """Check if captcha is enabled."""
        return self.is_enabled(chat_id, "captcha")

    def is_moderation_enabled(self, chat_id: int) -> bool:
        """Check if moderation is enabled."""
        return self.is_enabled(chat_id, "moderate")

    def is_no_first_link(self, chat_id: int) -> bool:
        """Check if first link restriction is enabled."""
        return self.is_enabled(chat_id, "no_first_link")

    def is_reply_only(self, chat_id: int) -> bool:
        """Check if reply-only mode is enabled."""
        return self.is_enabled(chat_id, "reply_only")

    def is_listening(self, chat_id: int) -> bool:
        """Check if bot is listening in chat."""
        return self.is_enabled(chat_id, "listen")

    def is_full_data(self, chat_id: int) -> bool:
        """Check if full data mode is enabled."""
        return self.is_enabled(chat_id, "full_data")

    def get_cached_count(self) -> int:
        """Get number of cached feature sets (for monitoring)."""
        with self._lock:
            return len(self._cache)
