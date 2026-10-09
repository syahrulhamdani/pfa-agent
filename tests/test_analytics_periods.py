"""Boundary: which dates a period covers, and how an anchor date moves between them."""

from datetime import date
from decimal import Decimal

import pytest

from pfa.schemas.analytics import Period
from pfa.services.analytics import (
    add_months,
    bucket_for,
    bucket_starts,
    percent_change,
    period_bounds,
    shift_anchor,
)

D = date


@pytest.mark.parametrize(
    ("period", "anchor", "expected"),
    [
        (Period.DAY, D(2026, 10, 5), (D(2026, 10, 5), D(2026, 10, 5))),
        # Weeks run Monday to Sunday. 2026-10-05 is a Monday.
        (Period.WEEK, D(2026, 10, 5), (D(2026, 10, 5), D(2026, 10, 11))),
        (Period.WEEK, D(2026, 10, 8), (D(2026, 10, 5), D(2026, 10, 11))),
        (Period.WEEK, D(2026, 10, 11), (D(2026, 10, 5), D(2026, 10, 11))),  # Sunday
        (
            Period.WEEK,
            D(2026, 10, 4),
            (D(2026, 9, 28), D(2026, 10, 4)),
        ),  # crosses a month
        (
            Period.WEEK,
            D(2026, 1, 1),
            (D(2025, 12, 29), D(2026, 1, 4)),
        ),  # crosses a year
        (Period.MONTH, D(2026, 10, 17), (D(2026, 10, 1), D(2026, 10, 31))),
        (Period.MONTH, D(2026, 2, 28), (D(2026, 2, 1), D(2026, 2, 28))),
        (Period.MONTH, D(2028, 2, 10), (D(2028, 2, 1), D(2028, 2, 29))),  # leap year
        (Period.MONTH, D(2026, 12, 31), (D(2026, 12, 1), D(2026, 12, 31))),
        (Period.QUARTER, D(2026, 1, 1), (D(2026, 1, 1), D(2026, 3, 31))),
        (Period.QUARTER, D(2026, 3, 31), (D(2026, 1, 1), D(2026, 3, 31))),
        (Period.QUARTER, D(2026, 4, 1), (D(2026, 4, 1), D(2026, 6, 30))),
        (Period.QUARTER, D(2026, 10, 9), (D(2026, 10, 1), D(2026, 12, 31))),
        (Period.QUARTER, D(2026, 12, 31), (D(2026, 10, 1), D(2026, 12, 31))),
        (Period.YEAR, D(2026, 6, 15), (D(2026, 1, 1), D(2026, 12, 31))),
    ],
)
def test_period_bounds(period, anchor, expected):
    assert period_bounds(period, anchor) == expected


@pytest.mark.parametrize("period", list(Period))
@pytest.mark.parametrize(
    "anchor", [D(2026, 1, 1), D(2026, 2, 28), D(2028, 2, 29), D(2026, 12, 31)]
)
def test_the_anchor_is_always_inside_its_own_period(period, anchor):
    start, end = period_bounds(period, anchor)
    assert start <= anchor <= end


@pytest.mark.parametrize("period", list(Period))
def test_consecutive_periods_neither_overlap_nor_leave_a_gap(period):
    anchor = D(2026, 10, 9)
    for steps in range(-5, 5):
        _, end = period_bounds(period, shift_anchor(period, anchor, steps))
        next_start, _ = period_bounds(period, shift_anchor(period, anchor, steps + 1))
        assert (next_start - end).days == 1


@pytest.mark.parametrize(
    ("day", "months", "expected"),
    [
        (D(2026, 1, 31), 1, D(2026, 2, 28)),  # clamps to the end of a short month
        (D(2028, 1, 31), 1, D(2028, 2, 29)),  # ...including a leap February
        (D(2026, 12, 15), 1, D(2027, 1, 15)),  # across a year
        (D(2026, 1, 15), -1, D(2025, 12, 15)),
        (D(2026, 3, 31), -1, D(2026, 2, 28)),
        (D(2026, 5, 31), 0, D(2026, 5, 31)),
        (D(2026, 10, 9), 24, D(2028, 10, 9)),
        (D(2026, 10, 9), -13, D(2025, 9, 9)),
    ],
)
def test_add_months(day, months, expected):
    assert add_months(day, months) == expected


