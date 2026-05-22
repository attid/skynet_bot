from enum import Enum
from collections.abc import Awaitable, Callable
from typing import Any, Dict, List, Optional, Union, cast

from db.session import AsyncSessionPool
from db.repositories import ConfigRepository, ChatsRepository, MessageRepository, ChatDTO, ChatUserDTO
from other.pyro_tools import GroupMember


class DatabaseService:
    def __init__(self):
        self.async_session_pool = AsyncSessionPool

    # --- ConfigRepository methods ---

    async def save_bot_value(self, chat_id: int, chat_key: Union[int, Enum], chat_value: Any):
        async with self.async_session_pool() as session:
            repo = ConfigRepository(session)
            await repo.async_save_bot_value(chat_id, chat_key, chat_value)
            await session.commit()

    async def load_bot_value(self, chat_id: int, chat_key: Union[int, Enum], default_value: Any = "") -> Any:
        async with self.async_session_pool() as session:
            repo = ConfigRepository(session)
            return await repo.async_load_bot_value(chat_id, chat_key, default_value)

    async def get_chat_ids_by_key(self, chat_key: Union[int, Enum]) -> List[int]:
        async with self.async_session_pool() as session:
            repo = ConfigRepository(session)
            return await repo.async_get_chat_ids_by_key(chat_key)

    async def get_chat_dict_by_key(self, chat_key: Union[int, Enum], return_json=False) -> Dict[int, Any]:
        async with self.async_session_pool() as session:
            repo = ConfigRepository(session)
            return await repo.async_get_chat_dict_by_key(chat_key, return_json)

    async def update_dict_value(self, chat_id: int, chat_key: Union[int, Enum], dict_key: str, dict_value: Any):
        async with self.async_session_pool() as session:
            repo = ConfigRepository(session)
            await repo.async_update_dict_value(chat_id, chat_key, dict_key, dict_value)
            await session.commit()

    async def get_dict_value(
        self, chat_id: int, chat_key: Union[int, Enum], dict_key: str, default_value: Any = None
    ) -> Any:
        async with self.async_session_pool() as session:
            repo = ConfigRepository(session)
            return await repo.async_get_dict_value(chat_id, chat_key, dict_key, default_value)

    async def save_kv_value(self, kv_key: str, kv_value: Any):
        async with self.async_session_pool() as session:
            repo = ConfigRepository(session)
            await repo.async_save_kv_value(kv_key, kv_value)
            await session.commit()

    async def load_kv_value(self, kv_key: str, default_value: Any = None) -> Any:
        async with self.async_session_pool() as session:
            repo = ConfigRepository(session)
            return await repo.async_load_kv_value(kv_key, default_value)

    # --- ChatsRepository methods ---

    async def update_chat_info(self, chat_id: int, members: List[GroupMember], clear_users=False):
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            await repo.async_update_chat_info(chat_id, members, clear_users)
            await session.commit()

    async def add_user_to_chat(self, chat_id: int, member: GroupMember):
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            await repo.async_add_user_to_chat(chat_id, member)
            await session.commit()

    async def remove_user_from_chat(self, chat_id: int, user_id: int):
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            result = await repo.async_remove_user_from_chat(chat_id, user_id)
            await session.commit()
            return result

    async def get_users_joined_last_day(self, chat_id: int) -> List[ChatUserDTO]:
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            return await repo.async_get_users_joined_last_day(chat_id)

    async def get_users_left_last_day(self, chat_id: int) -> List[ChatUserDTO]:
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            return await repo.async_get_users_left_last_day(chat_id)

    async def get_all_chats(self) -> List[ChatDTO]:
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            return await repo.async_get_all_chats()

    async def get_all_chats_by_user(self, user_id: int) -> List[ChatDTO]:
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            return await repo.async_get_all_chats_by_user(user_id)

    async def update_chat_with_dict(self, chat_id: int, update_data: Dict) -> bool:
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            result = await repo.async_update_chat_with_dict(chat_id, update_data)
            await session.commit()
            return result

    async def get_chat_by_id(self, chat_id: int) -> Optional[ChatDTO]:
        """Get chat from database by ID, returns ChatDTO or None."""
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            chat = await repo.async_get_chat_by_id(chat_id)
            if chat:
                admins_raw = cast(Any, chat.admins)
                return ChatDTO(
                    chat_id=cast(int, chat.chat_id),
                    username=cast(Optional[str], chat.username),
                    title=cast(Optional[str], chat.title),
                    created_at=cast(Any, chat.created_at),
                    last_updated=cast(Any, chat.last_updated),
                    admins=cast(List[int], admins_raw or []),
                )
            return None

    async def upsert_chat_info(self, chat_id: int, title: Optional[str], username: Optional[str]) -> None:
        """Create or update chat with title and username."""
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            await repo.async_upsert_chat_info(chat_id, title, username)
            await session.commit()

    async def save_bot_user(self, user_id: int, username: Optional[str], user_type: int = 0) -> None:
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            await repo.async_save_bot_user(user_id, username, user_type)
            await session.commit()

    async def get_user_id(self, username: str) -> int:
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            return await repo.async_get_user_id(username)

    async def update_user_chat_date(self, user_id: int, chat_id: int) -> None:
        async with self.async_session_pool() as session:
            repo = ChatsRepository(session)
            await repo.async_update_user_chat_date(user_id, chat_id)
            await session.commit()

    # --- MessageRepository methods ---

    async def save_message(
        self, user_id: int, username: str, chat_id: int, thread_id: int, text: str, summary_id: int | None = None
    ) -> None:
        async with self.async_session_pool() as session:
            repo = MessageRepository(session)
            await repo.async_save_message(
                user_id=user_id,
                username=username,
                chat_id=chat_id,
                thread_id=thread_id,
                text=text,
                summary_id=summary_id,
            )
            await session.commit()

    async def summarize_messages(
        self,
        chat_id: int,
        thread_id: int,
        summarize_text: Callable[[str], Awaitable[str]],
    ) -> list[str]:
        async with self.async_session_pool() as session:
            repo = MessageRepository(session)
            try:
                data = await repo.async_get_messages_without_summary(chat_id=chat_id, thread_id=thread_id)
                if not data:
                    return []

                text = ""
                summary = await repo.async_add_summary(text="")

                for record in data:
                    record_username = str(record.username or "")
                    record_text = str(record.text or "")
                    new_text = text + f"{record_username}: {record_text} \n\n"
                    if len(new_text) < 16000:
                        text = new_text
                        record.summary_id = summary.id
                        await session.flush()
                    else:
                        cast(Any, summary).text = await summarize_text(text)
                        await session.flush()
                        summary = await repo.async_add_summary(text="")
                        text = f"{record_username}: {record_text}\n\n"
                        record.summary_id = summary.id
                        await session.flush()

                if text:
                    cast(Any, summary).text = await summarize_text(text)
                    await session.flush()

                summaries = await repo.async_get_summary(chat_id=chat_id, thread_id=thread_id)
                await session.commit()
                return [str(record.text or "") for record in summaries if str(record.text or "")]
            except Exception:
                await session.rollback()
                raise
