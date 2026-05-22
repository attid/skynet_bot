from typing import List, Optional, Tuple, cast

from sqlalchemy import select, func, and_, desc, cast as sql_cast, Float, Date

from db.repositories.base import BaseRepository
from shared.infrastructure.database.models import TPayments, TDivList, TTransaction, TLedgers, TOperations


class FinanceRepository(BaseRepository):
    def get_total_user_div(self) -> float:
        self._raise_sync_removed("get_total_user_div")

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
        self._raise_sync_removed("get_div_list")

    async def async_get_div_list(self, list_id: int) -> Optional[TDivList]:
        result = await self.session.execute(select(TDivList).where(TDivList.id == list_id))
        return result.scalar_one_or_none()

    def get_payments(self, list_id: int, pack_count: int) -> List[TPayments]:
        self._raise_sync_removed("get_payments")

    async def async_get_payments(self, list_id: int, pack_count: int) -> List[TPayments]:
        result = await self.session.execute(
            select(TPayments).where(and_(TPayments.was_packed == 0, TPayments.id_div_list == list_id)).limit(pack_count)
        )
        return cast(List[TPayments], result.scalars().all())

    def count_unpacked_payments(self, list_id: int) -> int:
        self._raise_sync_removed("count_unpacked_payments")

    async def async_count_unpacked_payments(self, list_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).where(and_(TPayments.was_packed == 0, TPayments.id_div_list == list_id))
        )
        value = result.scalar()
        return value if value is not None else 0

    def count_unsent_transactions(self, list_id: int) -> int:
        self._raise_sync_removed("count_unsent_transactions")

    async def async_count_unsent_transactions(self, list_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).where(and_(TTransaction.was_send == 0, TTransaction.id_div_list == list_id))
        )
        value = result.scalar()
        return value if value is not None else 0

    def load_transactions(self, list_id: int) -> List[TTransaction]:
        self._raise_sync_removed("load_transactions")

    async def async_load_transactions(self, list_id: int) -> List[TTransaction]:
        result = await self.session.execute(
            select(TTransaction).where(and_(TTransaction.was_send == 0, TTransaction.id_div_list == list_id))
        )
        return cast(List[TTransaction], result.scalars().all())

    def get_watch_list(self) -> Tuple[str, ...]:
        self._raise_sync_removed("get_watch_list")

    def add_to_watchlist(self, public_keys: List[str]) -> None:
        self._raise_sync_removed("add_to_watchlist")

    def get_first_100_ledgers(self) -> List[TLedgers]:
        self._raise_sync_removed("get_first_100_ledgers")

    def get_ledger(self, ledger_id: int) -> Optional[TLedgers]:
        self._raise_sync_removed("get_ledger")

    def get_ledger_count(self) -> int:
        self._raise_sync_removed("get_ledger_count")

    def get_new_effects_for_token(self, token: str, last_id: str, amount: float) -> List[TOperations]:
        self._raise_sync_removed("get_new_effects_for_token")

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
        self._raise_sync_removed("get_operations")

    async def async_get_operations(self, last_id: Optional[str] = None, limit: int = 3000) -> List[TOperations]:
        if last_id is None:
            result = await self.session.execute(select(TOperations).order_by(desc(TOperations.dt)))
            last_record = result.scalar()
            return [last_record] if last_record else []

        stmt = select(TOperations).where(TOperations.id > last_id).order_by(TOperations.id).limit(limit)
        result = await self.session.execute(stmt)
        return cast(List[TOperations], result.scalars().all())

    def get_last_trade_operation(self, asset_code: str = "MTL", minimal_sum: float = 0) -> float:
        self._raise_sync_removed("get_last_trade_operation")

    def get_operations_by_asset(self, asset_code: str, dt_filter) -> List[TOperations]:
        self._raise_sync_removed("get_operations_by_asset")

    async def async_get_operations_by_asset(self, asset_code: str, dt_filter) -> List[TOperations]:
        stmt = (
            select(TOperations)
            .where((TOperations.code1 == asset_code) | (TOperations.code2 == asset_code))
            .where(sql_cast(TOperations.dt, Date) == dt_filter)
        )
        result = await self.session.execute(stmt)
        return cast(List[TOperations], result.scalars().all())
