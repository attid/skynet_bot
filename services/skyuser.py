from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from other.constants import MTLChats
from services.app_context import AppContext


@dataclass
class SkyUser:
    """Resolved actor for an update.

    Provides lazy admin checks based on cached admins and API fallback.
    """

    user_id: int | None
    username: str | None
    chat_id: int | None
    sender_chat_id: int | None
    bot: Bot | None
    app_context: AppContext | None

    def is_skynet_admin(self) -> bool:
        if not self.app_context or not self.app_context.admin_service:
            raise ValueError("app_context with admin_service required")
        return self.app_context.admin_service.is_skynet_admin(self.username or "")

    def has_topic_admins(self, chat_id: int, thread_id: int) -> bool:
        if not self.app_context or not self.app_context.admin_service:
            raise ValueError("app_context with admin_service required")
        return self.app_context.admin_service.has_topic_admins(chat_id, thread_id)

    def is_topic_admin(self, chat_id: int, thread_id: int) -> bool:
        if not self.app_context or not self.app_context.admin_service:
            raise ValueError("app_context with admin_service required")
        return self.app_context.admin_service.is_topic_admin(chat_id, thread_id, self.username or "")

    def is_channel_unlinked(self) -> bool:
        return self.sender_chat_id is not None and self.user_id is None

    def admin_denied_text(self, default: str = "You are not admin.") -> str:
        if self.is_channel_unlinked():
            return "Вы пишете от имени канала. Используйте /link_channel или переключитесь на пользователя."
        return default

    async def is_admin(self, chat_id: int | None = None, permission: Any = None) -> bool:
        """Check if user is admin in chat.

        If permission is provided, always uses API to verify permission.
        """
        target_chat_id = chat_id or self.chat_id
        if not target_chat_id or not self.user_id:
            logger.debug(
                "skyuser.is_admin: missing target or user_id (user_id={}, chat_id={}, sender_chat_id={}, username={})",
                self.user_id,
                target_chat_id,
                self.sender_chat_id,
                self.username,
            )
            return False

        if self.user_id == MTLChats.GroupAnonymousBot:
            if permission is not None:
                logger.debug(
                    "skyuser.is_admin: anonymous admin has no permission info (user_id={}, chat_id={}, permission={})",
                    self.user_id,
                    target_chat_id,
                    getattr(permission, "value", permission),
                )
                return False
            logger.debug(
                "skyuser.is_admin: anonymous admin treated as admin (user_id={}, chat_id={})",
                self.user_id,
                target_chat_id,
            )
            return True

        if self.user_id == target_chat_id:
            logger.debug(
                "skyuser.is_admin: user_id equals chat_id (user_id={}, chat_id={})",
                self.user_id,
                target_chat_id,
            )
            return True

        admin_service = self.app_context.admin_service if self.app_context else None
        has_cache = False
        if admin_service and permission is None:
            admin_service_any = cast(Any, admin_service)
            with admin_service_any._lock:
                has_cache = target_chat_id in admin_service_any._admins

        if has_cache and admin_service:
            result = admin_service.is_chat_admin(target_chat_id, self.user_id)
            logger.debug(
                "skyuser.is_admin: cache result={} (user_id={}, chat_id={}, sender_chat_id={}, username={})",
                result,
                self.user_id,
                target_chat_id,
                self.sender_chat_id,
                self.username,
            )
            return result

        if not self.bot:
            logger.debug(
                "skyuser.is_admin: no bot available for API check (user_id={}, chat_id={})",
                self.user_id,
                target_chat_id,
            )
            return False

        try:
            members = await self.bot.get_chat_administrators(chat_id=target_chat_id)
        except TelegramBadRequest as exc:
            logger.warning(f"is_admin: cannot get admins for chat {target_chat_id}: {exc}")
            return False

        if admin_service:
            admin_ids = [member.user.id for member in members]
            admin_service.set_chat_admins(target_chat_id, admin_ids)

        if permission is None:
            result = any(member.user.id == self.user_id for member in members)
            logger.debug(
                "skyuser.is_admin: api result={} (user_id={}, chat_id={}, sender_chat_id={}, username={})",
                result,
                self.user_id,
                target_chat_id,
                self.sender_chat_id,
                self.username,
            )
            return result

        perm_attr = getattr(permission, "value", permission)
        for member in members:
            if member.user.id == self.user_id:
                result = getattr(member, perm_attr, False)
                logger.debug(
                    "skyuser.is_admin: api permission result={} (user_id={}, chat_id={}, sender_chat_id={}, username={}, permission={})",
                    result,
                    self.user_id,
                    target_chat_id,
                    self.sender_chat_id,
                    self.username,
                    perm_attr,
                )
                return result

        logger.debug(
            "skyuser.is_admin: api result=False (user_id={}, chat_id={}, sender_chat_id={}, username={}, permission={})",
            self.user_id,
            target_chat_id,
            self.sender_chat_id,
            self.username,
            getattr(permission, "value", permission) if permission is not None else None,
        )
        return False
