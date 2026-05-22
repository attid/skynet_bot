from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from db import session as db_session


def test_db_session_exports_async_engine_and_session_pool():
    assert isinstance(db_session.async_engine, AsyncEngine)
    assert isinstance(db_session.AsyncSessionPool, async_sessionmaker)
