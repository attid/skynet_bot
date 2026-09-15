import pytest
import sys
import os
import socket
import random
import string
from contextlib import suppress
from aiohttp import web
from aiogram import Dispatcher, Bot, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.fsm.storage.memory import MemoryStorage

sys.path.append(os.getcwd())
os.environ.setdefault("TEST_TOKEN", "test-token")
os.environ.setdefault("BASE_FEE", "0")
os.environ.setdefault("OPENAI_KEY", "test-openai-key")
os.environ.setdefault("PRIVATE_SIGN", "test-private-sign")
os.environ.setdefault("CURRENCYLAYER_ID", "test-currencylayer-id")
os.environ.setdefault("COINLAYER_ID", "test-coinlayer-id")
os.environ.setdefault("DEBANK", "test-debank")
os.environ.setdefault("EURMTL_KEY", "test-eurmtl-key")
os.environ.setdefault("SENTRY_DSN", "test-sentry-dsn")
os.environ.setdefault("SENTRY_REPORT_DSN", "test-sentry-report-dsn")
os.environ.setdefault("HORIZON_URL", "https://horizon.example.com")
os.environ.setdefault("COINMARKETCAP", "test-coinmarketcap")
os.environ.setdefault("GRIST_TOKEN", "test-grist-token")
os.environ.setdefault("RELY_GRIST_TOKEN", "test-rely-grist-token")
os.environ.setdefault("BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")

from tests.fakes import FakeSession, TestAppContext
from middlewares.user_resolver import UserResolverMiddleware
from services import app_context as app_context_module
from other import aiogram_tools as aiogram_tools_module

# Import interfaces and classes for type hinting and mocking specific to your project
# Adjust imports based on your actual project structure
# Imports adjusted for current project state
# from core.interfaces.services import IStellarService
# from core.interfaces.repositories import IRepositoryFactory
# from infrastructure.factories.use_case_factory import IUseCaseFactory
# from infrastructure.services.localization_service import LocalizationService

# --- Constants ---
TEST_BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

# --- Helpers ---


def get_free_port():
    """Finds a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def random_address():
    """Generates a random Stellar-like address for testing."""
    return "G" + "".join(random.choices(string.ascii_uppercase + string.digits, k=55))


async def close_plain_http_session(session: AiohttpSession) -> None:
    """Close a test-only plain HTTP session without Aiogram's SSL shutdown delay."""
    client_session = session._session
    if client_session is not None and not client_session.closed:
        await client_session.close()
    session._session = None


# --- Fixtures: Config ---


@pytest.fixture(scope="function")
def telegram_server_config():
    port = get_free_port()
    return {"host": "localhost", "port": port, "url": f"http://localhost:{port}"}


@pytest.fixture(scope="function")
def horizon_server_config():
    port = get_free_port()
    return {"host": "localhost", "port": port, "url": f"http://localhost:{port}"}


@pytest.fixture(scope="function")
def grist_server_config():
    port = get_free_port()
    return {"host": "localhost", "port": port, "url": f"http://localhost:{port}"}


# --- Mock Servers ---


