import inspect
from contextlib import suppress

from other.aiogram_tools import add_text, answer_text_file, multi_answer, multi_reply
from services.bot_state_service import BotStateService
from services.channel_link_service import ChannelLinkService


class FakeAsyncMethod:
    def __init__(self, return_value=None, side_effect=None):
        self.return_value = return_value
        self.side_effect = side_effect
        self._calls = []

    async def __call__(self, *args, **kwargs):
        self._calls.append((args, kwargs))
        if self.side_effect is not None:
            result = self.side_effect(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        return self.return_value

    @property
    def called(self):
        return len(self._calls) > 0

    @property
    def call_count(self):
        return len(self._calls)

    @property
    def call_args(self):
        return self._calls[-1] if self._calls else None

    @property
    def call_args_list(self):
        return list(self._calls)

    def assert_called_once(self):
        assert self.call_count == 1, f"Expected 1 call, got {self.call_count}"

    def assert_called(self):
        assert self.call_count > 0, "Expected at least one call, got 0"

    def assert_not_called(self):
        assert self.call_count == 0, f"Expected 0 calls, got {self.call_count}"

    def assert_not_awaited(self):
        self.assert_not_called()

    def assert_awaited_once_with(self, *args, **kwargs):
        self.assert_called_once()
        last_args, last_kwargs = self.call_args
        assert last_args == args and last_kwargs == kwargs, (
            f"Expected args={args}, kwargs={kwargs}, got args={last_args}, kwargs={last_kwargs}"
        )

    def assert_awaited_once(self):
        self.assert_called_once()


class FakeSyncMethod:
    def __init__(self, return_value=None, side_effect=None):
        self.return_value = return_value
        self.side_effect = side_effect
        self._calls = []

    def __call__(self, *args, **kwargs):
        self._calls.append((args, kwargs))
        if self.side_effect is not None:
            return self.side_effect(*args, **kwargs)
        return self.return_value

    @property
    def called(self):
        return len(self._calls) > 0

    @property
    def call_count(self):
        return len(self._calls)

    @property
    def call_args(self):
        return self._calls[-1] if self._calls else None

    def assert_called_once(self):
        assert self.call_count == 1, f"Expected 1 call, got {self.call_count}"

    def assert_called(self):
        assert self.call_count > 0, "Expected at least one call, got 0"

    def assert_not_called(self):
        assert self.call_count == 0, f"Expected 0 calls, got {self.call_count}"


class FakeBotConfig:
    """Fake BotConfig model for testing."""

    def __init__(self, chat_id, chat_key, chat_value, chat_key_name=None):
        self.chat_id = chat_id
        self.chat_key = chat_key
        self.chat_value = chat_value
        self.chat_key_name = chat_key_name


class FakeBotUsers:
    """Fake BotUsers model for testing."""

    def __init__(self, user_id, user_name=None, user_type=0):
        self.user_id = user_id
        self.user_name = user_name
        self.user_type = user_type


class FakeChat:
    """Fake Chat model for testing."""

    def __init__(self, chat_id, admins=None, metadata_=None):
        self.chat_id = chat_id
        self.admins = admins or []
        self.metadata_ = metadata_ or {}
        self.last_updated = None
        self.created_at = None


class FakeChatMember:
    """Fake ChatMember model for testing."""

    def __init__(self, chat_id, user_id, metadata_=None):
        self.chat_id = chat_id
        self.user_id = user_id
        self.metadata_ = metadata_ or {}
        self.left_at = None
        self.created_at = None


class FakeResult:
    """Smart fake result that can return configured data."""

    def __init__(self, data=None):
        self._data = data

    def __await__(self):
        async def _return_self():
            return self

        return _return_self().__await__()

    def scalar_one_or_none(self):
        if self._data is None:
            return None
        if isinstance(self._data, list):
            return self._data[0] if self._data else None
        return self._data

    def scalars(self):
        return self

    def all(self):
        if self._data is None:
            return []
        if isinstance(self._data, list):
            return self._data
        return [self._data]

    def fetchall(self):
        if self._data is None:
            return []
        if isinstance(self._data, list):
            return [(item,) if not isinstance(item, tuple) else item for item in self._data]
        return [(self._data,)]


class AwaitableNone:
    def __await__(self):
        async def _return_none():
            return None

        return _return_none().__await__()


class FakeSession:
    """
    Smart fake session that stores data in memory and supports
    ConfigRepository and ChatsRepository operations.
    """

    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.flushed = False
        # Storage for different models
        self._bot_configs = {}  # (chat_id, chat_key) -> FakeBotConfig
        self._bot_users = {}  # user_id -> FakeBotUsers
        self._chats = {}  # chat_id -> FakeChat
        self._chat_members = {}  # (chat_id, user_id) -> FakeChatMember
        self._pending_adds = []

    def commit(self):
        self.committed = True
        # Process pending adds
        for obj in self._pending_adds:
            self._store_object(obj)
        self._pending_adds.clear()
        return AwaitableNone()

    def rollback(self):
        self.rolled_back = True
        self._pending_adds.clear()
        return AwaitableNone()

    def flush(self):
        self.flushed = True
        # Process pending adds on flush too
        for obj in self._pending_adds:
            self._store_object(obj)
        self._pending_adds.clear()
        return AwaitableNone()

    def close(self):
        pass

    def add(self, obj):
        # Store immediately for simplicity (auto-flush behavior)
        self._store_object(obj)

    def delete(self, obj):
        # Remove object from storage
        if isinstance(obj, FakeBotConfig):
            key = (obj.chat_id, obj.chat_key)
            self._bot_configs.pop(key, None)
        elif isinstance(obj, FakeBotUsers):
            self._bot_users.pop(obj.user_id, None)

    def _store_object(self, obj):
        """Store object in appropriate internal storage."""
        if isinstance(obj, FakeBotConfig):
            key = (obj.chat_id, obj.chat_key)
            self._bot_configs[key] = obj
        elif isinstance(obj, FakeBotUsers):
            self._bot_users[obj.user_id] = obj
        elif isinstance(obj, FakeChat):
            self._chats[obj.chat_id] = obj
        elif isinstance(obj, FakeChatMember):
            key = (obj.chat_id, obj.user_id)
            self._chat_members[key] = obj
        # Handle real SQLAlchemy models by duck-typing
        elif hasattr(obj, "__tablename__"):
            table = obj.__tablename__
            if table == "bot_config":
                fake = FakeBotConfig(obj.chat_id, obj.chat_key, obj.chat_value, getattr(obj, "chat_key_name", None))
                self._bot_configs[(obj.chat_id, obj.chat_key)] = fake
            elif table == "bot_users":
                fake = FakeBotUsers(obj.user_id, obj.user_name, obj.user_type)
                self._bot_users[obj.user_id] = fake
            elif table == "chats":
                fake = FakeChat(obj.chat_id, getattr(obj, "admins", []), getattr(obj, "metadata_", {}))
                self._chats[obj.chat_id] = fake
            elif table == "chat_members":
                fake = FakeChatMember(obj.chat_id, obj.user_id, getattr(obj, "metadata_", {}))
                self._chat_members[(obj.chat_id, obj.user_id)] = fake

    def execute(self, statement, *args, **kwargs):
        """Parse statement and return appropriate data."""
        # Convert statement to string for analysis
        stmt_str = str(statement)

        # Extract bound parameters from SQLAlchemy statement
        params = self._extract_bound_params(statement)

        # Handle DELETE statements
        if "DELETE" in stmt_str.upper():
            if "bot_config" in stmt_str.lower():
                chat_id = params.get("chat_id")
                chat_key = params.get("chat_key")
                if chat_id is not None and chat_key is not None:
                    self._bot_configs.pop((chat_id, chat_key), None)
            return FakeResult(None)

        # Handle SELECT on BotConfig
        if "bot_config" in stmt_str.lower():
            return self._handle_bot_config_query(statement, stmt_str, params)

        # Handle SELECT on BotUsers
        if "bot_users" in stmt_str.lower():
            return self._handle_bot_users_query(statement, stmt_str, params)

        # Handle SELECT on chats
        if "chats" in stmt_str.lower() and "chat_members" not in stmt_str.lower():
            return self._handle_chats_query(statement, stmt_str, params)

        # Handle SELECT on chat_members
        if "chat_members" in stmt_str.lower():
            return self._handle_chat_members_query(statement, stmt_str, params)

        return FakeResult(None)

    def _extract_bound_params(self, statement):
        """Extract bound parameters from SQLAlchemy statement."""
        params = {}
        try:
            # Try to compile the statement and get parameters
            if hasattr(statement, "compile"):
                compiled = statement.compile()
                if hasattr(compiled, "params"):
                    params = dict(compiled.params)
        except Exception:
            pass

        # Also try to extract from whereclause directly
        if hasattr(statement, "whereclause") and statement.whereclause is not None:
            self._extract_params_from_clause(statement.whereclause, params)

        return params

    def _extract_params_from_clause(self, clause, params):
        """Recursively extract parameters from SQLAlchemy clause."""
        try:
            # Handle BinaryExpression (e.g., column == value)
            if hasattr(clause, "left") and hasattr(clause, "right"):
                left = clause.left
                right = clause.right

                # Get column name
                col_name = None
                if hasattr(left, "key"):
                    col_name = left.key
                elif hasattr(left, "name"):
                    col_name = left.name

                # Get value
                if col_name:
                    if hasattr(right, "value"):
                        params[col_name] = right.value
                    elif hasattr(right, "effective_value"):
                        params[col_name] = right.effective_value

            # Handle AND clauses
            if hasattr(clause, "clauses"):
                for sub_clause in clause.clauses:
                    self._extract_params_from_clause(sub_clause, params)
        except Exception:
            pass

    def _handle_bot_config_query(self, statement, stmt_str, params):
        """Handle queries to bot_config table."""
        chat_id = params.get("chat_id")
        chat_key = params.get("chat_key")

        if chat_id is not None and chat_key is not None:
            # Specific lookup
            key = (chat_id, chat_key)
            config = self._bot_configs.get(key)
            return FakeResult(config)
        elif chat_key is not None:
            # Get all configs with this key
            configs = [c for (cid, ck), c in self._bot_configs.items() if ck == chat_key]
            return FakeResult(configs)

        return FakeResult(None)

    def _handle_bot_users_query(self, statement, stmt_str, params):
        """Handle queries to bot_users table."""
        user_id = params.get("user_id")
        user_name = params.get("user_name")
        if user_id is not None:
            user = self._bot_users.get(user_id)
            return FakeResult(user)
        if user_name is not None:
            # Lookup by username (used by ChatsRepository.get_user_id)
            # Returns user_id scalar, not the full object
            for u in self._bot_users.values():
                if u.user_name == user_name:
                    return FakeResult(u.user_id)
            return FakeResult(None)
        return FakeResult(list(self._bot_users.values()))

    def _handle_chats_query(self, statement, stmt_str, params):
        """Handle queries to chats table."""
        chat_id = params.get("chat_id")
        if chat_id is not None:
            chat = self._chats.get(chat_id)
            return FakeResult(chat)
        return FakeResult(list(self._chats.values()))

    def _handle_chat_members_query(self, statement, stmt_str, params):
        """Handle queries to chat_members table."""
        chat_id = params.get("chat_id")
        user_id = params.get("user_id")

        if chat_id is not None and user_id is not None:
            member = self._chat_members.get((chat_id, user_id))
            return FakeResult(member)
        elif chat_id is not None:
            members = [m for (cid, uid), m in self._chat_members.items() if cid == chat_id]
            return FakeResult(members)
        return FakeResult(None)

    def query(self, *args, **kwargs):
        return FakeQuery()

    # Helper methods for tests to set up data
    def set_bot_config(self, chat_id, chat_key, chat_value):
        """Helper for tests to set config values."""
        from enum import Enum

        if isinstance(chat_key, Enum):
            chat_key = chat_key.value
        self._bot_configs[(chat_id, chat_key)] = FakeBotConfig(chat_id, chat_key, chat_value)

    def set_user(self, user_id, user_type=0, user_name=None):
        """Helper for tests to set user data."""
        self._bot_users[user_id] = FakeBotUsers(user_id, user_name, user_type)

    def get_bot_config(self, chat_id, chat_key):
        """Helper for tests to verify config values."""
        from enum import Enum

        if isinstance(chat_key, Enum):
            chat_key = chat_key.value
        config = self._bot_configs.get((chat_id, chat_key))
        return config.chat_value if config else None


class FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def filter_by(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def all(self):
        return []


class FakeWebResponse:
    def __init__(self, data):
        self.data = data


class FakeMongoConfig:
    def __init__(self):
        self._values = {}
        self.save_bot_value = FakeAsyncMethod(side_effect=self._save_bot_value)
        self.load_bot_value = FakeAsyncMethod(side_effect=self._load_bot_value)
        self.get_chat_dict_by_key = FakeAsyncMethod(return_value={})
        self.get_chat_ids_by_key = FakeAsyncMethod(return_value=[])
        self.add_user_to_chat = FakeAsyncMethod(return_value=True)
        self.remove_user_from_chat = FakeAsyncMethod(return_value=True)

    async def _save_bot_value(self, key, bot_value_type, value):
        self._values[(key, bot_value_type)] = value
        return True

    async def _load_bot_value(self, key, bot_value_type, default=None):
        return self._values.get((key, bot_value_type), default)


class FakeLocalizationService:
    def get_text(self, user_id, key, params=()):
        return key


class TestUtilsService:
    def __init__(self):
        self.sleep_and_delete_calls = []
        self.multi_reply_calls = []
        self.multi_answer_calls = []
        self.answer_text_file_calls = []
        self._admin_service = None  # Will be set by TestAppContext

    def set_admin_service(self, admin_service):
        """Set the admin service reference for is_skynet_admin checks."""
        self._admin_service = admin_service

    async def sleep_and_delete(self, message, seconds=None):
        self.sleep_and_delete_calls.append((message, seconds))
        with suppress(Exception):
            await message.delete()

    async def multi_reply(self, message, text):
        self.multi_reply_calls.append((message, text))
        return await multi_reply(message, text)

    async def multi_answer(self, message, text):
        self.multi_answer_calls.append((message, text))
        return await multi_answer(message, text)

    async def answer_text_file(self, message, text, filename=None):
        self.answer_text_file_calls.append((message, text, filename))
        return await answer_text_file(message, text, filename=filename)

    ## async def is_admin(self, message, chat_id=None):
    ##     return await is_admin(message, chat_id=chat_id)
    ##
    ## def is_skynet_admin(self, message, app_context=None):
    ##     # Use admin_service for is_skynet_admin checks
    ##     if self._admin_service:
    ##         username = message.from_user.username if message.from_user else None
    ##         return self._admin_service.is_skynet_admin(username)
    ##     return False

    def add_text(self, lines, num_line, text):
        return add_text(lines, num_line, text)


class FakeMessageThreadCacheService:
    def __init__(self):
        self._messages = {}
        self.remember_calls = []
        self.get_calls = []

    async def remember_message_context(
        self,
        chat_id: int,
        message_id: int,
        thread_id: int,
        user_id: int | None = None,
        username: str | None = None,
        full_name: str | None = None,
        sender_chat_id: int | None = None,
        sender_chat_title: str | None = None,
    ) -> None:
        self.remember_calls.append(
            (chat_id, message_id, thread_id, user_id, username, full_name, sender_chat_id, sender_chat_title)
        )
        self._messages[(chat_id, message_id)] = {
            "thread_id": thread_id,
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "sender_chat_id": sender_chat_id,
            "sender_chat_title": sender_chat_title,
        }

    async def get_message_context(self, chat_id: int, message_id: int) -> dict | None:
        self.get_calls.append((chat_id, message_id))
        return self._messages.get((chat_id, message_id))


class FakeConfigService:
    def __init__(self):
        self._bot_values = {}
        self._chat_dict = {}
        self._chat_lists = {}
        self._no_first_link = set()
        self._full_data = set()
        self._user_status = {}
        # In-memory caches for DI service interface
        self._welcome_messages = {}
        self._welcome_buttons = {}
        self._delete_income = {}
        # Async methods for legacy interface
        self.save_bot_value = FakeAsyncMethod(side_effect=self._save_bot_value)
        self.load_bot_value = FakeAsyncMethod(side_effect=self._load_bot_value)
        self.get_chat_dict_by_key = FakeAsyncMethod(side_effect=self._get_chat_dict_by_key)
        self.get_chat_ids_by_key = FakeAsyncMethod(side_effect=self._get_chat_ids_by_key)
        self.add_user_to_chat = FakeAsyncMethod(side_effect=self._add_user_to_chat)
        self.remove_user_from_chat = FakeAsyncMethod(side_effect=self._remove_user_from_chat)

    async def _save_bot_value(self, key, bot_value_type, value):
        self._bot_values[(key, bot_value_type)] = value
        return True

    async def _load_bot_value(self, key, bot_value_type, default=None):
        return self._bot_values.get((key, bot_value_type), default)

    async def _get_chat_dict_by_key(self, key, is_int=False):
        data = self._chat_dict.get(key, {})
        if is_int:
            return {int(k): v for k, v in data.items()}
        return data

    async def _get_chat_ids_by_key(self, key):
        return list(self._chat_lists.get(key, []))

    async def _add_user_to_chat(self, chat_id, member):
        # member can be a GroupMember object or just a user_id
        user_id = getattr(member, "user_id", member) if hasattr(member, "user_id") else member
        self._chat_lists.setdefault(chat_id, set()).add(user_id)
        return True

    async def _remove_user_from_chat(self, chat_id, user_id):
        if chat_id in self._chat_lists:
            self._chat_lists[chat_id].discard(user_id)
        return True

    def check_user(self, user_id):
        return self._user_status.get(user_id, 0)

    def set_user_status(self, user_id, status):
        self._user_status[user_id] = status

    def is_no_first_link(self, chat_id):
        return chat_id in self._no_first_link

    def add_no_first_link(self, chat_id):
        self._no_first_link.add(chat_id)

    def remove_no_first_link(self, chat_id):
        self._no_first_link.discard(chat_id)

    def is_full_data(self, chat_id):
        return chat_id in self._full_data

    def set_full_data(self, chat_id, enabled=True):
        if enabled:
            self._full_data.add(chat_id)
        else:
            self._full_data.discard(chat_id)

    # DI service interface methods (synchronous)
    def get_welcome_message(self, chat_id):
        return self._welcome_messages.get(chat_id)

    def set_welcome_message(self, chat_id, message, session=None):
        self._welcome_messages[chat_id] = message

    def remove_welcome_message(self, chat_id, session=None):
        self._welcome_messages.pop(chat_id, None)

    def get_welcome_button(self, chat_id):
        return self._welcome_buttons.get(chat_id)

    def set_welcome_button(self, chat_id, button, session=None):
        self._welcome_buttons[chat_id] = button

    def remove_welcome_button(self, chat_id, session=None):
        self._welcome_buttons.pop(chat_id, None)

    def get_delete_income(self, chat_id):
        return self._delete_income.get(chat_id)

    def set_delete_income(self, chat_id, config, session=None):
        self._delete_income[chat_id] = config

    def remove_delete_income(self, chat_id, session=None):
        self._delete_income.pop(chat_id, None)

    def load_value(self, chat_id, key, default=None):
        """Synchronous load_value for DI service interface."""
        return self._bot_values.get((chat_id, key), default)


class FakeAIService:
    def __init__(self):
        self.talk = FakeAsyncMethod(return_value="")
        self.generate_image = FakeAsyncMethod(return_value=[])
        self.talk_get_comment = FakeAsyncMethod(return_value="")
        self.add_task_to_google = FakeAsyncMethod(return_value="")
        self._horoscope = ["*Овен*: Сегодня отличный день!"]

    def get_horoscope(self):
        return self._horoscope

    def set_horoscope(self, horoscope: list):
        self._horoscope = horoscope


class FakeTalkService:
    def __init__(self):
        self.answer_notify_message = FakeAsyncMethod(return_value=None)
        self.remind = FakeAsyncMethod(return_value=None)


class FakeAntispamService:
    def __init__(self):
        self.check_spam = FakeAsyncMethod(return_value=False)
        self.combo_check_spammer = FakeAsyncMethod(return_value=False)
        self.lols_check_spammer = FakeAsyncMethod(return_value=False)
        self.delete_and_log_spam = FakeAsyncMethod(return_value=True)
        self.set_vote = FakeAsyncMethod(return_value=True)


class FakePollServiceMethod:
    """Wrapper to track method calls with .called property and optional return_value override."""

    def __init__(self, impl):
        self._impl = impl
        self._calls = []
        self._return_value = None
        self._has_return_value = False

    async def __call__(self, *args, **kwargs):
        self._calls.append((args, kwargs))
        if self._has_return_value:
            return self._return_value
        return self._impl(*args, **kwargs)

    @property
    def called(self):
        return len(self._calls) > 0

    @property
    def call_count(self):
        return len(self._calls)

    @property
    def call_args(self):
        return self._calls[-1] if self._calls else None

    @property
    def return_value(self):
        return self._return_value

    @return_value.setter
    def return_value(self, value):
        self._return_value = value
        self._has_return_value = True


class FakePollService:
    def __init__(self):
        self._polls = {}
        self._mtla_polls = {}
        # Wrap methods with call tracking
        self.save_poll = FakePollServiceMethod(self._save_poll)
        self.load_poll = FakePollServiceMethod(self._load_poll)
        self.save_mtla_poll = FakePollServiceMethod(self._save_mtla_poll)
        self.load_mtla_poll = FakePollServiceMethod(self._load_mtla_poll)

    def _save_poll(self, session, chat_id, message_id, poll_data):
        self._polls[(chat_id, message_id)] = poll_data
        return True

    def _load_poll(self, session, chat_id, message_id):
        return self._polls.get((chat_id, message_id), {})

    def _save_mtla_poll(self, session, poll_id, poll_data):
        self._mtla_polls[poll_id] = poll_data
        return True

    def _load_mtla_poll(self, session, poll_id):
        return self._mtla_polls.get(poll_id, {})


class FakeGSpreadWorksheet:
    """Fake worksheet for gspread tests."""

    def __init__(self, data=None):
        self._data = data or []
        self._updated_ranges = []

    async def get_all_values(self):
        return self._data

    async def update(self, range_name, values):
        self._updated_ranges.append((range_name, values))
        return True


class FakeGSpreadSpreadsheet:
    """Fake spreadsheet for gspread tests."""

    def __init__(self, worksheets=None):
        self._worksheets = worksheets or {"List": FakeGSpreadWorksheet()}

    async def worksheet(self, name):
        return self._worksheets.get(name, FakeGSpreadWorksheet())


class FakeAgcClient:
    """Fake async gspread client."""

    def __init__(self):
        self._spreadsheets = {}

    async def open(self, name):
        if name not in self._spreadsheets:
            self._spreadsheets[name] = FakeGSpreadSpreadsheet()
        return self._spreadsheets[name]

    def set_spreadsheet(self, name, spreadsheet):
        self._spreadsheets[name] = spreadsheet


class FakeGSpreadService:
    def __init__(self):
        self.get_all_mtlap = FakeAsyncMethod(return_value=[])
        self.get_update_mtlap_skynet_row = FakeAsyncMethod(return_value=None)
        self.find_user = FakeAsyncMethod(return_value=[])
        self.check_bim = FakeAsyncMethod(return_value="")
        self.copy_a_table = FakeAsyncMethod(return_value=("", ""))
        self.update_a_table_first = FakeAsyncMethod(return_value=None)
        self.update_a_table_vote = FakeAsyncMethod(return_value=[])
        self.check_vote_table = FakeAsyncMethod(return_value=([], [], set()))
        self.check_credentials = FakeAsyncMethod(return_value=(True, "token refreshed"))
        self._agc_client = FakeAgcClient()
        self.authorize = FakeAsyncMethod(return_value=self._agc_client)


class FakeGristService:
    def __init__(self):
        self.load_table_data = FakeAsyncMethod(return_value=[])
        self.patch_data = FakeAsyncMethod(return_value=None)


class FakeWebService:
    def __init__(self):
        self.get = FakeAsyncMethod(return_value=FakeWebResponse(data={}))


class FakeMtlService:
    def __init__(self):
        self.check_consul_mtla_chats = FakeAsyncMethod(return_value=[])


class FakeStellarService:
    @property
    def addresses(self):
        from shared.domain.stellar_addresses import MTLAddresses

        return MTLAddresses

    @property
    def assets(self):
        from other.stellar.constants import MTLAssets

        return MTLAssets

    def __init__(self):
        self.check_fee = FakeAsyncMethod(return_value="")
        self.decode_xdr = FakeAsyncMethod(return_value=[])
        self.show_bim = FakeAsyncMethod(return_value="")
        self.get_balances = FakeAsyncMethod(return_value={})
        self.send_payment_async = FakeAsyncMethod(return_value={})
        self.sign = FakeSyncMethod(return_value="")
        self.build_swap_xdr = FakeAsyncMethod(return_value="")
        self.async_submit = FakeAsyncMethod(return_value=None)
        self.find_public_key = FakeSyncMethod(return_value=None)
        self.check_mtlap = FakeAsyncMethod(return_value="")
        self.get_mtlap_votes = FakeAsyncMethod(return_value={})
        self.stop_all_exchange = FakeAsyncMethod(return_value=None)
        self.address_id_to_username = FakeAsyncMethod(return_value="@user")
        self.check_url_xdr = FakeAsyncMethod(return_value=["Decoded XDR info"])
        self.get_cash_balance = FakeAsyncMethod(return_value="Balance: 100 EURMTL")
        self.create_list = FakeSyncMethod(return_value=1)
        self.calc_bim_pays = FakeAsyncMethod(return_value=[("addr1", 10), ("addr2", 20)])
        self.gen_xdr = FakeSyncMethod(return_value=0)
        self.send_by_list_id = FakeAsyncMethod(return_value=0)
        self.calc_divs = FakeAsyncMethod(return_value=[("addr1", 10)])
        self.calc_sats_divs = FakeAsyncMethod(return_value=[("addr1", 10)])
        self.calc_usdm_divs = FakeAsyncMethod(return_value=[("addr1", 10)])
        self.calc_usdm_daily = FakeAsyncMethod(return_value=[("addr1", 10)])
        self.calc_usdm_usdm_divs = FakeAsyncMethod(return_value=[["GCLQ...", 1000.0, 5.97, 5.97, 0]])
        self.get_new_vote_all_mtl = FakeAsyncMethod(return_value=["vote_xdr_here"])
        self.get_btcmtl_xdr = FakeAsyncMethod(return_value="btcmtl_xdr")
        self.get_damircoin_xdr = FakeAsyncMethod(return_value="damircoin_xdr")
        self.get_agora_xdr = FakeAsyncMethod(return_value="agora_xdr")
        self.get_chicago_xdr = FakeAsyncMethod(return_value=["Chicago", "info", "chicago_xdr"])
        self.get_toc_xdr = FakeAsyncMethod(return_value="toc_xdr")
        self.show_data = FakeAsyncMethod(return_value=["Data 1", "Data 2"])


class FakeAirdropService:
    def __init__(self):
        self.check_records = FakeAsyncMethod(return_value=[])
        self.load_configs = FakeAsyncMethod(return_value=[])
        self.log_payment = FakeAsyncMethod(return_value=None)


class FakeReportService:
    def __init__(self):
        self.update_airdrop = FakeAsyncMethod(return_value=None)
        self.update_mmwb_report = FakeAsyncMethod(return_value=None)
        self.update_bim_data = FakeAsyncMethod(return_value=None)
        self.update_guarantors_report = FakeAsyncMethod(return_value=None)
        self.update_main_report = FakeAsyncMethod(return_value=None)
        self.update_donate_report = FakeAsyncMethod(return_value=None)
        self.update_fest = FakeAsyncMethod(return_value=None)


class FakeModerationService:
    def __init__(self):
        self.ban_user = FakeAsyncMethod(side_effect=self._ban_user)
        self.unban_user = FakeAsyncMethod(side_effect=self._unban_user)
        self._user_status = {}
        self._user_ids = {}

    async def _ban_user(self, session, chat_id, user_id, bot, revoke_messages=True):
        from shared.domain.user import SpamStatus

        await bot.ban_chat_member(chat_id, user_id, revoke_messages=revoke_messages)
        self._user_status[user_id] = SpamStatus.BAD
        return True

    async def _unban_user(self, session, chat_id, user_id, bot):
        from shared.domain.user import SpamStatus

        await bot.unban_chat_member(chat_id, user_id)
        self._user_status[user_id] = SpamStatus.NEW
        return True

    def check_user_status(self, session, user_id):
        from shared.domain.user import SpamStatus

        return self._user_status.get(user_id, SpamStatus.NEW)

    def get_user_id(self, session, username):
        if isinstance(username, str):
            if username.isdigit() or (username.startswith("-") and username[1:].isdigit()):
                return int(username)
            if username.startswith("@"):
                return self._user_ids.get(username[1:], 0)
        return self._user_ids.get(username, 0)

    def set_user_id(self, username, user_id):
        self._user_ids[username] = user_id


class FakeGroupService:
    def __init__(self):
        self.get_members = FakeAsyncMethod(return_value=[])
        self.check_membership = FakeAsyncMethod(return_value=True)
        self.enforce_entry_channel = FakeAsyncMethod(return_value=(True, None))
        self.ping_piro = FakeAsyncMethod(return_value=None)


class FakeAirdropConfigItem:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeFeatureFlagsService:
    """Fake implementation of FeatureFlagsService for testing."""

    FEATURE_KEYS = [
        "captcha",
        "moderate",
        "no_first_link",
        "reply_only",
        "listen",
        "auto_all",
        "save_last_message_date",
        "join_request_captcha",
        "full_data",
        "first_vote",
        "need_decode",
        "delete_income",
        "entry_channel",
        "notify_join",
        "notify_message",
        "selfmod",
    ]

    def __init__(self):
        self._features = {}  # chat_id -> {feature -> bool}

    def is_enabled(self, chat_id, feature):
        if feature not in self.FEATURE_KEYS:
            return False
        return self._features.get(chat_id, {}).get(feature, False)

    def enable(self, chat_id, feature):
        return self.set_feature(chat_id, feature, True)

    def disable(self, chat_id, feature):
        return self.set_feature(chat_id, feature, False)

    def set_feature(self, chat_id, feature, enabled, persist=True):
        if feature not in self.FEATURE_KEYS:
            return False
        if chat_id not in self._features:
            self._features[chat_id] = {}
        self._features[chat_id][feature] = enabled
        return True

    def toggle(self, chat_id, feature):
        current = self.is_enabled(chat_id, feature)
        self.set_feature(chat_id, feature, not current)
        return not current

    def get_chats_with_feature(self, feature):
        """Get all chat IDs with feature enabled."""
        if feature not in self.FEATURE_KEYS:
            return []
        return [chat_id for chat_id, features in self._features.items() if features.get(feature, False)]

    def get_feature_list(self, feature):
        """Alias for get_chats_with_feature."""
        return self.get_chats_with_feature(feature)

    def is_listening(self, chat_id):
        return self.is_enabled(chat_id, "listen")

    def is_captcha_enabled(self, chat_id):
        return self.is_enabled(chat_id, "captcha")

    def is_moderation_enabled(self, chat_id):
        return self.is_enabled(chat_id, "moderate")

    def is_no_first_link(self, chat_id):
        return self.is_enabled(chat_id, "no_first_link")

    def is_reply_only(self, chat_id):
        return self.is_enabled(chat_id, "reply_only")

    def is_full_data(self, chat_id):
        return self.is_enabled(chat_id, "full_data")


class FakeVotingService:
    """Fake implementation of VotingService for testing."""

    def __init__(self):
        self._vote_weights = {}  # address -> {user: weight, "NEED": {...}}
        self._first_vote = []
        self._first_vote_data = {}
        self._poll_votes = {}

    # Vote weights methods (for weighted polls)
    def get_vote_weights(self, address):
        data = self._vote_weights.get(address)
        return data.copy() if data else None

    def get_all_vote_weights(self):
        return {k: v.copy() for k, v in self._vote_weights.items()}

    def set_vote_weights(self, address, weights):
        self._vote_weights[address] = weights.copy()

    def set_all_vote_weights(self, vote_weights):
        self._vote_weights = {k: v.copy() if isinstance(v, dict) else v for k, v in vote_weights.items()}

    def get_user_vote_weight(self, address, user):
        weights = self._vote_weights.get(address, {})
        return weights.get(user) or weights.get(str(user))

    # First vote methods
    def is_first_vote_enabled(self, chat_id):
        return chat_id in self._first_vote

    def enable_first_vote(self, chat_id):
        if chat_id not in self._first_vote:
            self._first_vote.append(chat_id)

    def disable_first_vote(self, chat_id):
        if chat_id in self._first_vote:
            self._first_vote.remove(chat_id)

    def get_first_vote_chats(self):
        return self._first_vote.copy()

    def get_first_vote_data(self, chat_id):
        return self._first_vote_data.get(chat_id, {}).copy()

    def set_first_vote_data(self, chat_id, data):
        self._first_vote_data[chat_id] = data.copy()

    def record_first_vote(self, chat_id, user_id, choice):
        if chat_id not in self._first_vote_data:
            self._first_vote_data[chat_id] = {}
        self._first_vote_data[chat_id][user_id] = choice

    def has_user_voted(self, chat_id, user_id):
        return user_id in self._first_vote_data.get(chat_id, {})

    def clear_first_vote_data(self, chat_id):
        self._first_vote_data.pop(chat_id, None)

    # Key-based first vote data methods (for message-specific voting)
    def get_first_vote_data_by_key(self, key, default=None):
        """Get first vote data by string key (e.g., '{message_id}{chat_id}')."""
        data = self._first_vote_data.get(key)
        if data is not None:
            return data.copy()
        return default.copy() if default else {}

    def set_first_vote_data_by_key(self, key, data):
        """Set first vote data by string key."""
        self._first_vote_data[key] = data.copy()


class FakeNotificationService:
    """Fake NotificationService for testing."""

    def __init__(self):
        self._notify_join: dict = {}
        self._notify_message: dict = {}
        self._alert_me: dict = {}  # chat_id -> list of user_ids

    def is_join_notify_enabled(self, chat_id: int) -> bool:
        return bool(self._notify_join.get(chat_id))

    def get_join_notify_config(self, chat_id: int):
        return self._notify_join.get(chat_id)

    def set_join_notify(self, chat_id: int, config) -> None:
        self._notify_join[chat_id] = config

    def disable_join_notify(self, chat_id: int) -> None:
        self._notify_join.pop(chat_id, None)

    def is_message_notify_enabled(self, chat_id: int) -> bool:
        return bool(self._notify_message.get(chat_id))

    def get_message_notify_config(self, chat_id: int):
        return self._notify_message.get(chat_id)

    def set_message_notify(self, chat_id: int, config) -> None:
        self._notify_message[chat_id] = config

    def disable_message_notify(self, chat_id: int) -> None:
        self._notify_message.pop(chat_id, None)

    def get_all_message_notify(self) -> dict:
        return self._notify_message.copy()

    # Alert me methods (per-chat user alert subscriptions)
    def get_alert_users(self, chat_id: int) -> list:
        """Get list of user_ids subscribed to alerts in this chat."""
        return self._alert_me.get(chat_id, []).copy()

    def is_user_subscribed(self, chat_id: int, user_id: int) -> bool:
        """Check if user is subscribed to alerts in this chat."""
        return user_id in self._alert_me.get(chat_id, [])

    def add_alert_user(self, chat_id: int, user_id: int) -> None:
        """Subscribe user to alerts in this chat."""
        if chat_id not in self._alert_me:
            self._alert_me[chat_id] = []
        if user_id not in self._alert_me[chat_id]:
            self._alert_me[chat_id].append(user_id)

    def remove_alert_user(self, chat_id: int, user_id: int) -> None:
        """Unsubscribe user from alerts in this chat."""
        if chat_id in self._alert_me and user_id in self._alert_me[chat_id]:
            self._alert_me[chat_id].remove(user_id)

    def toggle_alert_user(self, chat_id: int, user_id: int) -> bool:
        """Toggle user's alert subscription. Returns True if now subscribed, False if unsubscribed."""
        if chat_id not in self._alert_me:
            self._alert_me[chat_id] = []
        if user_id in self._alert_me[chat_id]:
            self._alert_me[chat_id].remove(user_id)
            return False
        else:
            self._alert_me[chat_id].append(user_id)
            return True

    def get_all_alerts(self) -> dict:
        """Get all alert subscriptions for persistence."""
        return {k: v.copy() for k, v in self._alert_me.items()}

    def load_alert_me(self, data: dict) -> None:
        self._alert_me = data.copy()


class FakeLock:
    """Fake lock for testing (context manager that does nothing)."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakeAdminService:
    """Fake AdminManagementService for testing."""

    def __init__(self):
        self._skynet_admins: list[str] = []
        self._skynet_img: list[str] = []
        self._chat_admins: dict[int, list[int]] = {}
        self._topic_admins: dict[str, list[str]] = {}  # "chat_id-thread_id" -> [usernames with @]
        self._topic_mute: dict[str, dict] = {}  # "chat_id-thread_id" -> {user_id: {"end_time": str, "user": str}}
        self._lock = FakeLock()
        self._admins = self._chat_admins  # Alias for compatibility with admin_panel.py

    def _topic_key(self, chat_id: int, thread_id: int) -> str:
        return f"{chat_id}-{thread_id}"

    def is_skynet_admin(self, username: str) -> bool:
        if not username:
            return False
        normalized = username if username.startswith("@") else f"@{username}"
        return normalized.lower() in [u.lower() for u in self._skynet_admins]

    def is_skynet_img_user(self, username: str) -> bool:
        if not username:
            return False
        normalized = username if username.startswith("@") else f"@{username}"
        return normalized.lower() in [u.lower() for u in self._skynet_img]

    def set_skynet_admins(self, usernames: list[str]) -> None:
        self._skynet_admins = usernames.copy()

    def set_skynet_img_users(self, usernames: list[str]) -> None:
        self._skynet_img = usernames.copy()

    def add_skynet_admin(self, username: str) -> None:
        normalized = username if username.startswith("@") else f"@{username}"
        if normalized not in self._skynet_admins:
            self._skynet_admins.append(normalized)

    def add_skynet_img_user(self, username: str) -> None:
        normalized = username if username.startswith("@") else f"@{username}"
        if normalized not in self._skynet_img:
            self._skynet_img.append(normalized)

    def set_chat_admins(self, chat_id: int, admin_ids: list[int]) -> None:
        self._chat_admins[chat_id] = admin_ids.copy()

    def get_chat_admins(self, chat_id: int) -> list[int]:
        return self._chat_admins.get(chat_id, []).copy()

    # Chat admin methods
    def is_chat_admin(self, chat_id: int, user_id: int) -> bool:
        return user_id in self._chat_admins.get(chat_id, [])

    def add_chat_admin(self, chat_id: int, user_id: int) -> None:
        if chat_id not in self._chat_admins:
            self._chat_admins[chat_id] = []
        if user_id not in self._chat_admins[chat_id]:
            self._chat_admins[chat_id].append(user_id)

    def remove_chat_admin(self, chat_id: int, user_id: int) -> None:
        if chat_id in self._chat_admins and user_id in self._chat_admins[chat_id]:
            self._chat_admins[chat_id].remove(user_id)

    # Topic admin methods
    def has_topic_admins(self, chat_id: int, thread_id: int) -> bool:
        key = self._topic_key(chat_id, thread_id)
        return key in self._topic_admins

    def has_topic_admins_by_key(self, topic_key: str) -> bool:
        """Check if topic has any admins configured by key string."""
        return topic_key in self._topic_admins

    def is_topic_admin(self, chat_id: int, thread_id: int, username: str) -> bool:
        if not username:
            return False
        key = self._topic_key(chat_id, thread_id)
        normalized = username.lower() if username.startswith("@") else f"@{username.lower()}"
        return normalized in self._topic_admins.get(key, [])

    def is_topic_admin_by_key(self, topic_key: str, username: str) -> bool:
        """Check if username is topic admin using pre-computed key."""
        if not username:
            return False
        normalized = username.lower() if username.startswith("@") else f"@{username.lower()}"
        return normalized in self._topic_admins.get(topic_key, [])

    def get_topic_admins(self, chat_id: int, thread_id: int) -> list[str]:
        key = self._topic_key(chat_id, thread_id)
        return self._topic_admins.get(key, []).copy()

    def set_topic_admins(self, chat_id: int, thread_id: int, admin_usernames: list[str]) -> None:
        key = self._topic_key(chat_id, thread_id)
        self._topic_admins[key] = admin_usernames.copy()

    def add_topic_admin(self, chat_id: int, thread_id: int, username: str) -> None:
        normalized = username.lower() if username.startswith("@") else f"@{username.lower()}"
        key = self._topic_key(chat_id, thread_id)
        if key not in self._topic_admins:
            self._topic_admins[key] = []
        if normalized not in self._topic_admins[key]:
            self._topic_admins[key].append(normalized)

    def get_all_topic_admins(self) -> dict:
        return {k: v.copy() for k, v in self._topic_admins.items()}

    # Topic mute methods
    def get_topic_mutes(self, chat_id: int, thread_id: int) -> dict:
        key = self._topic_key(chat_id, thread_id)
        mutes = self._topic_mute.get(key, {})
        return {k: v.copy() for k, v in mutes.items()}

    def get_topic_mutes_by_key(self, topic_key: str) -> dict:
        """Get all mutes for a topic by key. Returns {user_id: {"end_time": str, "user": str}}."""
        mutes = self._topic_mute.get(topic_key, {})
        return {k: v.copy() for k, v in mutes.items()}

    def has_topic_mutes(self, chat_id: int, thread_id: int) -> bool:
        key = self._topic_key(chat_id, thread_id)
        return bool(self._topic_mute.get(key))

    def has_topic_mutes_by_key(self, topic_key: str) -> bool:
        """Check if topic has any mutes by key."""
        return bool(self._topic_mute.get(topic_key))

    def get_user_mute(self, chat_id: int, thread_id: int, user_id: int):
        key = self._topic_key(chat_id, thread_id)
        mute_info = self._topic_mute.get(key, {}).get(user_id)
        return mute_info.copy() if mute_info else None

    def is_user_muted(self, chat_id: int, thread_id: int, user_id: int) -> bool:
        key = self._topic_key(chat_id, thread_id)
        return user_id in self._topic_mute.get(key, {})

    def set_user_mute(self, chat_id: int, thread_id: int, user_id: int, end_time: str, user_display: str) -> None:
        key = self._topic_key(chat_id, thread_id)
        if key not in self._topic_mute:
            self._topic_mute[key] = {}
        self._topic_mute[key][user_id] = {"end_time": end_time, "user": user_display}

    def set_user_mute_by_key(self, topic_key: str, user_id: int, end_time: str, user_display: str) -> None:
        """Set mute for a user in a topic by key."""
        if topic_key not in self._topic_mute:
            self._topic_mute[topic_key] = {}
        self._topic_mute[topic_key][user_id] = {"end_time": end_time, "user": user_display}

    def remove_user_mute(self, chat_id: int, thread_id: int, user_id: int) -> None:
        key = self._topic_key(chat_id, thread_id)
        if key in self._topic_mute and user_id in self._topic_mute[key]:
            del self._topic_mute[key][user_id]

    def remove_user_mute_by_key(self, topic_key: str, user_id: int) -> None:
        """Remove mute for a user in a topic by key."""
        if topic_key in self._topic_mute and user_id in self._topic_mute[topic_key]:
            del self._topic_mute[topic_key][user_id]

    def get_all_topic_mutes(self) -> dict:
        return {k: {uk: uv.copy() for uk, uv in v.items()} for k, v in self._topic_mute.items()}

    def load_topic_mutes(self, data: dict) -> None:
        self._topic_mute = {}
        for key, mutes in data.items():
            self._topic_mute[key] = {}
            for user_id, mute_info in mutes.items():
                uid = int(user_id) if isinstance(user_id, str) else user_id
                self._topic_mute[key][uid] = mute_info.copy()

    # Skynet admin getter methods
    def get_skynet_admins(self) -> list[str]:
        return self._skynet_admins.copy()

    def get_skynet_img_users(self) -> list[str]:
        return self._skynet_img.copy()

    # Bulk loading methods
    def load_admins(self, admins_data: dict) -> None:
        self._chat_admins = {k: v.copy() for k, v in admins_data.items()}

    def load_topic_admins(self, topic_admins_data: dict) -> None:
        self._topic_admins = {k: v.copy() for k, v in topic_admins_data.items()}


class FakeSpamStatusService:
    """Fake implementation of SpamStatusService for testing."""

    def __init__(self):
        from shared.domain.user import SpamStatus

        self._cache: dict = {}  # user_id -> SpamStatus
        self._name_cache: dict = {}
        self.SpamStatus = SpamStatus

    def get_status(self, user_id: int):
        from shared.domain.user import SpamStatus

        return self._cache.get(user_id, SpamStatus.NEW)

    def get_user(self, user_id: int):
        from shared.domain.user import User

        status = self.get_status(user_id)
        return User(user_id=user_id, spam_status=status)

    def set_status(self, user_id: int, status) -> None:
        self._cache[user_id] = status

    def is_good(self, user_id: int) -> bool:
        from shared.domain.user import SpamStatus

        return self.get_status(user_id) == SpamStatus.GOOD

    def is_bad(self, user_id: int) -> bool:
        from shared.domain.user import SpamStatus

        return self.get_status(user_id) == SpamStatus.BAD

    def is_new(self, user_id: int) -> bool:
        from shared.domain.user import SpamStatus

        return self.get_status(user_id) == SpamStatus.NEW

    def mark_good(self, user_id: int) -> None:
        from shared.domain.user import SpamStatus

        self.set_status(user_id, SpamStatus.GOOD)

    def mark_bad(self, user_id: int) -> None:
        from shared.domain.user import SpamStatus

        self.set_status(user_id, SpamStatus.BAD)

    def mark_new(self, user_id: int) -> None:
        from shared.domain.user import SpamStatus

        self.set_status(user_id, SpamStatus.NEW)

    def clear_cache(self) -> None:
        self._cache.clear()

    def invalidate_user(self, user_id: int) -> None:
        self._cache.pop(user_id, None)

    def preload_statuses(self, statuses: dict) -> None:
        from shared.domain.user import SpamStatus

        for user_id, status in statuses.items():
            self._cache[user_id] = SpamStatus(status)

    def get_cached_count(self) -> int:
        return len(self._cache)

    # Name cache methods
    def cache_name(self, key: str, name: str) -> None:
        self._name_cache[key] = name

    def get_cached_name(self, key: str):
        return self._name_cache.get(key)

    def load_name_cache(self, names: dict) -> None:
        self._name_cache = names.copy()

    def get_all_names(self) -> dict:
        return self._name_cache.copy()


class FakeCommandRegistryService:
    """Fake implementation of CommandRegistryService for testing."""

    def __init__(self):
        from services.command_registry_service import CommandInfo

        self._commands: dict = {}
        self._CommandInfo = CommandInfo

    def register_command(
        self,
        name: str,
        description: str = "",
        cmd_type: int = 0,
        cmd_list: list = None,
        hidden: bool = False,
    ) -> None:
        """Register a command with metadata."""
        self._commands[name] = self._CommandInfo(
            name=name,
            description=description,
            cmd_type=cmd_type,
            cmd_list=cmd_list or [],
            hidden=hidden,
        )

    def get_command(self, name: str):
        """Get command info by name."""
        return self._commands.get(name)

    def get_all_commands(self) -> dict:
        """Get all registered commands."""
        return self._commands.copy()

    def get_commands_by_type(self, cmd_type) -> list:
        """Get commands filtered by type."""
        return [cmd for cmd in self._commands.values() if cmd.cmd_type == cmd_type and not cmd.hidden]

    def get_visible_commands(self) -> list:
        """Get all non-hidden commands."""
        return [cmd for cmd in self._commands.values() if not cmd.hidden]

    def unregister_command(self, name: str) -> bool:
        """Unregister a command. Returns True if existed."""
        if name in self._commands:
            del self._commands[name]
            return True
        return False

    def has_command(self, name: str) -> bool:
        """Check if command is registered."""
        return name in self._commands

    def update_command(self, name: str, **kwargs) -> bool:
        """Update existing command fields. Returns True if command exists."""
        if name not in self._commands:
            return False
        cmd = self._commands[name]
        for key, value in kwargs.items():
            if hasattr(cmd, key):
                setattr(cmd, key, value)
        return True

    def load_commands(self, commands_data: dict) -> None:
        """Bulk load commands from dict."""
        self._commands = {}
        for name, data in commands_data.items():
            self._commands[name] = self._CommandInfo(
                name=name,
                description=data.get("description", ""),
                cmd_type=data.get("cmd_type", 0),
                cmd_list=data.get("cmd_list", []),
                hidden=data.get("hidden", False),
            )


class FakeDatabaseService:
    """Fake DatabaseService for testing."""

    def __init__(self):
        self._chats = {}  # chat_id -> ChatDTO
        self._bot_values: dict[tuple[int, object], object] = {}

    async def get_chat_by_id(self, chat_id: int):
        """Get chat from database by ID, returns ChatDTO or None."""
        return self._chats.get(chat_id)

    async def upsert_chat_info(self, chat_id: int, title, username) -> None:
        """Create or update chat with title and username."""
        from db.repositories import ChatDTO

        self._chats[chat_id] = ChatDTO(chat_id=chat_id, title=title, username=username, admins=[])

    def set_chat(self, chat_id: int, title: str, username: str = None):
        """Test helper to set up chat data."""
        from db.repositories import ChatDTO

        self._chats[chat_id] = ChatDTO(chat_id=chat_id, title=title, username=username, admins=[])

    @staticmethod
    def _key(chat_key):
        from enum import Enum

        if isinstance(chat_key, Enum):
            return chat_key.value
        return chat_key

    async def save_bot_value(self, chat_id: int, chat_key, chat_value) -> None:
        key = (chat_id, self._key(chat_key))
        if chat_value is None:
            self._bot_values.pop(key, None)
        else:
            self._bot_values[key] = chat_value

    async def load_bot_value(self, chat_id: int, chat_key, default_value=""):
        return self._bot_values.get((chat_id, self._key(chat_key)), default_value)

    async def save_bot_user(self, user_id: int, username: str | None, user_type: int = 0) -> None:
        return None


class FakeSelfmodService:
    """In-memory Fake of SelfmodService for tests that don't need DB persistence.

    Mirrors the real service's surface used by routers; not a full reimplementation.
    """

    def __init__(self):
        from services.selfmod_service import VoteState, threshold_passed, mute_duration_for_level  # noqa: F401

        self._VoteState = VoteState
        self._threshold_passed = threshold_passed
        self._votes: dict[tuple[int, int], VoteState] = {}
        self._warnings: dict[int, dict[int, int]] = {}

    async def start_vote(self, kind, chat_id, vote_msg_id, target_user_id, target_mention, target_msg_id=None):
        from datetime import datetime, timezone

        state = self._VoteState(
            kind=kind,
            chat_id=chat_id,
            vote_msg_id=vote_msg_id,
            target_user_id=target_user_id,
            target_mention=target_mention,
            target_msg_id=target_msg_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._votes[(chat_id, vote_msg_id)] = state
        return state

    def get_vote(self, chat_id, vote_msg_id):
        return self._votes.get((chat_id, vote_msg_id))

    def has_active_mute_vote(self, chat_id, target_user_id):
        for (cid, _), st in self._votes.items():
            if cid == chat_id and st.target_user_id == target_user_id and st.kind in ("mute", "kick"):
                return True
        return False

    async def cast(self, chat_id, vote_msg_id, voter_id, voter_mention, choice):
        from services.selfmod_service import VoteResult

        state = self._votes.get((chat_id, vote_msg_id))
        if state is None:
            return None
        if state.has_voted(voter_id):
            return VoteResult(state=state, outcome=None, already_voted=True)
        (state.yes_voters if choice else state.no_voters).append(voter_id)
        state.voter_mentions[str(voter_id)] = voter_mention
        return VoteResult(state=state, outcome=self._threshold_passed(state.yes(), state.no()))

    async def close_vote(self, chat_id, vote_msg_id):
        self._votes.pop((chat_id, vote_msg_id), None)

    async def get_warnings(self, chat_id, user_id):
        return self._warnings.get(chat_id, {}).get(user_id, 0)

    async def add_warning(self, chat_id, user_id):
        bucket = self._warnings.setdefault(chat_id, {})
        bucket[user_id] = bucket.get(user_id, 0) + 1
        return bucket[user_id]

    async def reset_warnings(self, chat_id, user_id):
        if chat_id in self._warnings:
            self._warnings[chat_id].pop(user_id, None)

    async def list_warnings(self, chat_id):
        return dict(self._warnings.get(chat_id, {}))

    # Test helpers
    def set_warning_count(self, chat_id, user_id, count):
        self._warnings.setdefault(chat_id, {})[user_id] = count


class TestAppContext:
    def __init__(self, bot, dispatcher):
        self.bot = bot
        self.dispatcher = dispatcher
        self.session = FakeSession()  # Shared session for repository operations
        self.localization_service = FakeLocalizationService()
        self.utils_service = TestUtilsService()
        self.config_service = FakeConfigService()
        self.ai_service = FakeAIService()
        self.talk_service = FakeTalkService()
        self.antispam_service = FakeAntispamService()
        self.poll_service = FakePollService()
        self.gspread_service = FakeGSpreadService()
        self.grist_service = FakeGristService()
        self.web_service = FakeWebService()
        self.mtl_service = FakeMtlService()
        self.stellar_service = FakeStellarService()
        self.airdrop_service = FakeAirdropService()
        self.report_service = FakeReportService()
        self.moderation_service = FakeModerationService()
        self.group_service = FakeGroupService()
        self.bot_state_service = BotStateService()
        self.feature_flags = FakeFeatureFlagsService()
        self.voting_service = FakeVotingService()
        self.admin_service = FakeAdminService()
        self.notification_service = FakeNotificationService()
        self.spam_status_service = FakeSpamStatusService()
        self.command_registry = FakeCommandRegistryService()
        self.db_service = FakeDatabaseService()
        self.channel_link_service = ChannelLinkService()
        self.selfmod_service = FakeSelfmodService()
        self.message_thread_cache_service = FakeMessageThreadCacheService()
        self.admin_id = 123456
        # Wire admin_service to utils_service
        self.utils_service.set_admin_service(self.admin_service)

    def check_user(self, user_id: int) -> int:
        """Check user status for antispam."""
        return self.spam_status_service.get_status(user_id)


# ============================================================================
# Protocol-compatible fake implementations for clean architecture
# ============================================================================


class FakeStellarSDK:
    """
    Fake implementation of IStellarSDK Protocol for testing.

    Provides test helpers to set up expected responses and verify interactions.
    """

    def __init__(
        self,
        accounts: dict = None,
        balances: dict = None,
        holders: dict = None,
    ):
        self._accounts = accounts or {}
        self._balances = balances or {}
        self._holders = holders or {}
        self._submitted_transactions: list = []

    async def get_account(self, address: str):
        return self._accounts.get(address)

    async def get_balances(self, address: str):
        return self._balances.get(address, {})

    async def get_holders(self, asset, limit: int = 200):
        key = f"{asset.code}:{asset.issuer}"
        return self._holders.get(key, [])[:limit]

    async def submit_transaction(self, xdr: str):
        self._submitted_transactions.append(xdr)
        return {"hash": f"fake_hash_{len(self._submitted_transactions)}"}

    def sign_transaction(self, xdr: str):
        return f"signed_{xdr}"

    # Test helpers
    def set_balance(self, address: str, asset: str, amount):
        from decimal import Decimal

        if address not in self._balances:
            self._balances[address] = {}
        self._balances[address][asset] = Decimal(str(amount))

    def set_holders(self, asset, holders: list):
        key = f"{asset.code}:{asset.issuer}"
        self._holders[key] = holders

    def get_submitted_transactions(self):
        return self._submitted_transactions.copy()


class FakeFinanceRepositoryProtocol:
    """Fake implementation of IFinanceRepository Protocol."""

    def __init__(self):
        self.div_lists = {}
        self.payments = {}
        self.transactions = []
        self.watch_list = []

    def get_div_list(self, list_id: int):
        return self.div_lists.get(list_id)

    def get_payments(self, list_id: int, pack_count: int):
        return self.payments.get(list_id, [])[:pack_count]

    def count_unpacked_payments(self, list_id: int):
        return len(self.payments.get(list_id, []))

    def save_transaction(self, list_id: int, xdr: str):
        self.transactions.append({"list_id": list_id, "xdr": xdr})
        return True

    def get_watch_list(self):
        return self.watch_list.copy()


class FakeConfigRepositoryProtocol:
    """Fake implementation of IConfigRepository Protocol."""

    def __init__(self):
        self.config = {}

    def _normalize_key(self, chat_key):
        """Convert Enum to its value, like real ConfigRepository."""
        from enum import Enum

        if isinstance(chat_key, Enum):
            return chat_key.value
        return chat_key

    def save_bot_value(self, chat_id: int, chat_key, chat_value):
        key = self._normalize_key(chat_key)
        self.config[(chat_id, key)] = chat_value
        return True

    def load_bot_value(self, chat_id: int, chat_key, default_value=None):
        key = self._normalize_key(chat_key)
        return self.config.get((chat_id, key), default_value)

    def get_chat_ids_by_key(self, chat_key):
        key = self._normalize_key(chat_key)
        return [k[0] for k in self.config.keys() if k[1] == key]


class FakeChatsRepositoryProtocol:
    """Fake implementation of IChatsRepository Protocol."""

    def __init__(self):
        self.users = {}
        self.chats = []

    def get_all_chats(self):
        return self.chats.copy()

    def add_user_to_chat(self, chat_id: int, member):
        return True

    def remove_user_from_chat(self, chat_id: int, user_id: int):
        return True

    def get_user_id(self, username: str):
        for uid, user in self.users.items():
            if getattr(user, "username", None) == username:
                return uid
        return None

    def get_user_by_id(self, user_id: int):
        return self.users.get(user_id)

    def save_user_type(self, user_id: int, user_type: int):
        if user_id not in self.users:
            self.users[user_id] = type("User", (), {"user_type": user_type, "user_id": user_id})()
        else:
            self.users[user_id].user_type = user_type
        return True
