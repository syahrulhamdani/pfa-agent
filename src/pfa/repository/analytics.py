"""SQL aggregations behind the dashboard.

Every query looks only at confirmed transactions dated within the range, and treats
transactions flagged as transfers (moves between the user's own accounts) separately,
so that they are never counted as spending or income.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import ColumnElement, Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.models import Category, Direction, Transaction, TransactionStatus

UNCATEGORISED = "Uncategorised"
SeriesBucket = Literal["day", "week", "month"]


def _is_transfer() -> ColumnElement[bool]:
    return Transaction.is_transfer.is_(True)


def _is_counted() -> ColumnElement[bool]:
    return Transaction.is_transfer.is_(False)


class AnalyticsRepository:
    """Reads aggregated figures for a date range."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    def _confirmed_between(
        self, start: date, end: date
    ) -> tuple[ColumnElement[bool], ...]:
        return (
            Transaction.status == TransactionStatus.CONFIRMED.value,
            Transaction.occurred_on >= start,
            Transaction.occurred_on <= end,
            Transaction.amount.is_not(None),
        )

    async def totals_by_direction(
        self, start: date, end: date
    ) -> dict[Direction, tuple[int, Decimal]]:
        """Returns (count, total) for money out and money in, transfers excluded."""
        rows = await self._session.execute(
            select(Transaction.direction, func.count(), func.sum(Transaction.amount))
            .select_from(Transaction)
            .where(*self._confirmed_between(start, end), _is_counted())
            .group_by(Transaction.direction)
        )
        found = {Direction(d): (count, total) for d, count, total in rows}
        return {d: found.get(d, (0, Decimal("0.00"))) for d in Direction}

    async def transfer_totals(self, start: date, end: date) -> tuple[int, Decimal]:
        """Returns (count, total) of moves between the user's own accounts."""
        row = (
            await self._session.execute(
                select(func.count(), func.coalesce(func.sum(Transaction.amount), 0))
                .select_from(Transaction)
                .where(*self._confirmed_between(start, end), _is_transfer())
            )
        ).one()
        return row[0], Decimal(row[1])

    async def by_category(
        self, start: date, end: date
    ) -> list[tuple[Direction, str, int, Decimal]]:
        """Returns (direction, category, count, total), biggest total first."""
        name = func.coalesce(Category.name, UNCATEGORISED)
        total = func.sum(Transaction.amount)
        rows = await self._session.execute(
            select(Transaction.direction, name, func.count(), total)
            .select_from(Transaction)
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(*self._confirmed_between(start, end), _is_counted())
            .group_by(Transaction.direction, name)
            .order_by(total.desc(), name)
        )
        return [(Direction(d), n, count, t) for d, n, count, t in rows]

    async def series(
        self, start: date, end: date, bucket: SeriesBucket
    ) -> list[tuple[date, Direction, Decimal]]:
        """Returns (bucket start, direction, total) with no empty buckets."""
        if bucket == "day":
            start_of_bucket = Transaction.occurred_on
        else:
            start_of_bucket = cast(
                func.date_trunc(bucket, Transaction.occurred_on), Date
            )
        rows = await self._session.execute(
            select(start_of_bucket, Transaction.direction, func.sum(Transaction.amount))
            .select_from(Transaction)
            .where(*self._confirmed_between(start, end), _is_counted())
            .group_by(start_of_bucket, Transaction.direction)
        )
        return [(day, Direction(d), t) for day, d, t in rows]
