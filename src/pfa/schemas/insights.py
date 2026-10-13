"""Pydantic models for the facts behind summaries, recommendations and chat answers.

Every figure pfa tells you is computed in code and held here. The model that writes
the words only ever sees these facts, never the database.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from pfa.schemas.analytics import MoneyTotal, Period

BudgetState = Literal["ok", "near", "over"]


class CategoryLine(BaseModel):
    """One category's share of money out."""

    category: str
    total: Decimal
    count: int
    share: float  # of all money out in the period


class BudgetLine(BaseModel):
    """One category's budget this month and how it stands."""

    category: str
    amount: Decimal
    spent: Decimal
    remaining: Decimal  # negative once over
    used: float  # spent / amount
    state: BudgetState


class GoalLine(BaseModel):
    """One savings goal and the pace it needs."""

    name: str
    saved: Decimal
    target: Decimal
    progress: float
    remaining: Decimal
    days_left: int  # negative once the date has passed
    per_week_needed: Decimal | None  # None when reached or the date has passed


class InsightFacts(BaseModel):
    """Everything pfa may quote about a period, computed and checked in code."""

    label: str
    period: Period
    start: date
    end: date
    partial: bool = False  # the period was still running when this was written
    money_out: Decimal
    money_in: Decimal
    net: Decimal
    out_count: int
    in_count: int
    money_out_change: float | None  # against the period before; None if it had none
    money_in_change: float | None
    transfers: MoneyTotal  # moves between the user's own accounts, in neither total
    top_out: list[CategoryLine]
    focus: CategoryLine | None = None  # the category a question asked about
    focus_name: str | None = None
    budget_month: date | None = None
    budgets: list[BudgetLine] = Field(default_factory=list)
    flags: list[BudgetLine] = Field(default_factory=list)  # worth speaking up about
    unbudgeted_spent: Decimal = Decimal("0.00")
    goals: list[GoalLine] = Field(default_factory=list)

    @property
    def has_activity(self) -> bool:
        """True if anything was recorded in the period."""
        return bool(self.out_count or self.in_count or self.transfers.count)


class WeeklySummaryRead(BaseModel):
    """A saved weekly summary, as the web app and Telegram show it."""

    week_start: date
    week_end: date
    facts: InsightFacts
    recommendations: list[str]
    source: Literal["model", "fallback"] = "model"  # who wrote the recommendations
    created_at: datetime
