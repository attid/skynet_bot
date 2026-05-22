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
        """Get wallet by ID."""
        record = (
            self.session.query(MyMtlWalletBot)
            .filter(
                MyMtlWalletBot.id == wallet_id,
                MyMtlWalletBot.need_delete == 0,
            )
            .first()
        )

        if not record:
            return None

        return self._to_dto(record)

    def get_wallet_by_public_key(self, public_key: str) -> Optional[WalletDTO]:
        """Get wallet by public key."""
        record = (
            self.session.query(MyMtlWalletBot)
            .filter(
                MyMtlWalletBot.public_key == public_key,
                MyMtlWalletBot.need_delete == 0,
            )
            .first()
        )

        if not record:
            return None

        return self._to_dto(record)

    def get_wallets_by_user(self, user_id: int) -> list[WalletDTO]:
        """Get all wallets for user."""
        records = (
            self.session.query(MyMtlWalletBot)
            .filter(
                MyMtlWalletBot.user_id == user_id,
                MyMtlWalletBot.need_delete == 0,
            )
            .all()
        )

        return [self._to_dto(r) for r in records]

    def get_default_wallet(self, user_id: int) -> Optional[WalletDTO]:
        """Get user's default wallet."""
        record = (
            self.session.query(MyMtlWalletBot)
            .filter(
                MyMtlWalletBot.user_id == user_id,
                MyMtlWalletBot.default_wallet == 1,
                MyMtlWalletBot.need_delete == 0,
            )
            .first()
        )

        if not record:
            # Fall back to first wallet if no default set
            record = (
                self.session.query(MyMtlWalletBot)
                .filter(
                    MyMtlWalletBot.user_id == user_id,
                    MyMtlWalletBot.need_delete == 0,
                )
                .first()
            )

        if not record:
            return None

        return self._to_dto(record)

    def set_default_wallet(self, user_id: int, wallet_id: int) -> bool:
        """Set wallet as default for user."""
        # Clear existing default
        self.session.query(MyMtlWalletBot).filter(MyMtlWalletBot.user_id == user_id).update(
            {MyMtlWalletBot.default_wallet: 0}, synchronize_session=False
        )

        # Set new default
        count = (
            self.session.query(MyMtlWalletBot)
            .filter(
                MyMtlWalletBot.id == wallet_id,
                MyMtlWalletBot.user_id == user_id,
            )
            .update({MyMtlWalletBot.default_wallet: 1}, synchronize_session=False)
        )

        return count > 0

    def update_balances(self, public_key: str, balances: dict) -> bool:
        """Update cached balances for wallet."""
        balances_json = json.dumps(balances)

        count = (
            self.session.query(MyMtlWalletBot)
            .filter(MyMtlWalletBot.public_key == public_key)
            .update({MyMtlWalletBot.balances: balances_json}, synchronize_session=False)
        )
        return count > 0

    def mark_for_deletion(self, wallet_id: int) -> bool:
        """Mark wallet for deletion (soft delete)."""
        count = (
            self.session.query(MyMtlWalletBot)
            .filter(MyMtlWalletBot.id == wallet_id)
            .update({MyMtlWalletBot.need_delete: 1}, synchronize_session=False)
        )
        return count > 0

    def count_user_wallets(self, user_id: int) -> int:
        """Count active wallets for user."""
        return (
            self.session.query(MyMtlWalletBot)
            .filter(
                MyMtlWalletBot.user_id == user_id,
                MyMtlWalletBot.need_delete == 0,
            )
            .count()
        )

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
