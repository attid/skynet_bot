import importlib
import warnings

from other import config_reader
from other.config_reader import to_asyncpg_url


def test_get_secrets_dir_returns_none_when_directory_is_missing(monkeypatch):
    monkeypatch.setattr(config_reader.os.path, "isdir", lambda path: False)

    assert config_reader.get_secrets_dir() is None


def test_reloading_config_reader_does_not_warn_when_secrets_dir_is_missing(monkeypatch):
    monkeypatch.setattr(config_reader.os.path, "isdir", lambda path: False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(config_reader)

    assert not [warning for warning in caught if 'directory "/run/secrets" does not exist' in str(warning.message)]


def test_to_asyncpg_url_adds_asyncpg_driver_to_plain_postgresql_url():
    assert to_asyncpg_url("postgresql://user:pass@db:5432/app") == "postgresql+asyncpg://user:pass@db:5432/app"


def test_to_asyncpg_url_replaces_psycopg_driver_with_asyncpg():
    assert to_asyncpg_url("postgresql+psycopg2://user:pass@db:5432/app") == "postgresql+asyncpg://user:pass@db:5432/app"


def test_to_asyncpg_url_keeps_existing_asyncpg_driver():
    assert to_asyncpg_url("postgresql+asyncpg://user:pass@db:5432/app") == "postgresql+asyncpg://user:pass@db:5432/app"