@pytest.mark.parametrize(
    ("period", "anchor", "steps", "expected"),
    [
        (Period.DAY, D(2026, 3, 1), -1, D(2026, 2, 28)),
        (Period.DAY, D(2026, 12, 31), 1, D(2027, 1, 1)),
        (Period.WEEK, D(2026, 10, 9), -1, D(2026, 10, 2)),
        (Period.WEEK, D(2026, 10, 9), 2, D(2026, 10, 23)),
        (Period.MONTH, D(2026, 3, 31), -1, D(2026, 2, 28)),
        (Period.QUARTER, D(2026, 10, 9), -1, D(2026, 7, 9)),
        (Period.QUARTER, D(2026, 11, 30), 1, D(2027, 2, 28)),
        (Period.YEAR, D(2028, 2, 29), 1, D(2029, 2, 28)),  # a leap day has no next year
        (Period.YEAR, D(2026, 10, 9), -1, D(2025, 10, 9)),
        (Period.MONTH, D(2026, 10, 9), 0, D(2026, 10, 9)),
    ],
)
def test_shift_anchor(period, anchor, steps, expected):
    assert shift_anchor(period, anchor, steps) == expected


def test_the_previous_period_is_the_one_just_before():
    anchor = D(2026, 10, 9)
    assert period_bounds(Period.QUARTER, shift_anchor(Period.QUARTER, anchor, -1)) == (
        D(2026, 7, 1),
        D(2026, 9, 30),
    )
    assert period_bounds(
        Period.MONTH, shift_anchor(Period.MONTH, D(2026, 1, 20), -1)
    ) == (
        D(2025, 12, 1),
        D(2025, 12, 31),
    )


def test_how_each_period_is_charted():
    assert bucket_for(Period.DAY) is None
    assert bucket_for(Period.WEEK) == "day"
    assert bucket_for(Period.MONTH) == "day"
    assert bucket_for(Period.QUARTER) == "week"
    assert bucket_for(Period.YEAR) == "month"


def test_a_months_daily_buckets_cover_every_day():
    starts = bucket_starts(D(2026, 2, 1), D(2026, 2, 28), "day")
    assert len(starts) == 28
    assert starts[0] == D(2026, 2, 1)
    assert starts[-1] == D(2026, 2, 28)
    assert len(bucket_starts(D(2028, 2, 1), D(2028, 2, 29), "day")) == 29


def test_weekly_buckets_start_on_mondays_and_may_begin_before_the_period():
    starts = bucket_starts(
        D(2026, 10, 1), D(2026, 12, 31), "week"
    )  # Oct 1 is a Thursday
    assert starts[0] == D(2026, 9, 28)  # the Monday of the week the quarter starts in
    assert all(s.weekday() == 0 for s in starts)
    assert all((b - a).days == 7 for a, b in zip(starts, starts[1:], strict=False))
    assert starts[-1] <= D(2026, 12, 31)
    assert len(starts) == 14


def test_a_year_has_twelve_monthly_buckets():
    starts = bucket_starts(D(2026, 1, 1), D(2026, 12, 31), "month")
    assert starts == [D(2026, m, 1) for m in range(1, 13)]


def test_a_single_day_bucket():
    assert bucket_starts(D(2026, 10, 5), D(2026, 10, 5), "day") == [D(2026, 10, 5)]


# --- how much a figure changed ---


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (Decimal("100"), Decimal("150"), 0.5),
        (Decimal("100"), Decimal("50"), -0.5),
        (Decimal("100"), Decimal("100"), 0.0),
        (Decimal("80"), Decimal("375"), 3.6875),
        (Decimal("200"), Decimal("0"), -1.0),
    ],
)
def test_percent_change_is_a_fraction(previous, current, expected):
    assert percent_change(previous, current) == pytest.approx(expected)


def test_a_change_from_nothing_has_no_percentage_by_default():
    """The default rule; update this test if you change `percent_change`."""
    assert percent_change(Decimal("0"), Decimal("100")) is None
    assert percent_change(Decimal("0.00"), Decimal("0")) is None
