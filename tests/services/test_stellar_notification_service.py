# tests/services/test_stellar_notification_service.py
"""Unit tests for StellarNotificationService internal logic.

All external I/O (Telegram, Horizon, the operations-notifier HTTP API) is stubbed
at the service boundary: tests patch ``_send_to_telegram`` and never populate
``envelope_xdr`` (which would trigger the XDR decode path), and none of the
notifier HTTP methods (``subscribe_token``/``subscribe_account``/``unsubscribe``/
``get_active_subscriptions``/``sync_subscriptions``/``start_server``) are
exercised here. The ``Mock()`` bot is therefore safe — no code path under test
calls ``self.bot.<method>(...)``, so there is no serialization surface to hide.

This file intentionally does not use ``mock_telegram``/``mock_horizon``/
``mock_grist``: per docs/conventions.md, service-level fakes are allowed for
unit-testing pure internal logic (dedup, min filter, message formatting, webhook
parsing, nonce, auth headers). Tests that exercise a real outgoing request must
be added to a separate file and use the canonical fixtures from
``tests/conftest.py``.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import json

from services.stellar_notification_service import StellarNotificationService


@pytest.fixture
def mock_bot():
    """Create a mock bot instance."""
    return Mock()


@pytest.fixture
def mock_session_pool():
    """Create a mock session pool."""
    mock_session = Mock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.commit = AsyncMock()

    pool = Mock(return_value=mock_session)
    return pool


@pytest.fixture
def service(mock_bot, mock_session_pool):
    """Create StellarNotificationService with mocks."""
    with patch("services.stellar_notification_service.config") as mock_config:
        mock_config.notifier_url = "http://notifier:8000"
        mock_config.webhook_public_url = "http://skynet:8081/webhook"
        mock_config.webhook_port = 8081
        mock_config.notifier_auth_token = "test_token"
        mock_config.test_mode = True
        return StellarNotificationService(mock_bot, mock_session_pool)


class TestGetAssetCode:
    """Tests for _get_asset_code method."""

    def test_returns_xlm_for_none(self, service):
        assert service._get_asset_code(None) == "XLM"

    def test_returns_xlm_for_empty_dict(self, service):
        assert service._get_asset_code({}) == "XLM"

    def test_returns_xlm_for_native_string(self, service):
        assert service._get_asset_code({"asset_type": "native"}) == "XLM"

    def test_returns_xlm_for_native_zero(self, service):
        assert service._get_asset_code({"asset_type": 0}) == "XLM"

    def test_returns_xlm_for_native_zero_string(self, service):
        assert service._get_asset_code({"asset_type": "0"}) == "XLM"

    def test_returns_asset_code(self, service):
        assert service._get_asset_code({"asset_code": "MTL", "asset_type": "credit_alphanum4"}) == "MTL"

    def test_returns_xlm_when_no_asset_code(self, service):
        assert service._get_asset_code({"asset_type": "credit_alphanum4"}) == "XLM"


class TestFormatMessage:
    """Tests for _format_message method."""

    def test_format_payment(self, service):
        payload = {
            "operation": {
                "id": "12345",
                "type": "payment",
                "source_account": "GABC1234567890123456789012345678901234567890123456789012",
                "to": "GDEF1234567890123456789012345678901234567890123456789012",
                "amount": "100.5",
                "asset": {"asset_code": "MTL", "asset_type": "credit_alphanum4"},
            },
            "transaction": {},
        }
        destination = {"type": "asset"}

        result = service._format_message(payload, destination)

        assert "payment" in result
        assert "100.5" in result
        assert "MTL" in result
        assert "GABC..9012" in result
        assert "GDEF..9012" in result
        assert "12345" in result

    def test_format_create_account(self, service):
        payload = {
            "operation": {
                "id": "67890",
                "type": "create_account",
                "source_account": "GABC1234567890123456789012345678901234567890123456789012",
                "destination": "GNEW1234567890123456789012345678901234567890123456789012",
                "amount": "50",
            },
            "transaction": {},
        }
        destination = {"type": "account"}

        result = service._format_message(payload, destination)

        assert "create_account" in result
        assert "50" in result
        assert "XLM" in result

    def test_format_path_payment(self, service):
        payload = {
            "operation": {
                "id": "11111",
                "type": "path_payment_strict_send",
                "source_account": "GABC1234567890123456789012345678901234567890123456789012",
                "to": "GDEF1234567890123456789012345678901234567890123456789012",
                "source_amount": "100",
                "source_asset": {"asset_code": "USDC", "asset_type": "credit_alphanum4"},
                "dest_amount": "95",
                "asset": {"asset_code": "EURMTL", "asset_type": "credit_alphanum12"},
            },
            "transaction": {},
        }
        destination = {"type": "asset"}

        result = service._format_message(payload, destination)

        assert "path_payment_strict_send" in result
        assert "100" in result
        assert "USDC" in result
        assert "95" in result
        assert "EURMTL" in result

    def test_format_manage_sell_offer(self, service):
        payload = {
            "operation": {
                "id": "22222",
                "type": "manage_sell_offer",
                "source_account": "GABC1234567890123456789012345678901234567890123456789012",
                "amount": "1000",
                "price": "1.5",
                "source_asset": {"asset_code": "MTL", "asset_type": "credit_alphanum4"},
                "asset": {"asset_code": "EURMTL", "asset_type": "credit_alphanum12"},
                "offer_id": 12345,
            },
            "transaction": {},
        }
        destination = {"type": "asset"}

        result = service._format_message(payload, destination)

        assert "manage_sell_offer" in result
        assert "1000" in result
        assert "MTL" in result
        assert "EURMTL" in result
        assert "1.5" in result
        assert "12345" in result

    def test_format_change_trust(self, service):
        payload = {
            "operation": {
                "id": "33333",
                "type": "change_trust",
                "source_account": "GABC1234567890123456789012345678901234567890123456789012",
                "asset": {"asset_code": "MMWB", "asset_type": "credit_alphanum4"},
                "limit": "1000000",
            },
            "transaction": {},
        }
        destination = {"type": "account"}

        result = service._format_message(payload, destination)

        assert "change_trust" in result
        assert "MMWB" in result
        assert "1000000" in result

    def test_format_with_memo(self, service):
        payload = {
            "operation": {
                "id": "44444",
                "type": "payment",
                "source_account": "GABC1234567890123456789012345678901234567890123456789012",
                "to": "GDEF1234567890123456789012345678901234567890123456789012",
                "amount": "50",
                "asset": {"asset_type": "native"},
            },
            "transaction": {"memo": {"type": "text", "value": "Test memo"}},
        }
        destination = {"type": "asset"}

        result = service._format_message(payload, destination)

        assert "Memo: Test memo" in result

    def test_format_with_buffer_memo(self, service):
        payload = {
            "operation": {
                "id": "55555",
                "type": "payment",
                "source_account": "GABC1234567890123456789012345678901234567890123456789012",
                "to": "GDEF1234567890123456789012345678901234567890123456789012",
                "amount": "50",
                "asset": {"asset_type": "native"},
            },
            "transaction": {
                "memo": {
                    "type": "text",
                    "value": {"data": [72, 101, 108, 108, 111]},  # "Hello"
                }
            },
        }
        destination = {"type": "asset"}

        result = service._format_message(payload, destination)

        assert "Memo: Hello" in result

    def test_format_unknown_operation(self, service):
        payload = {
            "operation": {
                "id": "66666",
                "type": "unknown_op",
                "source_account": "GABC1234567890123456789012345678901234567890123456789012",
            },
            "transaction": {},
        }
        destination = {"type": "asset"}

        result = service._format_message(payload, destination)

        assert "unknown_op" in result
        assert "GABC..9012" in result


class TestDeduplication:
    """Tests for operation deduplication."""

    @pytest.mark.asyncio
    async def test_duplicate_operation_skipped(self, service):
        service.subscriptions_map["sub-1"] = {"chat_id": 123, "topic_id": None, "type": "asset", "min": 0}

        payload = {
            "subscription": "sub-1",
            "operation": {"id": "op-123", "type": "payment", "amount": "100"},
            "transaction": {},
        }

        # First call
        with patch.object(service, "_send_to_telegram", new_callable=AsyncMock) as mock_send:
            await service.process_notification(payload, "sub-1")
            assert mock_send.called

        # Second call with same operation ID
        with patch.object(service, "_send_to_telegram", new_callable=AsyncMock) as mock_send:
            await service.process_notification(payload, "sub-1")
            assert not mock_send.called

    @pytest.mark.asyncio
    async def test_cache_cleared_when_full(self, service):
        service.max_cache_size = 3
        service.subscriptions_map["sub-1"] = {"chat_id": 123, "topic_id": None, "type": "asset", "min": 0}

        with patch.object(service, "_send_to_telegram", new_callable=AsyncMock):
            # Fill up the cache
            for i in range(4):
                payload = {
                    "subscription": "sub-1",
                    "operation": {"id": f"op-{i}", "type": "payment", "amount": "100"},
                    "transaction": {},
                }
                await service.process_notification(payload, "sub-1")

        # Cache should have been cleared after exceeding max_cache_size
        assert len(service.notified_operations) < 4

    @pytest.mark.asyncio
    async def test_same_transaction_hash_sent_once(self, service):
        service.subscriptions_map["sub-1"] = {
            "chat_id": 123,
            "topic_id": None,
            "type": "asset",
            "min": 0,
        }

        payload_1 = {
            "subscription": "sub-1",
            "operation": {"id": "op-1", "type": "payment", "amount": "100"},
            "transaction": {"hash": "tx-123", "envelope_xdr": None},
        }
        payload_2 = {
            "subscription": "sub-1",
            "operation": {"id": "op-2", "type": "manage_sell_offer", "amount": "0"},
            "transaction": {"hash": "tx-123", "envelope_xdr": None},
        }

        with patch.object(service, "_send_to_telegram", new_callable=AsyncMock) as mock_send:
            await service.process_notification(payload_1, "sub-1")
            await service.process_notification(payload_2, "sub-1")
            assert mock_send.call_count == 1


class TestMinimumAmountFilter:
    """Tests for minimum amount filtering."""

    @pytest.mark.asyncio
    async def test_operation_below_minimum_skipped(self, service):
        service.subscriptions_map["sub-1"] = {
            "chat_id": 123,
            "topic_id": None,
            "type": "asset",
            "min": 100,  # Minimum amount filter
        }

        payload = {
            "subscription": "sub-1",
            "operation": {
                "id": "op-below-min",
                "type": "payment",
                "amount": "50",  # Below minimum
            },
            "transaction": {},
        }

        with patch.object(service, "_send_to_telegram", new_callable=AsyncMock) as mock_send:
            await service.process_notification(payload, "sub-1")
            assert not mock_send.called

    @pytest.mark.asyncio
    async def test_operation_above_minimum_sent(self, service):
        service.subscriptions_map["sub-1"] = {"chat_id": 123, "topic_id": None, "type": "asset", "min": 100}

        payload = {
            "subscription": "sub-1",
            "operation": {
                "id": "op-above-min",
                "type": "payment",
                "amount": "150",  # Above minimum
            },
            "transaction": {},
        }

        with patch.object(service, "_send_to_telegram", new_callable=AsyncMock) as mock_send:
            await service.process_notification(payload, "sub-1")
            assert mock_send.called


class TestSubscriptionRouting:
    """Tests for subscription-based message routing."""

    @pytest.mark.asyncio
    async def test_unknown_subscription_logged(self, service):
        payload = {
            "subscription": "unknown-sub",
            "operation": {"id": "op-1", "type": "payment", "amount": "100"},
            "transaction": {},
        }

        with patch.object(service, "_send_to_telegram", new_callable=AsyncMock) as mock_send:
            await service.process_notification(payload)
            assert not mock_send.called

    @pytest.mark.asyncio
    async def test_missing_subscription_id_handled(self, service):
        payload = {"operation": {"id": "op-1", "type": "payment", "amount": "100"}, "transaction": {}}

        with patch.object(service, "_send_to_telegram", new_callable=AsyncMock) as mock_send:
            await service.process_notification(payload)
            assert not mock_send.called


class TestWebhookHandler:
    """Tests for webhook handler."""

    @pytest.mark.asyncio
    async def test_handle_webhook_empty_payload(self, service):
        request = MagicMock()
        request.read = AsyncMock(return_value=b"")

        response = await service.handle_webhook(request)

        assert response.status == 400
        assert "Empty payload" in response.text

    @pytest.mark.asyncio
    async def test_handle_webhook_invalid_json(self, service):
        request = MagicMock()
        request.read = AsyncMock(return_value=b"not valid json")

        response = await service.handle_webhook(request)

        assert response.status == 400
        assert "Invalid JSON" in response.text

    @pytest.mark.asyncio
    async def test_handle_webhook_valid_payload(self, service):
        service.subscriptions_map["sub-1"] = {"chat_id": 123, "topic_id": None, "type": "asset", "min": 0}

        payload = {
            "subscription": "sub-1",
            "operation": {"id": "webhook-op-1", "type": "payment", "amount": "100"},
            "transaction": {},
        }

        request = MagicMock()
        request.read = AsyncMock(return_value=json.dumps(payload).encode())

        with patch.object(service, "_send_to_telegram", new_callable=AsyncMock):
            response = await service.handle_webhook(request)

        assert response.status == 200
        assert response.text == "OK"


class TestAuthHeaders:
    """Tests for authentication header generation."""

    def test_get_auth_headers_with_token(self, service):
        with patch("services.stellar_notification_service.config") as mock_config:
            mock_config.notifier_auth_token = "Bearer test123"

            headers = service._get_auth_headers()

            assert headers["Authorization"] == "Bearer test123"
            assert headers["Content-Type"] == "application/json"

    def test_get_auth_headers_without_token(self, service):
        with patch("services.stellar_notification_service.config") as mock_config:
            mock_config.notifier_auth_token = None

            headers = service._get_auth_headers()

            assert "Authorization" not in headers
            assert headers["Content-Type"] == "application/json"


class TestNonce:
    """Tests for nonce management."""

    @pytest.mark.asyncio
    async def test_nonce_increments(self, service):
        nonce1 = await service._get_next_nonce()
        nonce2 = await service._get_next_nonce()

        assert nonce2 == nonce1 + 1

    @pytest.mark.asyncio
    async def test_nonce_initializes_from_time(self, service):
        import time

        before = int(time.time() * 1000)
        nonce = await service._get_next_nonce()
        after = int(time.time() * 1000) + 1

        # Nonce should be time-based + 1
        assert before < nonce <= after + 1
