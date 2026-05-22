from datetime import datetime, timedelta, UTC
from typing import List, Optional, Dict

from pydantic import BaseModel, Field
from sqlalchemy import select, delete, and_

from db.repositories.base import BaseRepository
from other.pyro_tools import GroupMember
from shared.infrastructure.database.models import Chat, ChatMember, BotUsers, BotUserChats


# DTOs replacing MongoUser and MongoChat
class ChatUserDTO(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str]
    full_name: str
    is_admin: bool = False
    created_at: datetime
    left_at: Optional[datetime] = None


class ChatDTO(BaseModel):
    chat_id: int
    username: Optional[str] = None
    title: Optional[str] = None
    created_at: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    users: Dict[str, ChatUserDTO] = Field(default_factory=dict)
    admins: List[int] = Field(default_factory=list)


class ChatsRepository(BaseRepository):
    def update_chat_info(self, chat_id: int, members: List[GroupMember], clear_users: bool = False) -> bool:
        now = datetime.now(UTC)

        # Получаем текущую информацию о чате
        result = self.session.execute(select(Chat).where(Chat.chat_id == chat_id))
        chat = result.scalar_one_or_none()

        if not chat:
            chat = Chat(chat_id=chat_id, created_at=now, last_updated=now, admins=[], metadata_={})
            self.session.add(chat)
            self.session.flush()

        if clear_users:
            self.session.execute(delete(ChatMember).where(ChatMember.chat_id == chat_id))
            chat.admins = []

        chat.last_updated = now

        # Ensure chat.admins is a list
        if chat.admins is None:
            chat.admins = []

        admin_ids = set(chat.admins)

        for member in members:
            # Check user existence in BotUsers
            user_result = self.session.execute(select(BotUsers).where(BotUsers.user_id == member.user_id))
            user_record = user_result.scalar_one_or_none()

            if not user_record:
                new_user = BotUsers(user_id=member.user_id, user_name=member.username, user_type=0)
                self.session.add(new_user)
                # No need to flush every time, but maybe safer for FKs if we weren't using bulk approach.
                # Here we are adding one by one.

            # Check member existence
            existing_member = self.session.execute(
                select(ChatMember).where(and_(ChatMember.chat_id == chat_id, ChatMember.user_id == member.user_id))
            ).scalar_one_or_none()

            member_metadata = {"username": member.username, "full_name": member.full_name, "is_admin": member.is_admin}

            if existing_member:
                existing_member.metadata_ = member_metadata
                if existing_member.left_at:
                    existing_member.left_at = None
            else:
                new_member = ChatMember(
                    chat_id=chat_id, user_id=member.user_id, created_at=now, metadata_=member_metadata
                )
                self.session.add(new_member)

            if member.is_admin:
                admin_ids.add(member.user_id)
            else:
                admin_ids.discard(member.user_id)

        chat.admins = list(admin_ids)
        # Flush or commit is handled by caller or context manager, but mongo.py did commit.
        # We will let the service/caller handle commit if possible, or do it here if we strictly follow mongo.py behavior.
        # mongo.py methods committed. To match behavior, I should probably not commit if I want a clean repo pattern,
        # but since I am replacing logic that expects side effects, I might need to be careful.
        # Ideally Repositories don't commit. Unit of Work does.
        # But for now, let's assume the calling code (Session context) will commit.
        return True

    def add_user_to_chat(self, chat_id: int, member: GroupMember) -> bool:
        now = datetime.now(UTC)

        result = self.session.execute(select(Chat).where(Chat.chat_id == chat_id))
        chat = result.scalar_one_or_none()

        if not chat:
            chat = Chat(chat_id=chat_id, created_at=now, last_updated=now, admins=[], metadata_={})
            self.session.add(chat)
            self.session.flush()

        chat.last_updated = now

        user_result = self.session.execute(select(BotUsers).where(BotUsers.user_id == member.user_id))
        user_record = user_result.scalar_one_or_none()

        if not user_record:
            new_user = BotUsers(user_id=member.user_id, user_name=member.username, user_type=0)
            self.session.add(new_user)

        existing_member = self.session.execute(
            select(ChatMember).where(and_(ChatMember.chat_id == chat_id, ChatMember.user_id == member.user_id))
        ).scalar_one_or_none()

        member_metadata = {"username": member.username, "full_name": member.full_name, "is_admin": member.is_admin}

        if existing_member:
            existing_member.metadata_ = member_metadata
            if existing_member.left_at:
                existing_member.left_at = None
        else:
            new_member = ChatMember(chat_id=chat_id, user_id=member.user_id, created_at=now, metadata_=member_metadata)
            self.session.add(new_member)

        if member.is_admin:
            if chat.admins is None:
                chat.admins = []
            if member.user_id not in chat.admins:
                # We need to re-assign for mutation tracking if it's not a MutableList
                admins = list(chat.admins)
                admins.append(member.user_id)
                chat.admins = admins

        return True

    async def async_add_user_to_chat(self, chat_id: int, member: GroupMember) -> bool:
        now = datetime.now(UTC)

        result = await self.session.execute(select(Chat).where(Chat.chat_id == chat_id))
        chat = result.scalar_one_or_none()

        if not chat:
            chat = Chat(chat_id=chat_id, created_at=now, last_updated=now, admins=[], metadata_={})
            self.session.add(chat)
            await self.session.flush()

        chat.last_updated = now

        user_result = await self.session.execute(select(BotUsers).where(BotUsers.user_id == member.user_id))
        user_record = user_result.scalar_one_or_none()

        if not user_record:
            new_user = BotUsers(user_id=member.user_id, user_name=member.username, user_type=0)
            self.session.add(new_user)

        existing_member = (
            await self.session.execute(
                select(ChatMember).where(and_(ChatMember.chat_id == chat_id, ChatMember.user_id == member.user_id))
            )
        ).scalar_one_or_none()

        member_metadata = {"username": member.username, "full_name": member.full_name, "is_admin": member.is_admin}

        if existing_member:
            existing_member.metadata_ = member_metadata
            if existing_member.left_at:
                existing_member.left_at = None
        else:
            new_member = ChatMember(chat_id=chat_id, user_id=member.user_id, created_at=now, metadata_=member_metadata)
            self.session.add(new_member)

        if member.is_admin:
            if chat.admins is None:
                chat.admins = []
            if member.user_id not in chat.admins:
                admins = list(chat.admins)
                admins.append(member.user_id)
                chat.admins = admins

        return True

    def remove_user_from_chat(self, chat_id: int, user_id: int) -> bool:
        result = self.session.execute(select(Chat).where(Chat.chat_id == chat_id))
        chat = result.scalar_one_or_none()
        if not chat:
            return False

        now = datetime.now(UTC)

        result = self.session.execute(
            select(ChatMember).where(and_(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id))
        )
        member_record = result.scalar_one_or_none()

        if member_record and not member_record.left_at:
            member_record.left_at = now
            if member_record.metadata_:
                # Make copy to update JSON
                new_meta = dict(member_record.metadata_)
                new_meta["left_at"] = now.isoformat()
                member_record.metadata_ = new_meta

        if chat.admins and user_id in chat.admins:
            admins = list(chat.admins)
            if user_id in admins:
                admins.remove(user_id)
                chat.admins = admins

        chat.last_updated = now
        return member_record is not None

    async def async_remove_user_from_chat(self, chat_id: int, user_id: int) -> bool:
        result = await self.session.execute(select(Chat).where(Chat.chat_id == chat_id))
        chat = result.scalar_one_or_none()
        if not chat:
            return False

        now = datetime.now(UTC)

        result = await self.session.execute(
            select(ChatMember).where(and_(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id))
        )
        member_record = result.scalar_one_or_none()

        if member_record and not member_record.left_at:
            member_record.left_at = now
            if member_record.metadata_:
                new_meta = dict(member_record.metadata_)
                new_meta["left_at"] = now.isoformat()
                member_record.metadata_ = new_meta

        if chat.admins and user_id in chat.admins:
            admins = list(chat.admins)
            if user_id in admins:
                admins.remove(user_id)
                chat.admins = admins

        chat.last_updated = now
        return member_record is not None

    def get_users_joined_last_day(self, chat_id: int) -> List[ChatUserDTO]:
        one_day_ago = datetime.now() - timedelta(days=1)
        return self._get_users_by_filter(chat_id, ChatMember.created_at > one_day_ago)

    def get_users_left_last_day(self, chat_id: int) -> List[ChatUserDTO]:
        one_day_ago = datetime.now() - timedelta(days=1)
        return self._get_users_by_filter(chat_id, ChatMember.left_at > one_day_ago)

    def _get_users_by_filter(self, chat_id: int, filter_condition) -> List[ChatUserDTO]:
        result = self.session.execute(select(ChatMember).where(and_(ChatMember.chat_id == chat_id, filter_condition)))
        members = result.scalars().all()

        dtos = []
        for member in members:
            metadata = member.metadata_ or {}
            dto = ChatUserDTO(
                user_id=member.user_id,
                username=metadata.get("username"),
                full_name=metadata.get("full_name", ""),
                is_admin=metadata.get("is_admin", False),
                created_at=member.created_at,
                left_at=member.left_at,
            )
            dtos.append(dto)
        return dtos

    def get_all_chats(self) -> List[ChatDTO]:
        result = self.session.execute(select(Chat))
        chats = result.scalars().all()

        chat_dtos = []
        for chat in chats:
            members_result = self.session.execute(select(ChatMember).where(ChatMember.chat_id == chat.chat_id))
            members = members_result.scalars().all()

            users_dict = {}
            for member in members:
                metadata = member.metadata_ or {}
                users_dict[str(member.user_id)] = ChatUserDTO(
                    user_id=member.user_id,
                    username=metadata.get("username"),
                    full_name=metadata.get("full_name"),
                    is_admin=metadata.get("is_admin", False),
                    created_at=member.created_at,
                    left_at=member.left_at,
                )

            chat_dto = ChatDTO(
                chat_id=chat.chat_id,
                username=chat.username,
                title=chat.title,
                created_at=chat.created_at,
                last_updated=chat.last_updated,
                users=users_dict,
                admins=chat.admins or [],
            )
            chat_dtos.append(chat_dto)
        return chat_dtos

    def get_all_chats_by_user(self, user_id: int) -> List[ChatDTO]:
        result = self.session.execute(select(ChatMember).where(ChatMember.user_id == user_id))
        memberships = result.scalars().all()

        chat_dtos = []
        for membership in memberships:
            chat_result = self.session.execute(select(Chat).where(Chat.chat_id == membership.chat_id))
            chat = chat_result.scalar_one_or_none()

            if chat:
                metadata = membership.metadata_ or {}
                users_dict = {
                    str(membership.user_id): ChatUserDTO(
                        user_id=membership.user_id,
                        username=metadata.get("username"),
                        full_name=metadata.get("full_name"),
                        is_admin=metadata.get("is_admin", False),
                        created_at=membership.created_at,
                        left_at=membership.left_at,
                    )
                }

                chat_dto = ChatDTO(
                    chat_id=chat.chat_id,
                    username=chat.username,
                    title=chat.title,
                    created_at=chat.created_at,
                    last_updated=chat.last_updated,
                    users=users_dict,
                    admins=chat.admins or [],
                )
                chat_dtos.append(chat_dto)
        return chat_dtos

    def update_chat_with_dict(self, chat_id: int, update_data: Dict) -> bool:
        result = self.session.execute(select(Chat).where(Chat.chat_id == chat_id))
        chat = result.scalar_one_or_none()

        if not chat:
            return False

        metadata_updated = False
        new_metadata = dict(chat.metadata_) if chat.metadata_ else {}

        for key, value in update_data.items():
            if hasattr(chat, key):
                setattr(chat, key, value)
            else:
                new_metadata[key] = value
                metadata_updated = True

        if metadata_updated:
            chat.metadata_ = new_metadata

        chat.last_updated = datetime.now(UTC)
        return True

    # BotUsers methods (from requests.py)
    def save_bot_user(self, user_id: int, user_name: Optional[str], user_type: int = 0) -> None:
        user = self.session.execute(select(BotUsers).where(BotUsers.user_id == user_id)).scalar_one_or_none()

        if user is None:
            new_user = BotUsers(user_id=user_id, user_name=user_name, user_type=user_type)
            self.session.add(new_user)
        else:
            if user_name:
                user.user_name = user_name
            user.user_type = user_type

    async def async_save_bot_user(self, user_id: int, user_name: Optional[str], user_type: int = 0) -> None:
        user = (await self.session.execute(select(BotUsers).where(BotUsers.user_id == user_id))).scalar_one_or_none()

        if user is None:
            new_user = BotUsers(user_id=user_id, user_name=user_name, user_type=user_type)
            self.session.add(new_user)
        else:
            if user_name:
                user.user_name = user_name
            user.user_type = user_type

    def get_user_id(self, user_name: str) -> int:
        if user_name.startswith("@"):
            username = user_name[1:]
            result = self.session.execute(
                select(BotUsers.user_id).where(BotUsers.user_name == username).limit(1)
            ).scalar_one_or_none()
            if not result:
                raise ValueError(f"User @{username} not found in the database.")
            return result
        else:
            try:
                return int(user_name)
            except ValueError:
                raise ValueError("Invalid user ID or username format. Use a numeric ID or @username.")

    def load_bot_users(self) -> List[BotUsers]:
        result = self.session.execute(select(BotUsers))
        return result.scalars().all()

    async def async_load_bot_users(self) -> List[BotUsers]:
        result = await self.session.execute(select(BotUsers))
        return result.scalars().all()

    def update_user_chat_date(self, user_id: int, chat_id: int) -> None:
        existing_record = self.session.execute(
            select(BotUserChats).where(and_(BotUserChats.user_id == user_id, BotUserChats.chat_id == chat_id))
        ).scalar_one_or_none()

        if existing_record:
            existing_record.dt_last = datetime.now()
        else:
            new_record = BotUserChats(user_id=user_id, chat_id=chat_id, dt_last=datetime.now())
            self.session.add(new_record)

    def get_user_by_id(self, user_id: int) -> Optional[BotUsers]:
        """Get user by ID."""
        result = self.session.execute(select(BotUsers).where(BotUsers.user_id == user_id))
        return result.scalar_one_or_none()

    async def async_get_user_by_id(self, user_id: int) -> Optional[BotUsers]:
        """Get user by ID."""
        result = await self.session.execute(select(BotUsers).where(BotUsers.user_id == user_id))
        return result.scalar_one_or_none()

    def save_user_type(self, user_id: int, user_type: int) -> None:
        """Update user type."""
        user = self.get_user_by_id(user_id)
        if user:
            user.user_type = user_type
        else:
            new_user = BotUsers(user_id=user_id, user_name=None, user_type=user_type)
            self.session.add(new_user)

    def get_chat_by_id(self, chat_id: int) -> Optional[Chat]:
        """Get chat record from database."""
        result = self.session.execute(select(Chat).where(Chat.chat_id == chat_id))
        return result.scalar_one_or_none()

    def upsert_chat_info(self, chat_id: int, title: Optional[str], username: Optional[str]) -> None:
        """Create or update chat with title and username."""
        now = datetime.now(UTC)
        chat = self.get_chat_by_id(chat_id)
        if chat:
            chat.title = title
            chat.username = username
            chat.last_updated = now
        else:
            chat = Chat(chat_id=chat_id, title=title, username=username, created_at=now, last_updated=now)
            self.session.add(chat)