# 1. Mock Telegram Server
@pytest.fixture
async def mock_telegram(telegram_server_config):
    """Starts a local mock Telegram server."""

    class TelegramMockState:
        def __init__(self):
            self.received_requests = []
            self.custom_responses = {}  # method -> response_dict
            self.base_url = telegram_server_config["url"]
            self.files_by_id = {}
            self.files_by_path = {}

        def add_response(self, method, response):
            self.custom_responses[method] = response

        def get_requests(self):
            return self.received_requests

        def add_file(self, file_id, content, file_path=None):
            if file_path is None:
                file_path = f"files/{file_id}.bin"
            self.files_by_id[file_id] = {"file_path": file_path, "content": content}
            self.files_by_path[file_path] = content

    state = TelegramMockState()
    routes = web.RouteTableDef()

    @routes.post("/bot{token}/{method}")
    async def handle_request(request):
        token = request.match_info["token"]
        method = request.match_info["method"]

        if request.content_type == "application/json":
            try:
                data = await request.json()
            except Exception:
                data = {}
        else:
            if request.content_type.startswith("multipart/"):
                with suppress(Exception):
                    await request.read()
                data = {}
            else:
                try:
                    data = await request.post()
                except Exception:
                    data = {}

        data = dict(data)
        state.received_requests.append({"method": method, "token": token, "data": data})

        # Check for custom response
        if method in state.custom_responses:
            return web.json_response(state.custom_responses[method])

        # Default responses for common methods
        if method == "getMe":
            return web.json_response(
                {"ok": True, "result": {"id": 123456, "is_bot": True, "first_name": "TestBot", "username": "test_bot"}}
            )
        elif method in ("sendMessage", "forwardMessage"):
            chat_id = data.get("chat_id", 0)
            text = data.get("text", "")
            return web.json_response(
                {
                    "ok": True,
                    "result": {
                        "message_id": random.randint(1, 1000),
                        "date": 1234567890,
                        "chat": {"id": chat_id, "type": "private"},
                        "text": text,
                    },
                }
            )
        elif method == "sendPhoto":
            chat_id = data.get("chat_id", 0)
            caption = data.get("caption")
            return web.json_response(
                {
                    "ok": True,
                    "result": {
                        "message_id": random.randint(1, 1000),
                        "date": 1234567890,
                        "chat": {"id": chat_id, "type": "private"},
                        "caption": caption,
                        "photo": [{"file_id": "photo_id", "file_unique_id": "photo_unique", "width": 1, "height": 1}],
                    },
                }
            )
        elif method == "sendDocument":
            chat_id = data.get("chat_id", 0)
            return web.json_response(
                {
                    "ok": True,
                    "result": {
                        "message_id": random.randint(1, 1000),
                        "date": 1234567890,
                        "chat": {"id": chat_id, "type": "private"},
                        "document": {
                            "file_id": "doc_id",
                            "file_unique_id": "doc_unique",
                            "file_name": "file.txt",
                            "mime_type": "text/plain",
                        },
                    },
                }
            )
        elif method == "copyMessage":
            return web.json_response({"ok": True, "result": {"message_id": random.randint(1, 1000)}})
        elif method == "sendPoll":
            return web.json_response(
                {
                    "ok": True,
                    "result": {
                        "message_id": random.randint(1, 1000),
                        "date": 1234567890,
                        "chat": {"id": 123, "type": "private"},
                        "poll": {
                            "id": str(random.randint(1, 1000)),
                            "question": "Q",
                            "options": [{"persistent_id": "pid_A", "text": "A", "voter_count": 0}],
                            "total_voter_count": 0,
                            "is_closed": False,
                            "is_anonymous": True,
                            "type": "regular",
                            "allows_multiple_answers": False,
                            "allows_revoting": False,
                            "members_only": False,
                        },
                    },
                }
            )
        elif method == "getChatAdministrators":
            # Default fallback: emtpy list or some generic admin
            return web.json_response(
                {
                    "ok": True,
                    "result": [
                        {
                            "status": "creator",
                            "user": {"id": 123456, "is_bot": True, "first_name": "TestBot", "username": "test_bot"},
                            "is_anonymous": False,
                            "custom_title": None,
                        }
                    ],
                }
            )
        elif method == "getChatMember":
            return web.json_response(
                {
                    "ok": True,
                    "result": {
                        "user": {"id": data.get("user_id", 0), "is_bot": False, "first_name": "User"},
                        "status": "member",
                    },
                }
            )
        elif method == "getChat":
            return web.json_response(
                {
                    "ok": True,
                    "result": {
                        "id": data.get("chat_id", 0),
                        "type": "supergroup",
                        "title": "Test Chat",
                        "accent_color_id": 0,
                        "max_reaction_count": 0,
                        "permissions": {"can_send_messages": True},
                        "accepted_gift_types": {
                            "unlimited_gifts": True,
                            "limited_gifts": False,
                            "unique_gifts": False,
                            "premium_subscription": False,
                            "gifts_from_channels": False,
                        },
                    },
                }
            )
        elif method == "getFile":
            file_id = data.get("file_id")
            if file_id in state.files_by_id:
                return web.json_response(
                    {
                        "ok": True,
                        "result": {
                            "file_id": file_id,
                            "file_unique_id": str(file_id),
                            "file_path": state.files_by_id[file_id]["file_path"],
                            "file_size": len(state.files_by_id[file_id]["content"]),
                        },
                    }
                )
            return web.json_response(
                {
                    "ok": True,
                    "result": {"file_id": file_id, "file_unique_id": str(file_id), "file_path": f"files/{file_id}.bin"},
                }
            )

        return web.json_response({"ok": True, "result": True})

    @routes.get("/file/bot{token}/{file_path:.*}")
    async def handle_file(request):
        file_path = request.match_info["file_path"]
        content = state.files_by_path.get(file_path)
        if content is None:
            return web.Response(status=404)
        return web.Response(body=content)

    app = web.Application(client_max_size=200 * 1024 * 1024)
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, telegram_server_config["host"], telegram_server_config["port"])
    await site.start()

    yield state

    await runner.cleanup()


