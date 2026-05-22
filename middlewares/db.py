from typing import Callable, Awaitable, Dict, Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class LazySyncSession:
    def __init__(self, session_pool):
        self._session_pool = session_pool
        self._session_context = None
        self._session = None

    @property
    def opened(self) -> bool:
        return self._session is not None

    def _open(self):
        if self._session is None:
            self._session_context = self._session_pool()
            self._session = self._session_context.__enter__()
        return self._session

    def commit(self) -> None:
        if self._session is not None:
            self._session.commit()

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()

    def close(self) -> None:
        if self._session_context is not None:
            self._session_context.__exit__(None, None, None)
            self._session_context = None
            self._session = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._open(), name)


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_pool, lazy: bool = False):
        super().__init__()
        self.session_pool = session_pool
        self.lazy = lazy

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if self.lazy:
            return await self._handle_lazy_sync_session(handler, event, data)

        session_context = self.session_pool()
        if hasattr(session_context, "__aenter__"):
            async with session_context as session:
                return await self._handle_async_session(handler, event, data, session)

        with session_context as session:
            return await self._handle_sync_session(handler, event, data, session)

    async def _handle_lazy_sync_session(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        session = LazySyncSession(self.session_pool)
        data["session"] = session
        try:
            result = await handler(event, data)
        except Exception:
            session.rollback()
            session.close()
            raise
        if session.opened:
            session.commit()
            session.close()
        return result

    async def _handle_async_session(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
        session: Any,
    ) -> Any:
        data["session"] = session
        try:
            result = await handler(event, data)
        except Exception:
            await session.rollback()
            raise
        await session.commit()
        return result

    async def _handle_sync_session(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
        session: Any,
    ) -> Any:
        data["session"] = session
        try:
            result = await handler(event, data)
        except Exception:
            session.rollback()
            raise
        session.commit()
        return result
