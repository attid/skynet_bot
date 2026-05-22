# tests/services/test_config_service.py
"""Tests for ConfigService."""

import pytest
from unittest.mock import Mock

from other.constants import BotValueTypes
from services.config_service import ConfigService
from services.interfaces.repositories import IConfigRepository
from tests.fakes import FakeSession


@pytest.fixture
def mock_repo():
    """Create a mock config repository."""
    repo = Mock(spec=IConfigRepository)
    repo.load_bot_value.return_value = None
    repo.save_bot_value.return_value = True
    repo.get_chat_ids_by_key.return_value = []
    return repo


@pytest.fixture
def service(mock_repo):
    """Create ConfigService with mock repo."""
    return ConfigService(mock_repo)


class TestWelcomeMessages:
    """Tests for welcome message methods."""

    def test_get_welcome_message_returns_none_for_empty(self, service):
        assert service.get_welcome_message(123) is None

    def test_set_and_get_welcome_message(self, service):
        service.set_welcome_message(123, "Hello {name}!")

        assert service.get_welcome_message(123) == "Hello {name}!"

    def test_set_welcome_message_overwrites_existing(self, service):
        service.set_welcome_message(123, "Old message")
        service.set_welcome_message(123, "New message")

        assert service.get_welcome_message(123) == "New message"

    def test_welcome_messages_are_per_chat(self, service):
        service.set_welcome_message(123, "Chat 123 message")
        service.set_welcome_message(456, "Chat 456 message")

        assert service.get_welcome_message(123) == "Chat 123 message"
        assert service.get_welcome_message(456) == "Chat 456 message"

    def test_remove_welcome_message(self, service):
        service.set_welcome_message(123, "Hello!")
        service.remove_welcome_message(123)

        assert service.get_welcome_message(123) is None

    def test_remove_welcome_message_no_error_for_missing(self, service):
        service.remove_welcome_message(999)  # should not raise

    def test_load_welcome_messages_bulk(self, service):
        service.load_welcome_messages(
            {
                123: "Message 1",
                456: "Message 2",
                789: "Message 3",
            }
        )

        assert service.get_welcome_message(123) == "Message 1"
        assert service.get_welcome_message(456) == "Message 2"
        assert service.get_welcome_message(789) == "Message 3"

    def test_load_welcome_messages_merges_with_existing(self, service):
        service.set_welcome_message(123, "Existing")
        service.load_welcome_messages({456: "New"})

        assert service.get_welcome_message(123) == "Existing"
        assert service.get_welcome_message(456) == "New"


class TestWelcomeButtons:
    """Tests for welcome button methods."""

    def test_get_welcome_button_returns_none_for_empty(self, service):
        assert service.get_welcome_button(123) is None

    def test_set_and_get_welcome_button(self, service):
        button = {"text": "Click me", "url": "https://example.com"}
        service.set_welcome_button(123, button)

        assert service.get_welcome_button(123) == button

    def test_set_welcome_button_overwrites_existing(self, service):
        service.set_welcome_button(123, {"old": True})
        service.set_welcome_button(123, {"new": True})

        assert service.get_welcome_button(123) == {"new": True}

    def test_welcome_buttons_are_per_chat(self, service):
        service.set_welcome_button(123, {"chat": 123})
        service.set_welcome_button(456, {"chat": 456})

        assert service.get_welcome_button(123) == {"chat": 123}
        assert service.get_welcome_button(456) == {"chat": 456}

    def test_remove_welcome_button(self, service):
        service.set_welcome_button(123, {"text": "Button"})
        service.remove_welcome_button(123)

        assert service.get_welcome_button(123) is None

    def test_remove_welcome_button_no_error_for_missing(self, service):
        service.remove_welcome_button(999)  # should not raise

    def test_load_welcome_buttons_bulk(self, service):
        service.load_welcome_buttons(
            {
                123: {"btn": 1},
                456: {"btn": 2},
            }
        )

        assert service.get_welcome_button(123) == {"btn": 1}
        assert service.get_welcome_button(456) == {"btn": 2}

    def test_load_welcome_buttons_merges_with_existing(self, service):
        service.set_welcome_button(123, {"existing": True})
        service.load_welcome_buttons({456: {"new": True}})

        assert service.get_welcome_button(123) == {"existing": True}
        assert service.get_welcome_button(456) == {"new": True}


