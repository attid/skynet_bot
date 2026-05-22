# db/repositories/wallets.py
"""Wallets repository for Stellar wallet management."""

from typing import Optional
from dataclasses import dataclass
import json

from .base import BaseRepository
from shared.infrastructure.database.models import MyMtlWalletBot


@dataclass
class WalletDTO:
    """Data transfer object for wallet data."""

    id: int
    user_id: int
    public_key: str
    is_default: bool = False
    free_wallet: bool = True
    balances: Optional[dict] = None


class WalletsRepository(BaseRepository):
    """Repository for wallet operations."""

    def get_wallet_by_id(self, wallet_id: int) -> Optional[WalletDTO]:
        self._raise_sync_removed("get_wallet_by_id")

    def get_wallet_by_public_key(self, public_key: str) -> Optional[WalletDTO]:
        self._raise_sync_removed("get_wallet_by_public_key")

    def get_wallets_by_user(self, user_id: int) -> list[WalletDTO]:
        self._raise_sync_removed("get_wallets_by_user")

    def get_default_wallet(self, user_id: int) -> Optional[WalletDTO]:
        self._raise_sync_removed("get_default_wallet")

    def set_default_wallet(self, user_id: int, wallet_id: int) -> bool:
        self._raise_sync_removed("set_default_wallet")

    def update_balances(self, public_key: str, balances: dict) -> bool:
        self._raise_sync_removed("update_balances")

    def mark_for_deletion(self, wallet_id: int) -> bool:
        self._raise_sync_removed("mark_for_deletion")

    def count_user_wallets(self, user_id: int) -> int:
        self._raise_sync_removed("count_user_wallets")

    def _to_dto(self, record: MyMtlWalletBot) -> WalletDTO:
        """Convert ORM record to DTO."""
        balances = None
        if record.balances:
            try:
                balances = json.loads(record.balances)
            except (json.JSONDecodeError, TypeError):
                balances = None

        return WalletDTO(
            id=record.id,
            user_id=record.user_id,
            public_key=record.public_key,
            is_default=bool(record.default_wallet),
            free_wallet=bool(record.free_wallet),
            balances=balances,
        )
