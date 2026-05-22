from typing import List, Optional, Tuple, cast

from sqlalchemy import select, func, and_, desc, cast as sql_cast, Float, Date

from db.repositories.base import BaseRepository
from shared.infrastructure.database.models import TPayments, TDivList, TTransaction, TWatchList, TLedgers, TOperations


class FinanceRepository(BaseRepository):
    def get_total_user_div(self) -> float:
        stmt = (
            select(func.sum(TPayments.user_div))
            .select_from(TPayments)
            .join(TDivList, and_(TDivList.id == TPayments.id_div_list))
            .where(TDivList.pay_type == 1)
        )
        result = self.session.execute(stmt).scalar()
        return result if result is not None else 0.0

    async def async_get_total_user_div(self) -> float:
        stmt = (
            select(func.sum(TPayments.user_div))
            .select_from(TPayments)
            .join(TDivList, and_(TDivList.id == TPayments.id_div_list))
            .where(TDivList.pay_type == 1)
        )
        result = await self.session.execute(stmt)
        value = result.scalar()
        return value if value is not None else 0.0

    def get_div_list(self, list_id: int) -> Optional[TDivList]:
        return self.session.execute(select(TDivList).where(TDivList.id == list_id)).scalar_one_or_none()

    async def async_get_div_list(self, list_id: int) -> Optional[TDivList]:
        result = await self.session.execute(select(TDivList).where(TDivList.id == list_id))
        return result.scalar_one_or_none()

    def get_payments(self, list_id: int, pack_count: int) -> List[TPayments]:
        result = self.session.execute(
            select(TPayments).where(and_(TPayments.was_packed == 0, TPayments.id_div_list == list_id)).limit(pack_count)
        )
        return cast(List[TPayments], result.scalars().all())

    async def async_get_payments(self, list_id: int, pack_count: int) -> List[TPayments]:
        result = await self.session.execute(
            select(TPayments).where(and_(TPayments.was_packed == 0, TPayments.id_div_list == list_id)).limit(pack_count)
        )
        return cast(List[TPayments], result.scalars().all())

    def count_unpacked_payments(self, list_id: int) -> int:
        result = self.session.execute(
            select(func.count()).where(and_(TPayments.was_packed == 0, TPayments.id_div_list == list_id))
        ).scalar()
        return result if result is not None else 0

    async def async_count_unpacked_payments(self, list_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).where(and_(TPayments.was_packed == 0, TPayments.id_div_list == list_id))
        )
        value = result.scalar()
        return value if value is not None else 0

    def count_unsent_transactions(self, list_id: int) -> int:
        result = self.session.execute(
            select(func.count()).where(and_(TTransaction.was_send == 0, TTransaction.id_div_list == list_id))
        ).scalar()
        return result if result is not None else 0

    async def async_count_unsent_transactions(self, list_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).where(and_(TTransaction.was_send == 0, TTransaction.id_div_list == list_id))
        )
        value = result.scalar()
        return value if value is not None else 0

    def load_transactions(self, list_id: int) -> List[TTransaction]:
        result = self.session.execute(
            select(TTransaction).where(and_(TTransaction.was_send == 0, TTransaction.id_div_list == list_id))
        )
        return cast(List[TTransaction], result.scalars().all())

    async def async_load_transactions(self, list_id: int) -> List[TTransaction]:
        result = await self.session.execute(
            select(TTransaction).where(and_(TTransaction.was_send == 0, TTransaction.id_div_list == list_id))
        )
        return cast(List[TTransaction], result.scalars().all())

    def get_watch_list(self) -> Tuple[str, ...]:
        result = self.session.execute(select(TWatchList.account))
        return tuple(row[0] for row in result.fetchall())

    def add_to_watchlist(self, public_keys: List[str]) -> None:
        current_watch_list = self.get_watch_list()
        new_keys = [key for key in public_keys if key not in current_watch_list]

        for key in new_keys:
            new_entry = TWatchList(account=key)
            self.session.add(new_entry)

    def get_first_100_ledgers(self) -> List[TLedgers]:
        result = self.session.execute(select(TLedgers).order_by(TLedgers.ledger).limit(100))
        return cast(List[TLedgers], result.scalars().all())

    def get_ledger(self, ledger_id: int) -> Optional[TLedgers]:
        return self.session.execute(select(TLedgers).where(TLedgers.ledger == ledger_id)).scalar_one_or_none()

    def get_ledger_count(self) -> int:
        result = self.session.execute(select(func.count()).select_from(TLedgers))
        return result.scalar() if result is not None else 0

    def get_new_effects_for_token(self, token: str, last_id: str, amount: float) -> List[TOperations]:
        assert len(token) <= 32, "Length of 'token' should not exceed 32 characters"

        base_query = (
            select(TOperations)
            .where(TOperations.operation != "trustline_created")
            .where(
                (TOperations.code1 == token) & (sql_cast(TOperations.amount1, Float) > amount)
                | (TOperations.code2 == token) & (sql_cast(TOperations.amount2, Float) > amount)
            )
        )

        if last_id == "-1":
            stmt = base_query.order_by(desc(TOperations.id)).limit(1)
        else:
            stmt = base_query.where(TOperations.id > last_id).order_by(TOperations.id).limit(10)

        result = self.session.execute(stmt)
        return cast(List[TOperations], result.scalars().all())

    async def async_get_new_effects_for_token(self, token: str, last_id: str, amount: float) -> List[TOperations]:
        assert len(token) <= 32, "Length of 'token' should not exceed 32 characters"

        base_query = (
            select(TOperations)
            .where(TOperations.operation != "trustline_created")
            .where(
                (TOperations.code1 == token) & (sql_cast(TOperations.amount1, Float) > amount)
                | (TOperations.code2 == token) & (sql_cast(TOperations.amount2, Float) > amount)
            )
        )

        if last_id == "-1":
            stmt = base_query.order_by(desc(TOperations.id)).limit(1)
        else:
            stmt = base_query.where(TOperations.id > last_id).order_by(TOperations.id).limit(10)

        result = await self.session.execute(stmt)
        return cast(List[TOperations], result.scalars().all())

    def get_operations(self, last_id: Optional[str] = None, limit: int = 3000) -> List[TOperations]:
        if last_id is None:
            last_record = self.session.execute(select(TOperations).order_by(desc(TOperations.dt))).scalar()
            return [last_record] if last_record else []

        stmt = select(TOperations).where(TOperations.id > last_id).order_by(TOperations.id).limit(limit)
        result = self.session.execute(stmt)
        return cast(List[TOperations], result.scalars().all())

    def get_last_trade_operation(self, asset_code: str = "MTL", minimal_sum: float = 0) -> float:
        stmt = (
            select(TOperations)
            .where(
                (TOperations.operation == "trade")
                & (
                    and_(
                        (TOperations.code1 == asset_code),
                        (TOperations.code2 == "EURMTL"),
                        (sql_cast(TOperations.amount1, Float) > minimal_sum),
                    )
                    | and_(
                        (TOperations.code1 == "EURMTL"),
                        (TOperations.code2 == asset_code),
                        (sql_cast(TOperations.amount2, Float) > minimal_sum),
                    )
                )
            )
            .order_by(desc(TOperations.dt))
            .limit(1)
        )

        operation = self.session.execute(stmt).scalar_one_or_none()
        if operation:
            try:
                if operation.code2 == asset_code:
                    rate = float(operation.amount1) / float(operation.amount2)
                else:
                    rate = float(operation.amount2) / float(operation.amount1)
                return round(rate, 2)
            except ZeroDivisionError:
                return 0.0
        return 0.0

    def get_operations_by_asset(self, asset_code: str, dt_filter) -> List[TOperations]:
        stmt = (
            select(TOperations)
            .where((TOperations.code1 == asset_code) | (TOperations.code2 == asset_code))
            .where(sql_cast(TOperations.dt, Date) == dt_filter)
        )
        result = self.session.execute(stmt)
        return cast(List[TOperations], result.scalars().all())

    async def async_get_operations_by_asset(self, asset_code: str, dt_filter) -> List[TOperations]:
        stmt = (
            select(TOperations)
            .where((TOperations.code1 == asset_code) | (TOperations.code2 == asset_code))
            .where(sql_cast(TOperations.dt, Date) == dt_filter)
        )
        result = await self.session.execute(stmt)
        return cast(List[TOperations], result.scalars().all())
