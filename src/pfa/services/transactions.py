"""Reading confirmed transactions for the web app."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from pfa.core.exceptions import NotFoundError
from pfa.models.finance import Direction
from pfa.repository.finance import CategoryRepository, TransactionRepository
from pfa.schemas.transactions import DateBasis, TransactionFilter, TransactionRead


def local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Returns the UTC start (inclusive) and end (exclusive) of a local day."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def _to_read(rows) -> list[TransactionRead]:
    return [
        TransactionRead(
            id=tx.id,
            merchant=tx.merchant,
            amount=tx.amount,
            occurred_on=tx.occurred_on,
            category=category,
            card=card,
            description=tx.description,
            direction=Direction(tx.direction),
            is_transfer=tx.is_transfer,
            confirmed_at=tx.confirmed_at,
        )
        for tx, category, card in rows
    ]


async def todays_transactions(
    session: AsyncSession, timezone: str, now: datetime | None = None
) -> list[TransactionRead]:
    """Lists transactions confirmed today in the user's timezone.

    "Today" means the day a transaction was confirmed, not the date printed on the
    receipt, so a receipt from last week that was just uploaded still shows up.

    Args:
        session: Database session.
        timezone: IANA timezone name, such as "Asia/Jakarta".
        now: The current moment; injectable for tests.

    Returns:
        Confirmed transactions, newest first. Pending ones are never included.
    """
    tz = ZoneInfo(timezone)
    local_today = (now or datetime.now(UTC)).astimezone(tz).date()
    start, end = local_day_bounds(local_today, tz)
    rows = await TransactionRepository(session).list_confirmed_between(start, end)
    return _to_read(rows)


async def search_transactions(
    session: AsyncSession, timezone: str, flt: TransactionFilter
) -> list[TransactionRead]:
    """Lists confirmed transactions matching the filter, newest first.

    Date filters apply to the receipt date or to the confirmation day (in the
    user's timezone), depending on `flt.basis`. Both ends are inclusive days.
    """
    tz = ZoneInfo(timezone)
    kwargs: dict = {}
    if flt.basis is DateBasis.CONFIRMED:
        if flt.date_from:
            kwargs["confirmed_from"] = local_day_bounds(flt.date_from, tz)[0]
        if flt.date_to:
            kwargs["confirmed_to"] = local_day_bounds(flt.date_to, tz)[1]
    else:
        kwargs["occurred_from"] = flt.date_from
        kwargs["occurred_to"] = flt.date_to
    rows = await TransactionRepository(session).search_confirmed(
        min_amount=flt.min_amount,
        max_amount=flt.max_amount,
        category_names=flt.categories,
        direction=flt.direction,
        is_transfer=flt.is_transfer,
        **kwargs,
    )
    return _to_read(rows)


async def change_transactions(
    session: AsyncSession,
    ids: list[int],
    category_name: str | None = None,
    direction: Direction | None = None,
    is_transfer: bool | None = None,
) -> int:
    """Changes the category, direction and/or transfer flag of saved transactions.

    All or nothing: if the category or any transaction is unknown (or not saved
    yet), nothing changes. Changing a past transaction also changes how it counts in
    any comparison made later, such as against a budget. The amount is never touched:
    it stays positive, and the direction says which way the money moved.

    Args:
        session: Database session.
        ids: The transactions to change. Duplicates are ignored.
        category_name: The target category, matched ignoring case, or None to leave
            the category alone.
        direction: Whether the money came in or went out, or None to leave it alone.
        is_transfer: True to mark them as moves between the user's own accounts (not
            counted), False to count them again, or None to leave it alone. The
            category is never touched by this.

    Returns:
        How many transactions were changed.

    Raises:
        NotFoundError: If the category does not exist, or any id is not a saved
            transaction.
    """
    wanted = sorted(set(ids))
    values: dict = {}
    if category_name is not None:
        category_id = await CategoryRepository(session).get_id_by_name(category_name)
        if category_id is None:
            raise NotFoundError(f"There is no category called “{category_name}”.")
        values["category_id"] = category_id
    if direction is not None:
        values["direction"] = direction.value
    if is_transfer is not None:
        values["is_transfer"] = is_transfer
    if not values:
        raise NotFoundError("Choose something to change.")
    repo = TransactionRepository(session)
    missing = set(wanted) - await repo.confirmed_ids(wanted)
    if missing:
        shown = ", ".join(str(i) for i in sorted(missing)[:5])
        raise NotFoundError(f"Not a saved transaction: {shown}.")
    return await repo.update_confirmed(wanted, **values)
