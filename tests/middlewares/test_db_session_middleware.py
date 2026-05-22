import pytest

from middlewares.db import DbSessionMiddleware


class FakeAsyncSession:
    def __init__(self):
        self.entered = False
        self.exited = False
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class FakeAsyncSessionPool:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


class FakeSyncSession:
    def __init__(self):
        self.entered = False
        self.exited = False
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited = True

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeSyncSessionPool:
    def __init__(self, session):
        self.session = session
        self.call_count = 0

    def __call__(self):
        self.call_count += 1
        return self.session


@pytest.mark.asyncio
async def test_db_session_middleware_commits_async_session_on_success():
    session = FakeAsyncSession()
    middleware = DbSessionMiddleware(FakeAsyncSessionPool(session))
    data = {}

    async def handler(event, handler_data):
        assert handler_data["session"] is session
        return "ok"

    result = await middleware(handler, object(), data)

    assert result == "ok"
    assert session.entered is True
    assert session.committed is True
    assert session.rolled_back is False
    assert session.exited is True


@pytest.mark.asyncio
async def test_db_session_middleware_rolls_back_async_session_on_error():
    session = FakeAsyncSession()
    middleware = DbSessionMiddleware(FakeAsyncSessionPool(session))

    async def handler(event, handler_data):
        assert handler_data["session"] is session
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await middleware(handler, object(), {})

    assert session.entered is True
    assert session.committed is False
    assert session.rolled_back is True
    assert session.exited is True


@pytest.mark.asyncio
async def test_db_session_middleware_keeps_legacy_sync_session_pool_working():
    session = FakeSyncSession()
    middleware = DbSessionMiddleware(FakeSyncSessionPool(session))

    async def handler(event, handler_data):
        assert handler_data["session"] is session
        return "ok"

    result = await middleware(handler, object(), {})

    assert result == "ok"
    assert session.entered is True
    assert session.committed is True
    assert session.rolled_back is False
    assert session.exited is True


@pytest.mark.asyncio
async def test_db_session_middleware_lazy_mode_does_not_open_unused_session():
    session = FakeSyncSession()
    pool = FakeSyncSessionPool(session)
    middleware = DbSessionMiddleware(pool, lazy=True)

    async def handler(event, handler_data):
        assert "session" in handler_data
        return "ok"

    result = await middleware(handler, object(), {})

    assert result == "ok"
    assert pool.call_count == 0
    assert session.entered is False
    assert session.committed is False


@pytest.mark.asyncio
async def test_db_session_middleware_lazy_mode_commits_when_session_is_used():
    session = FakeSyncSession()
    pool = FakeSyncSessionPool(session)
    middleware = DbSessionMiddleware(pool, lazy=True)

    async def handler(event, handler_data):
        handler_data["session"].add("record")
        return "ok"

    session.add = lambda obj: None

    result = await middleware(handler, object(), {})

    assert result == "ok"
    assert pool.call_count == 1
    assert session.entered is True
    assert session.committed is True
    assert session.exited is True


@pytest.mark.asyncio
async def test_db_session_middleware_lazy_mode_rolls_back_used_session_on_error():
    session = FakeSyncSession()
    pool = FakeSyncSessionPool(session)
    middleware = DbSessionMiddleware(pool, lazy=True)

    async def handler(event, handler_data):
        handler_data["session"].add("record")
        raise RuntimeError("boom")

    session.add = lambda obj: None

    with pytest.raises(RuntimeError, match="boom"):
        await middleware(handler, object(), {})

    assert pool.call_count == 1
    assert session.entered is True
    assert session.committed is False
    assert session.rolled_back is True
    assert session.exited is True