# 2. Mock Horizon Server
@pytest.fixture
async def mock_horizon(horizon_server_config):
    """Starts a local mock Stellar Horizon server."""

    class HorizonMockState:
        def __init__(self):
            self.requests = []
            self.accounts = {}
            self.offers = {}
            self.paths = []
            self.transaction_response = {"successful": True, "hash": "abc123"}

        def set_account(self, account_id, balances=None, data=None):
            self.accounts[account_id] = {
                "id": account_id,
                "account_id": account_id,
                "sequence": "123",
                "balances": balances or [{"asset_type": "native", "balance": "100.0"}],
                "signers": [{"key": account_id, "weight": 1}],
                "thresholds": {"low_threshold": 0, "med_threshold": 1, "high_threshold": 2},
                "data": data or {},
                "flags": {"auth_required": False, "auth_revocable": False},
            }

        def get_requests(self, endpoint=None):
            if endpoint:
                return [r for r in self.requests if r["endpoint"] == endpoint]
            return self.requests

    state = HorizonMockState()

    # Route definitions
    routes = web.RouteTableDef()

    @routes.get("/accounts/{account_id}")
    async def get_account(request):
        account_id = request.match_info["account_id"]
        state.requests.append({"endpoint": "accounts", "method": "GET", "account_id": account_id})

        if account_id in state.accounts:
            return web.json_response(state.accounts[account_id])
        return web.json_response({"status": 404, "title": "Not Found"}, status=404)

    @routes.get("/accounts")
    async def get_accounts(request):
        state.requests.append({"endpoint": "accounts_query", "method": "GET", "params": dict(request.rel_url.query)})
        return web.json_response({"_embedded": {"records": []}})

    @routes.get("/fee_stats")
    async def fee_stats(request):
        state.requests.append({"endpoint": "fee_stats", "method": "GET"})
        return web.json_response(
            {
                "last_ledger": "1",
                "fee_charged": {"max": "100", "min": "100", "mode": "100", "p95": "100"},
                "max_fee": {"mode": "100"},
            }
        )

    @routes.post("/transactions")
    async def submit_transaction(request):
        data = await request.post()
        state.requests.append({"endpoint": "transactions", "method": "POST", "data": dict(data)})
        if state.transaction_response.get("successful"):
            return web.json_response(state.transaction_response)
        return web.json_response(state.transaction_response, status=400)

    @routes.get("/{path:.*}")
    async def catch_all(request):
        path = request.match_info["path"]
        state.requests.append({"endpoint": path, "method": "GET"})
        return web.json_response({"status": 404}, status=404)

    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, horizon_server_config["host"], horizon_server_config["port"])
    await site.start()

    yield state

    await runner.cleanup()


# 3. Mock Grist Server
@pytest.fixture
async def mock_grist(grist_server_config):
    """Starts a local mock Grist server."""

    class GristMockState:
        def __init__(self):
            self.requests = []
            self.records = {}  # table_id -> list of records

        def add_records(self, table_id, records):
            if table_id not in self.records:
                self.records[table_id] = []
            self.records[table_id].extend(records)

    state = GristMockState()
    routes = web.RouteTableDef()

    @routes.get("/api/docs/{doc_id}/tables/{table_id}/records")
    async def get_records(request):
        table_id = request.match_info["table_id"]
        state.requests.append({"table": table_id, "method": "GET"})
        records = state.records.get(table_id, [])
        return web.json_response({"records": records})

    @routes.post("/api/docs/{doc_id}/tables/{table_id}/records")
    async def add_records(request):
        table_id = request.match_info["table_id"]
        try:
            body = await request.json()
            records_to_add = body.get("records", [])
            new_records = []
            if table_id not in state.records:
                state.records[table_id] = []

            for record_data in records_to_add:
                # Generate a simple incremental ID based on current list length
                new_id = len(state.records[table_id]) + 1 + random.randint(100, 999)
                fields = record_data.get("fields", {})

                # Apply defaults for specific tables
                if table_id == "Deals" and "Checked" not in fields:
                    fields["Checked"] = False

                new_record = {"id": new_id, "fields": fields}
                state.records[table_id].append(new_record)
                new_records.append(new_record["id"])  # Grist POST returns IDs usually
        except Exception:
            pass

        state.requests.append({"table": table_id, "method": "POST"})
        # Grist API returns list of created record IDs
        return web.json_response({"records": new_records})

    @routes.patch("/api/docs/{doc_id}/tables/{table_id}/records")
    async def patch_records(request):
        table_id = request.match_info["table_id"]
        body = await request.json()
        records_to_patch = body.get("records", [])
        existing = {record["id"]: record for record in state.records.get(table_id, [])}
        patched_ids = []

        for record_data in records_to_patch:
            record_id = record_data.get("id")
            if record_id not in existing:
                continue
            existing[record_id].setdefault("fields", {}).update(record_data.get("fields", {}))
            patched_ids.append(record_id)

        state.requests.append({"table": table_id, "method": "PATCH"})
        return web.json_response({"records": patched_ids})

    @routes.put("/api/docs/{doc_id}/tables/{table_id}/records")
    async def put_records(request):
        body = await request.json()
        state.requests.append(
            {
                "doc_id": request.match_info["doc_id"],
                "table": request.match_info["table_id"],
                "method": "PUT",
                "json": body,
            }
        )
        return web.json_response({"records": []})

    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, grist_server_config["host"], grist_server_config["port"])
    await site.start()

    yield state

    await runner.cleanup()


