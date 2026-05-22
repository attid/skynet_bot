import asyncio

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


class SlowCommitAsyncSession(FakeAsyncSession):
    def __init__(self):
        super().__init__()
        self.commit_started = asyncio.Event()
        self.release_commit = asyncio.Event()

    async def commit(self):
        self.commit_started.set()
        await self.release_commit.wait()
        await super().commit()


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
async def test_db_session_middleware_commit_does_not_block_event_loop():
    session = SlowCommitAsyncSession()
    middleware = DbSessionMiddleware(FakeAsyncSessionPool(session))

    async def handler(event, handler_data):
        assert handler_data["session"] is session
        return "ok"

    task = asyncio.create_task(middleware(handler, object(), {}))
    await asyncio.wait_for(session.commit_started.wait(), timeout=1)

    probe_ran = False

    async def health_probe():
        nonlocal probe_ran
        await asyncio.sleep(0)
        probe_ran = True

    await asyncio.wait_for(health_probe(), timeout=1)
    session.release_commit.set()

    result = await asyncio.wait_for(task, timeout=1)

    assert result == "ok"
    assert probe_ran is True
    assert session.committed is True
