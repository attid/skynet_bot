from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from other.config_reader import config

async_engine = create_async_engine(config.async_postgres_url, pool_pre_ping=True)
AsyncSessionPool = async_sessionmaker(bind=async_engine, expire_on_commit=False)


def create_async_session():
    return AsyncSessionPool()
