from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from other.config_reader import config

engine = create_engine(config.postgres_url, pool_pre_ping=True)
SessionPool = sessionmaker(bind=engine)

async_engine = create_async_engine(config.async_postgres_url, pool_pre_ping=True)
AsyncSessionPool = async_sessionmaker(bind=async_engine, expire_on_commit=False)


def create_session():
    return SessionPool()


def create_async_session():
    return AsyncSessionPool()
