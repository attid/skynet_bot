import pytest

from db.repositories.chats import ChatsRepository
from db.repositories.config import ConfigRepository
from db.repositories.finance import FinanceRepository
from db.repositories.messages import MessageRepository
from other.pyro_tools import GroupMember


class FakeScalarResult:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value

    def scalar(self):
        return self._value


class FakeAsyncSession:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.added = []
        self.deleted = []
        self.executed = []
        self.flushed = False

    async def execute(self, stmt):
        self.executed.append(stmt)
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()

    async def flush(self):
        self.flushed = True

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)


class FakeUser:
    user_type = 2
    user_name = None


class FakeConfigRecord:
    chat_value = "enabled"


class FakeChat:
    def __init__(self):
        self.admins = [123]
        self.last_updated = None


class FakeChatMember:
    def __init__(self):
        self.left_at = None
        self.metadata_ = {"username": "user"}


@pytest.mark.asyncio
async def test_config_repository_async_load_bot_value_awaits_execute():
    session = FakeAsyncSession([FakeScalarResult(FakeConfigRecord())])

    result = await ConfigRepository(session).async_load_bot_value(1, "captcha")

    assert result == "enabled"
    assert len(session.executed) == 1


@pytest.mark.asyncio
async def test_chats_repository_async_get_user_by_id_awaits_execute():
    session = FakeAsyncSession([FakeScalarResult(FakeUser())])

    result = await ChatsRepository(session).async_get_user_by_id(123)

    assert result is not None
    assert result.user_type == 2
    assert len(session.executed) == 1


@pytest.mark.asyncio
async def test_chats_repository_async_load_bot_users_awaits_execute():
    users = [FakeUser()]
    session = FakeAsyncSession([FakeScalarResult(users)])

    result = await ChatsRepository(session).async_load_bot_users()

    assert result == users
    assert len(session.executed) == 1


@pytest.mark.asyncio
async def test_chats_repository_async_add_user_to_chat_uses_async_execute_and_flush():
    session = FakeAsyncSession([FakeScalarResult(None), FakeScalarResult(None), FakeScalarResult(None)])
    member = GroupMember(user_id=123, username="user", full_name="User", is_admin=False)

    result = await ChatsRepository(session).async_add_user_to_chat(-100, member)

    assert result is True
    assert len(session.executed) == 3
    assert session.flushed is True
    assert len(session.added) == 3


@pytest.mark.asyncio
async def test_chats_repository_async_remove_user_from_chat_uses_async_execute():
    chat = FakeChat()
    member = FakeChatMember()
    session = FakeAsyncSession([FakeScalarResult(chat), FakeScalarResult(member)])

    result = await ChatsRepository(session).async_remove_user_from_chat(-100, 123)

    assert result is True
    assert len(session.executed) == 2
    assert member.left_at is not None
    assert 123 not in chat.admins


@pytest.mark.asyncio
async def test_chats_repository_async_save_bot_user_updates_existing_user():
    user = FakeUser()
    session = FakeAsyncSession([FakeScalarResult(user)])

    await ChatsRepository(session).async_save_bot_user(123, "new_name", 1)

    assert user.user_name == "new_name"
    assert user.user_type == 1
    assert session.added == []


@pytest.mark.asyncio
async def test_message_repository_async_send_admin_message_adds_message():
    session = FakeAsyncSession()

    await MessageRepository(session).async_send_admin_message("problem")

    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_finance_repository_async_get_total_user_div_awaits_execute():
    session = FakeAsyncSession([FakeScalarResult(12.5)])

    result = await FinanceRepository(session).async_get_total_user_div()

    assert result == 12.5
    assert len(session.executed) == 1


@pytest.mark.asyncio
async def test_finance_repository_async_get_new_effects_for_token_awaits_execute():
    effects = [object()]
    session = FakeAsyncSession([FakeScalarResult(effects)])

    result = await FinanceRepository(session).async_get_new_effects_for_token("USDM", "123", 10)

    assert result == effects
    assert len(session.executed) == 1


@pytest.mark.asyncio
async def test_finance_repository_async_get_operations_awaits_execute():
    operations = [object()]
    session = FakeAsyncSession([FakeScalarResult(operations)])

    result = await FinanceRepository(session).async_get_operations("123")

    assert result == operations
    assert len(session.executed) == 1
