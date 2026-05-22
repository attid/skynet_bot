import os

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

start_path = os.path.dirname(os.path.dirname(__file__)) + "/"
dotenv_path = os.path.join(start_path, ".env")
default_secrets_path = "/run/secrets"


def to_asyncpg_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql+psycopg2://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


def get_secrets_dir() -> str | None:
    if os.path.isdir(default_secrets_path):
        return default_secrets_path
    return None


class Settings(BaseSettings):
    bot_token: SecretStr
    test_token: SecretStr
    telegram_api_url: str | None = None  # e.g. http://telegram-bot-api:8081 for self-hosted Bot API
    base_fee: int
    redis_url: str
    # firebird_url: str
    postgres_url: str
    openai_key: SecretStr
    openrouter_key: SecretStr | None = None
    private_sign: SecretStr
    currencylayer_id: str
    coinlayer_id: str
    debank: SecretStr
    eurmtl_key: str
    sentry_dsn: str
    sentry_report_dsn: str
    horizon_url: str
    stellar_testnet: bool = False
    coinmarketcap: SecretStr
    # mongodb_url: str
    pyro_api_id: int = 0
    pyro_api_hash: SecretStr | None = None
    grist_token: str
    miniapps_key: str | None = None
    test_mode: bool = True

    @property
    def async_postgres_url(self) -> str:
        return to_asyncpg_url(self.postgres_url)

    # Stellar Notifier webhook settings
    notifier_url: str | None = None  # http://operations-notifier:8000
    webhook_public_url: str | None = None  # http://skynet_bot:8081/webhook
    webhook_port: int = 8081
    notifier_auth_token: str | None = None  # Bearer token for notifier API

    model_config = SettingsConfigDict(
        env_file=dotenv_path,
        env_file_encoding="utf-8",
        extra="allow",
        case_sensitive=False,
        secrets_dir=get_secrets_dir(),
    )


config: Settings = Settings()  # type: ignore[call-arg]

if os.getenv("ENVIRONMENT", "test") == "production":
    config.test_mode = False
else:
    config.test_mode = True
