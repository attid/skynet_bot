# db/repositories/payments.py
"""Payments repository for dividend payment management."""

from typing import Optional
from decimal import Decimal
from sqlalchemy import func

from .base import BaseRepository
from shared.infrastructure.database.models import TPayments
from shared.domain.payment import Payment, PaymentStatus


class PaymentsRepository(BaseRepository):
    """Repository for payment operations with domain model mapping."""

    def get_payment_by_id(self, payment_id: int) -> Optional[Payment]:
        """Get payment by ID as domain model."""
        record = self.session.query(TPayments).filter(TPayments.id == payment_id).first()

        if not record:
            return None

        return self._to_domain(record)

    def get_payments_by_list(
        self,
        list_id: int,
        status: Optional[PaymentStatus] = None,
        limit: int = 100,
    ) -> list[Payment]:
        """Get payments for dividend list."""
        query = self.session.query(TPayments).filter(TPayments.id_div_list == list_id)

        if status == PaymentStatus.PENDING:
            query = query.filter(TPayments.was_packed == 0)
        elif status == PaymentStatus.PACKED:
            query = query.filter(TPayments.was_packed == 1)

        records = query.limit(limit).all()
        return [self._to_domain(r) for r in records]

    def get_unpacked_payments(self, list_id: int, limit: int = 70) -> list[Payment]:
        """Get unpacked payments for list (for packing into transactions)."""
        records = (
            self.session.query(TPayments)
            .filter(TPayments.id_div_list == list_id, TPayments.was_packed == 0)
            .limit(limit)
            .all()
        )

        return [self._to_domain(r) for r in records]

    def count_unpacked_payments(self, list_id: int) -> int:
        """Count unpacked payments for list."""
        return self.session.query(TPayments).filter(TPayments.id_div_list == list_id, TPayments.was_packed == 0).count()

    def mark_as_packed(self, payment_ids: list[int]) -> int:
        """Mark payments as packed. Returns count updated."""
        if not payment_ids:
            return 0

        count = (
            self.session.query(TPayments)
            .filter(TPayments.id.in_(payment_ids))
            .update({TPayments.was_packed: 1}, synchronize_session=False)
        )
        return count

    def get_total_for_user(self, user_key: str) -> Decimal:
        """Get total dividend amount for user across all lists."""
        result = self.session.query(func.sum(TPayments.user_div)).filter(TPayments.user_key == user_key).scalar()

        return Decimal(str(result)) if result else Decimal("0")

    def get_total_for_list(self, list_id: int) -> Decimal:
        """Get total dividend amount for list."""
        result = self.session.query(func.sum(TPayments.user_div)).filter(TPayments.id_div_list == list_id).scalar()

        return Decimal(str(result)) if result else Decimal("0")

    def create_payment(
        self,
        user_key: str,
        amount: Decimal,
        list_id: int,
        mtl_sum: Optional[float] = None,
        user_calc: Optional[float] = None,
    ) -> Payment:
        """Create new payment record."""
        record = TPayments(
            user_key=user_key,
            user_div=float(amount),
            id_div_list=list_id,
            mtl_sum=mtl_sum,
            user_calc=user_calc,
            was_packed=0,
        )
        self.session.add(record)
        return self._to_domain(record)

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
