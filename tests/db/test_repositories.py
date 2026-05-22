import json
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.repositories.chats import ChatsRepository
from db.repositories.config import ConfigRepository
from other.pyro_tools import GroupMember
from shared.infrastructure.database.models import Base, BotUsers, Chat, ChatMember


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_save_and_load_bot_value(db_session):
    repo = ConfigRepository(db_session)
    chat_id = 123
    chat_key = 1
    value = "test_value"

    await repo.async_save_bot_value(chat_id, chat_key, value)
    await db_session.commit()
    loaded_value = await repo.async_load_bot_value(chat_id, chat_key)
    assert loaded_value == value

    new_value = "new_test_value"
    await repo.async_save_bot_value(chat_id, chat_key, new_value)
    await db_session.commit()
    loaded_value = await repo.async_load_bot_value(chat_id, chat_key)
    assert loaded_value == new_value

    await repo.async_save_bot_value(chat_id, chat_key, None)
    await db_session.commit()
    loaded_value = await repo.async_load_bot_value(chat_id, chat_key, default_value="default")
    assert loaded_value == "default"


@pytest.mark.asyncio
async def test_json_handling(db_session):
    repo = ConfigRepository(db_session)
    chat_id = 456
    chat_key = 2

    json_value = {"key": "value", "list": [1, 2, 3]}
    await repo.async_save_bot_value(chat_id, chat_key, json_value)
    await db_session.commit()

    loaded_value = await repo.async_load_bot_value(chat_id, chat_key)
    assert json.loads(loaded_value) == json_value


@pytest.mark.asyncio
async def test_dict_value_operations(db_session):
    repo = ConfigRepository(db_session)
    chat_id = 789
    chat_key = 3

    await repo.async_update_dict_value(chat_id, chat_key, "field1", "value1")
    await db_session.commit()

    val = await repo.async_get_dict_value(chat_id, chat_key, "field1")
    assert val == "value1"

    await repo.async_update_dict_value(chat_id, chat_key, "field2", "value2")
    await db_session.commit()

    assert await repo.async_get_dict_value(chat_id, chat_key, "field1") == "value1"
    assert await repo.async_get_dict_value(chat_id, chat_key, "field2") == "value2"
    assert await repo.async_get_dict_value(chat_id, chat_key, "field3", "def") == "def"


@pytest.mark.asyncio
async def test_kv_store(db_session):
    repo = ConfigRepository(db_session)
    key = "test_key"
    value = {"data": 123}

    await repo.async_save_kv_value(key, value)
    await db_session.commit()

    loaded = await repo.async_load_kv_value(key)
    assert loaded == value

    await repo.async_save_kv_value(key, "updated")
    await db_session.commit()
    assert await repo.async_load_kv_value(key) == "updated"


@pytest.mark.asyncio
async def test_update_chat_info(db_session):
    repo = ChatsRepository(db_session)
    chat_id = 1001

    member1 = GroupMember(user_id=1, username="user1", full_name="User One", is_admin=True)
    member2 = GroupMember(user_id=2, username="user2", full_name="User Two", is_admin=False)

    await repo.async_update_chat_info(chat_id, [member1, member2])
    await db_session.commit()

    chat = (await db_session.execute(select(Chat).where(Chat.chat_id == chat_id))).scalar_one_or_none()
    assert chat is not None
    assert 1 in chat.admins
    assert 2 not in chat.admins

    members = (await db_session.execute(select(ChatMember).where(ChatMember.chat_id == chat_id))).scalars().all()
    assert len(members) == 2

    users = (await db_session.execute(select(BotUsers))).scalars().all()
    assert len(users) == 2

    member2_updated = GroupMember(user_id=2, username="user2", full_name="User Two", is_admin=True)
    await repo.async_update_chat_info(chat_id, [member2_updated])
    await db_session.commit()

    chat = (await db_session.execute(select(Chat).where(Chat.chat_id == chat_id))).scalar_one()
    assert 2 in chat.admins
    assert 1 in chat.admins


@pytest.mark.asyncio
async def test_add_and_remove_user(db_session):
    repo = ChatsRepository(db_session)
    chat_id = 2002
    member = GroupMember(user_id=10, username="joiner", full_name="Joiner", is_admin=False)

    await repo.async_add_user_to_chat(chat_id, member)
    await db_session.commit()

    chat_member = (
        await db_session.execute(select(ChatMember).where(ChatMember.chat_id == chat_id, ChatMember.user_id == 10))
    ).scalar_one_or_none()
    assert chat_member is not None
    assert chat_member.left_at is None

    await repo.async_remove_user_from_chat(chat_id, 10)
    await db_session.commit()

    chat_member = (
        await db_session.execute(select(ChatMember).where(ChatMember.chat_id == chat_id, ChatMember.user_id == 10))
    ).scalar_one()
    assert chat_member.left_at is not None


@pytest.mark.asyncio
async def test_get_users_joined_last_day(db_session):
    repo = ChatsRepository(db_session)
    chat_id = 3003

    m1 = GroupMember(user_id=100, username="u1", full_name="U1", is_admin=False)
    await repo.async_add_user_to_chat(chat_id, m1)
    await db_session.commit()

    old_date = datetime(2020, 1, 1)
    m2 = GroupMember(user_id=101, username="u2", full_name="U2", is_admin=False)
    await repo.async_add_user_to_chat(chat_id, m2)
    await db_session.commit()

    db_member = (await db_session.execute(select(ChatMember).where(ChatMember.user_id == 101))).scalar_one()
    db_member.created_at = old_date
    await db_session.commit()

    joined = await repo.async_get_users_joined_last_day(chat_id)
    assert len(joined) == 1
    assert joined[0].user_id == 100
