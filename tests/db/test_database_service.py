from services.database_service import DatabaseService
from tests.fakes import FakeSession


def _make_pool(session):
    class Pool:
        def __call__(self):
            return self

        def __enter__(self):
            return session

        def __exit__(self, exc_type, exc, tb):
            return False

    return Pool()


def _make_async_pool(session):
    class Pool:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    return Pool()


class FakeAsyncSession(FakeSession):
    async def commit(self):
        super().commit()

    async def execute(self, statement, *args, **kwargs):
        return super().execute(statement, *args, **kwargs)

    async def flush(self):
        super().flush()


def test_save_bot_value_delegation(monkeypatch):
    service = DatabaseService()
    session_instance = FakeAsyncSession()
    service.session_pool = _make_pool(session_instance)
    service.async_session_pool = _make_async_pool(session_instance)

    calls = {}

    class FakeConfigRepo:
        def __init__(self, session):
            calls["session"] = session

        async def async_save_bot_value(self, chat_id, key, value):
            calls["save"] = (chat_id, key, value)

    monkeypatch.setattr("services.database_service.ConfigRepository", FakeConfigRepo)

    chat_id = 1
    key = 2
    value = "val"

    import asyncio

    asyncio.run(service.save_bot_value(chat_id, key, value))

    assert calls["session"] is session_instance
    assert calls["save"] == (chat_id, key, value)
    assert session_instance.committed is True


def test_load_bot_value_delegation(monkeypatch):
    service = DatabaseService()
    session_instance = FakeAsyncSession()
    service.session_pool = _make_pool(session_instance)
    service.async_session_pool = _make_async_pool(session_instance)

    expected_value = "loaded"
    calls = {}

    class FakeConfigRepo:
        def __init__(self, session):
            calls["session"] = session

        async def async_load_bot_value(self, chat_id, key, default):
            calls["load"] = (chat_id, key, default)
            return expected_value

    monkeypatch.setattr("services.database_service.ConfigRepository", FakeConfigRepo)

    import asyncio

    result = asyncio.run(service.load_bot_value(1, 2))

    assert result == expected_value
    assert calls["load"] == (1, 2, "")


def test_update_chat_info_delegation(monkeypatch):
    service = DatabaseService()
    session_instance = FakeAsyncSession()
    service.session_pool = _make_pool(session_instance)
    service.async_session_pool = _make_async_pool(session_instance)

    calls = {}

    class FakeChatsRepo:
        def __init__(self, session):
            calls["session"] = session

        async def async_update_chat_info(self, chat_id, members, clear_users=False):
            calls["update"] = (chat_id, members, clear_users)

    monkeypatch.setattr("services.database_service.ChatsRepository", FakeChatsRepo)

    chat_id = 100
    members = []

    import asyncio

    asyncio.run(service.update_chat_info(chat_id, members))

    assert calls["session"] is session_instance
    assert calls["update"] == (chat_id, members, False)
    assert session_instance.committed is True