class TestDeleteIncome:
    """Tests for delete income methods."""

    def test_get_delete_income_returns_none_for_empty(self, service):
        assert service.get_delete_income(123) is None

    def test_set_and_get_delete_income(self, service):
        config = {"enabled": True, "threshold": 100}
        service.set_delete_income(123, config)

        assert service.get_delete_income(123) == config

    def test_set_delete_income_overwrites_existing(self, service):
        service.set_delete_income(123, {"old": True})
        service.set_delete_income(123, {"new": True})

        assert service.get_delete_income(123) == {"new": True}

    def test_delete_income_are_per_chat(self, service):
        service.set_delete_income(123, {"chat": 123})
        service.set_delete_income(456, {"chat": 456})

        assert service.get_delete_income(123) == {"chat": 123}
        assert service.get_delete_income(456) == {"chat": 456}

    def test_remove_delete_income(self, service):
        service.set_delete_income(123, {"config": True})
        service.remove_delete_income(123)

        assert service.get_delete_income(123) is None

    def test_remove_delete_income_no_error_for_missing(self, service):
        service.remove_delete_income(999)  # should not raise

    def test_load_delete_income_bulk(self, service):
        service.load_delete_income(
            {
                123: {"cfg": 1},
                456: {"cfg": 2},
            }
        )

        assert service.get_delete_income(123) == {"cfg": 1}
        assert service.get_delete_income(456) == {"cfg": 2}

    def test_load_delete_income_merges_with_existing(self, service):
        service.set_delete_income(123, {"existing": True})
        service.load_delete_income({456: {"new": True}})

        assert service.get_delete_income(123) == {"existing": True}
        assert service.get_delete_income(456) == {"new": True}

    def test_delete_income_accepts_any_value_type(self, service):
        """delete_income can store any value type."""
        service.set_delete_income(1, True)
        service.set_delete_income(2, 42)
        service.set_delete_income(3, "string")
        service.set_delete_income(4, [1, 2, 3])
        service.set_delete_income(5, {"nested": {"data": True}})

        assert service.get_delete_income(1) is True
        assert service.get_delete_income(2) == 42
        assert service.get_delete_income(3) == "string"
        assert service.get_delete_income(4) == [1, 2, 3]
        assert service.get_delete_income(5) == {"nested": {"data": True}}


class TestEntryChannel:
    """Tests for entry channel methods."""

    def test_get_entry_channel_returns_none_for_empty(self, service):
        assert service.get_entry_channel(123) is None

    def test_set_and_get_entry_channel(self, service):
        service.set_entry_channel(123, "-100999")

        assert service.get_entry_channel(123) == "-100999"

    def test_remove_entry_channel(self, service):
        service.set_entry_channel(123, "@channel")
        service.remove_entry_channel(123)

        assert service.get_entry_channel(123) is None

    def test_load_entry_channels_bulk(self, service):
        service.load_entry_channels({123: "-100999", 456: "@channel"})

        assert service.get_entry_channel(123) == "-100999"
        assert service.get_entry_channel(456) == "@channel"


class TestAsyncPersistence:
    """Tests for async DB-backed config service writes."""

    @pytest.mark.asyncio
    async def test_async_set_welcome_message_updates_cache_and_db(self):
        service = ConfigService()
        session = FakeSession()

        await service.async_set_welcome_message(123, "Hello", session)

        assert service.get_welcome_message(123) == "Hello"
        assert session.get_bot_config(123, BotValueTypes.WelcomeMessage) == "Hello"

    @pytest.mark.asyncio
    async def test_async_remove_welcome_button_updates_cache_and_db(self):
        service = ConfigService()
        session = FakeSession()
        await service.async_set_welcome_button(123, "Click", session)

        await service.async_remove_welcome_button(123, session)

        assert service.get_welcome_button(123) is None
        assert session.get_bot_config(123, BotValueTypes.WelcomeButton) is None

    @pytest.mark.asyncio
    async def test_async_set_delete_income_updates_cache_and_db(self):
        service = ConfigService()
        session = FakeSession()

        await service.async_set_delete_income(123, {"enabled": True}, session)

        assert service.get_delete_income(123) == {"enabled": True}
        assert session.get_bot_config(123, BotValueTypes.DeleteIncome) == {"enabled": True}
