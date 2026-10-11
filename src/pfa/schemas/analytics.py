"""Pydantic models for the dashboard's aggregated figures."""

import enum
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from pfa.schemas.budgets import BudgetsRead


class Period(enum.StrEnum):
    """The span of time a dashboard view covers."""

    DAY = "day"
    WEEK = "week"  # Monday to Sunday
    MONTH = "month"
    QUARTER = "quarter"  # calendar quarters: Jan-Mar, Apr-Jun, Jul-Sep, Oct-Dec
    YEAR = "year"


Bucket = Literal["day", "week", "month"]


class MoneyTotal(BaseModel):
    """How many transactions there were, and what they add up to."""

    total: Decimal
    count: int


class CategoryShare(BaseModel):
    """One category's part of money out or money in."""

    category: str
    total: Decimal
    count: int
    share: float  # a fraction of that side's total: 0.25 means a quarter


class SeriesPoint(BaseModel):
    """Money out and money in for one bucket of time within the period."""

    start: date
    money_out: Decimal
    money_in: Decimal


class PeriodComparison(BaseModel):
    """The period just before, and how this one changed against it."""

    start: date
    end: date
    money_out: Decimal
    money_in: Decimal
    # Fractions, e.g. 0.25 is 25% more. None when there is nothing to compare with.
    money_out_change: float | None
    money_in_change: float | None


class AnalyticsRead(BaseModel):
    """Everything the dashboard shows for one period.

    Money out and money in are always separate, and moves between the user's own
    accounts (the Transfer category) are reported on their own and left out of both.
    """

    period: Period
    start: date
    end: date  # inclusive
    bucket: Bucket | None  # how `series` is cut up; None for a single day
    money_out: MoneyTotal
    money_in: MoneyTotal
    net: Decimal
    transfers: MoneyTotal
    out_by_category: list[CategoryShare]
    in_by_category: list[CategoryShare]
    series: list[SeriesPoint]
    previous: PeriodComparison
    # Budgets and what is left of them: only for a month, the unit budgets are set in.
    budgets: BudgetsRead | None = None
