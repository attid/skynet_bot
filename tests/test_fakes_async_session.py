from other.constants import BotValueTypes
from db.repositories import ChatsRepository, ConfigRepository
from tests.fakes import FakeSession


async def test_fake_session_supports_async_config_repository_methods():
    session = FakeSession()

    await ConfigRepository(session).async_save_bot_value(123, BotValueTypes.PinnedUrl, "https://example.test")
    value = await ConfigRepository(session).async_load_bot_value(123, BotValueTypes.PinnedUrl)

    assert value == "https://example.test"


async def test_fake_session_supports_async_chats_repository_methods():
    session = FakeSession()

    await ChatsRepository(session).async_save_bot_user(123, "alice", 1)
    user = await ChatsRepository(session).async_get_user_by_id(123)

    assert user is not None
    assert user.user_name == "alice"
