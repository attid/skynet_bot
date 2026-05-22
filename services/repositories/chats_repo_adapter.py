class ChatsRepositoryAdapter:
    """AsyncSessionPool-backed adapter for chat repository access."""

    def __init__(self, async_session_pool):
        self._async_session_pool = async_session_pool

    async def get_all_chats(self):
        from db.repositories import ChatsRepository

        async with self._async_session_pool() as session:
            return await ChatsRepository(session).async_get_all_chats()

    async def add_user_to_chat(self, chat_id: int, member):
        from db.repositories import ChatsRepository

        async with self._async_session_pool() as session:
            result = await ChatsRepository(session).async_add_user_to_chat(chat_id, member)
            await session.commit()
            return result

    async def remove_user_from_chat(self, chat_id: int, user_id: int):
        from db.repositories import ChatsRepository

        async with self._async_session_pool() as session:
            result = await ChatsRepository(session).async_remove_user_from_chat(chat_id, user_id)
            await session.commit()
            return result

    async def get_user_id(self, username: str):
        from db.repositories import ChatsRepository

        async with self._async_session_pool() as session:
            return await ChatsRepository(session).async_get_user_id(username)

    async def get_user_by_id(self, user_id: int):
        from db.repositories import ChatsRepository

        async with self._async_session_pool() as session:
            return await ChatsRepository(session).async_get_user_by_id(user_id)

    async def save_user_type(self, user_id: int, user_type: int):
        from db.repositories import ChatsRepository

        async with self._async_session_pool() as session:
            await ChatsRepository(session).async_save_user_type(user_id, user_type)
            await session.commit()
            return True
