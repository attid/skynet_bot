# db/repositories/payments.py
"""Payments repository for dividend payment management."""

from typing import Optional
from decimal import Decimal

from .base import BaseRepository
from shared.infrastructure.database.models import TPayments
from shared.domain.payment import Payment, PaymentStatus


class PaymentsRepository(BaseRepository):
    """Repository for payment operations with domain model mapping."""

    def get_payment_by_id(self, payment_id: int) -> Optional[Payment]:
        self._raise_sync_removed("get_payment_by_id")

    def get_payments_by_list(
        self,
        list_id: int,
        status: Optional[PaymentStatus] = None,
        limit: int = 100,
    ) -> list[Payment]:
        self._raise_sync_removed("get_payments_by_list")

    def get_unpacked_payments(self, list_id: int, limit: int = 70) -> list[Payment]:
        self._raise_sync_removed("get_unpacked_payments")

    def count_unpacked_payments(self, list_id: int) -> int:
        self._raise_sync_removed("count_unpacked_payments")

    def mark_as_packed(self, payment_ids: list[int]) -> int:
        self._raise_sync_removed("mark_as_packed")

    def get_total_for_user(self, user_key: str) -> Decimal:
        self._raise_sync_removed("get_total_for_user")

    def get_total_for_list(self, list_id: int) -> Decimal:
        self._raise_sync_removed("get_total_for_list")

    def create_payment(
        self,
        user_key: str,
        amount: Decimal,
        list_id: int,
        mtl_sum: Optional[float] = None,
        user_calc: Optional[float] = None,
    ) -> Payment:
        self._raise_sync_removed("create_payment")

    def _to_domain(self, record: TPayments) -> Payment:
        """Convert ORM record to domain model."""
        status = PaymentStatus.PACKED if record.was_packed else PaymentStatus.PENDING

        return Payment(
            id=record.id,
            user_key=record.user_key,
            amount=Decimal(str(record.user_div)) if record.user_div else Decimal("0"),
            status=status,
            list_id=record.id_div_list,
        )
