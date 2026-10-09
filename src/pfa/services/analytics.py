"""Dashboard figures: which dates a period covers, and how the numbers are put together.

Spending means money out only. Money in is reported beside it, never netted into it,
and moves between the user's own accounts (the Transfer category) are reported on
their own and left out of both. Periods are by the date on the receipt, because the
dashboard answers "when did the money move", not "when did I tell pfa".
"""

import calendar
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from pfa.models import Direction
from pfa.repository.analytics import AnalyticsRepository
from pfa.schemas.analytics import (
    AnalyticsRead,
    Bucket,
    CategoryShare,
    MoneyTotal,
    Period,
    PeriodComparison,
    SeriesPoint,
)

ZERO = Decimal("0.00")


def today_in(timezone: str, now: datetime | None = None) -> date:
    """Returns today's date in the user's timezone."""
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(timezone)).date()


def add_months(day: date, months: int) -> date:
    """Moves a date by whole months, clamping the day (31 Jan + 1 month = 28 Feb)."""
    year, month_index = divmod(day.year * 12 + (day.month - 1) + months, 12)
    month = month_index + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def period_bounds(period: Period, anchor: date) -> tuple[date, date]:
    """Returns the first and last day (inclusive) of the period containing `anchor`."""
    if period is Period.DAY:
        return anchor, anchor
    if period is Period.WEEK:
        start = anchor - timedelta(days=anchor.weekday())  # Monday
        return start, start + timedelta(days=6)
    if period is Period.MONTH:
        last = calendar.monthrange(anchor.year, anchor.month)[1]
        return anchor.replace(day=1), anchor.replace(day=last)
    if period is Period.QUARTER:
        first_month = 3 * ((anchor.month - 1) // 3) + 1
        last_month = first_month + 2
        last = calendar.monthrange(anchor.year, last_month)[1]
        return date(anchor.year, first_month, 1), date(anchor.year, last_month, last)
    return date(anchor.year, 1, 1), date(anchor.year, 12, 31)


def shift_anchor(period: Period, anchor: date, steps: int) -> date:
    """Moves an anchor date forwards (positive) or backwards by whole periods."""
    if period is Period.DAY:
        return anchor + timedelta(days=steps)
    if period is Period.WEEK:
        return anchor + timedelta(weeks=steps)
    if period is Period.MONTH:
        return add_months(anchor, steps)
    if period is Period.QUARTER:
        return add_months(anchor, 3 * steps)
    return add_months(anchor, 12 * steps)


def bucket_for(period: Period) -> Bucket | None:
    """Says how a period's chart is cut up: a bar per day, week or month."""
    return {
        Period.DAY: None,
        Period.WEEK: "day",
        Period.MONTH: "day",
        Period.QUARTER: "week",
        Period.YEAR: "month",
    }[period]


def bucket_starts(start: date, end: date, bucket: Bucket) -> list[date]:
    """Lists the start of every bucket in the range, empty ones included."""
    starts: list[date] = []
    if bucket == "day":
        current = start
        while current <= end:
            starts.append(current)
            current += timedelta(days=1)
    elif bucket == "week":
        current = start - timedelta(days=start.weekday())
        while current <= end:
            starts.append(current)
            current += timedelta(days=7)
    else:
        current = start.replace(day=1)
        while current <= end:
            starts.append(current)
            current = add_months(current, 1)
    return starts


def percent_change(previous: Decimal, current: Decimal) -> float | None:
    """Says how much `current` differs from `previous`, as a fraction.

    0.25 means 25% more, -0.5 means half as much.

    Returns:
        The fraction, or None when there is no meaningful comparison.
    """
    if previous == 0:
        return None
    return float((current - previous) / previous)


def _shares(
    rows: list[tuple[Direction, str, int, Decimal]], direction: Direction
) -> list[CategoryShare]:
    side = [(name, count, total) for d, name, count, total in rows if d is direction]
    grand_total = sum((total for _, _, total in side), ZERO)
    if grand_total == 0:
        return []
    return [
        CategoryShare(
            category=name,
            total=total,
            count=count,
            share=round(float(total / grand_total), 4),
        )
        for name, count, total in side
    ]


async def build_analytics(
    session: AsyncSession, period: Period, anchor: date
) -> AnalyticsRead:
    """Assembles the dashboard for the period containing `anchor`.

    Args:
        session: Database session.
        period: How wide a view to build.
        anchor: Any date inside the period wanted.

    Returns:
        Totals, the per-category split of money out and money in, a chart series with
        no gaps, the Transfer total, and a comparison with the previous period.
    """
    repo = AnalyticsRepository(session)
    start, end = period_bounds(period, anchor)
    previous_start, previous_end = period_bounds(
        period, shift_anchor(period, anchor, -1)
    )

    totals = await repo.totals_by_direction(start, end)
    previous_totals = await repo.totals_by_direction(previous_start, previous_end)
    transfer_count, transfer_total = await repo.transfer_totals(start, end)
    categories = await repo.by_category(start, end)

    bucket = bucket_for(period)
    series: list[SeriesPoint] = []
    if bucket is not None:
        found = {
            (day, d): total for day, d, total in await repo.series(start, end, bucket)
        }
        series = [
            SeriesPoint(
                start=day,
                money_out=found.get((day, Direction.OUT), ZERO),
                money_in=found.get((day, Direction.IN), ZERO),
            )
            for day in bucket_starts(start, end, bucket)
        ]

    out_count, out_total = totals[Direction.OUT]
    in_count, in_total = totals[Direction.IN]
    previous_out = previous_totals[Direction.OUT][1]
    previous_in = previous_totals[Direction.IN][1]
    return AnalyticsRead(
        period=period,
        start=start,
        end=end,
        bucket=bucket,
        money_out=MoneyTotal(total=out_total, count=out_count),
        money_in=MoneyTotal(total=in_total, count=in_count),
        net=in_total - out_total,
        transfers=MoneyTotal(total=transfer_total, count=transfer_count),
        out_by_category=_shares(categories, Direction.OUT),
        in_by_category=_shares(categories, Direction.IN),
        series=series,
        previous=PeriodComparison(
            start=previous_start,
            end=previous_end,
            money_out=previous_out,
            money_in=previous_in,
            money_out_change=_rounded(percent_change(previous_out, out_total)),
            money_in_change=_rounded(percent_change(previous_in, in_total)),
        ),
    )


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 4)