# --- Router Test Infrastructure ---


@pytest.fixture
async def router_bot(mock_telegram, telegram_server_config):
    """Creates a Bot instance connected to mock Telegram server."""
    session = AiohttpSession(api=TelegramAPIServer.from_base(telegram_server_config["url"]))
    bot = Bot(token=TEST_BOT_TOKEN, session=session)
    yield bot
    await close_plain_http_session(session)


@pytest.fixture
def dp():
    """Provides a standalone Dispatcher for tests not using router_app_context."""
    return Dispatcher(storage=MemoryStorage())


@pytest.fixture
async def router_app_context(mock_telegram, router_bot, horizon_server_config, mock_horizon):
    """
    Standard app_context for router tests.
    Uses fake services and real Bot connected to mock_telegram.
    Also patches the global app_context singleton so filters can use test services.
    """
    from other.config_reader import config as app_config

    original_horizon_url = app_config.horizon_url
    app_config.horizon_url = horizon_server_config["url"]

    test_ctx = TestAppContext(bot=router_bot, dispatcher=Dispatcher(storage=MemoryStorage()))

    # Patch the global app_context singleton so filters (like ChatInOption) use test services
    # Need to patch both the source module AND the importing module
    original_singleton = app_context_module.app_context
    original_aiogram_tools = aiogram_tools_module.app_context

    app_context_module.app_context = test_ctx
    aiogram_tools_module.app_context = test_ctx

    yield test_ctx

    app_config.horizon_url = original_horizon_url

    # Restore the original singletons
    app_context_module.app_context = original_singleton
    aiogram_tools_module.app_context = original_aiogram_tools


class RouterTestMiddleware(BaseMiddleware):
    """
    Middleware for router tests to inject dependencies.
    Uses shared FakeSession from app_context so tests can set up data.
    """

    def __init__(self, app_context):
        self.app_context = app_context
        self._user_resolver = UserResolverMiddleware(app_context, app_context.bot)

    async def __call__(self, handler, event, data):
        data["app_context"] = self.app_context
        # Use shared session from app_context so tests can set up data
        data["session"] = self.app_context.session
        if hasattr(self.app_context, "localization_service"):
            data["l10n"] = self.app_context.localization_service
        skyuser = self._user_resolver._resolve_user(event)
        data["skyuser"] = skyuser
        return await handler(event, data)


class MockDbMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        data["session"] = FakeSession()
        return await handler(event, data)


# --- Updates Factories ---


def create_message_update(user_id, text, **kwargs) -> types.Update:
    return types.Update(
        update_id=1,
        message=types.Message(
            message_id=1,
            date=1234567890,
            chat=types.Chat(id=user_id, type="private"),
            from_user=types.User(id=user_id, is_bot=False, first_name="Test"),
            text=text,
            **kwargs,
        ),
    )


def create_callback_update(user_id, data, message_id=1, **kwargs) -> types.Update:
    return types.Update(
        update_id=1,
        callback_query=types.CallbackQuery(
            id="cb1",
            from_user=types.User(id=user_id, is_bot=False, first_name="Test"),
            chat_instance="ci1",
            message=types.Message(
                message_id=message_id, date=1234567890, chat=types.Chat(id=user_id, type="private"), text="msg"
            ),
            data=data,
            **kwargs,
        ),
    )
