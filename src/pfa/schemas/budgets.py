"""Pydantic models for budgets and savings goals."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Money in this app has two decimals and fits Numeric(14, 2).
Money = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
SavedMoney = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
GoalName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
MonthText = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class BudgetSet(BaseModel):
    """Sets a category's budget for a month; every call adds a new version."""

    category: str = Field(min_length=1, max_length=50)
    month: MonthText
    amount: Money


class BudgetRead(BaseModel):
    """A category's current budget for a month, and how much of it is used."""

    category: str
    month: date  # the month asked for
    set_for: date  # the month whose budget applies (differs only if carried over)
    amount: Decimal
    version: int
    spent: Decimal  # money out in the month, not counting moves between own accounts
    remaining: Decimal  # negative once the budget is exceeded
    used: float  # spent / amount; above 1 means over budget


class BudgetsRead(BaseModel):
    """Every budget that applies to a month, with totals."""

    month: date
    items: list[BudgetRead]
    total_budget: Decimal
    total_spent: Decimal  # spent in budgeted categories only
    total_remaining: Decimal
    unbudgeted_spent: Decimal  # money out in categories with no budget


class BudgetsCopy(BaseModel):
    """Copies one month's budgets into another."""

    from_month: MonthText
    to_month: MonthText

    @model_validator(mode="after")
    def _different_months(self) -> "BudgetsCopy":
        if self.from_month == self.to_month:
            raise ValueError("choose two different months")
        return self


class BudgetsCopied(BaseModel):
    """What a copy did."""

    copied: int  # budgets created in the target month
    skipped: int  # categories that already had a budget there, left as they were


class BudgetVersionRead(BaseModel):
    """One saved version of a budget."""

    version: int
    amount: Decimal
    created_at: datetime
    current: bool


class GoalCreate(BaseModel):
    """A new savings goal."""

    name: GoalName
    target_amount: Money
    target_date: Annotated[date, Field(ge=date(1970, 1, 1), le=date(2100, 12, 31))]
    saved_amount: SavedMoney = Decimal("0.00")


class GoalUpdate(BaseModel):
    """Changes to a goal. Send only what changes."""

    name: GoalName | None = None
    target_amount: Money | None = None
    target_date: (
        Annotated[date, Field(ge=date(1970, 1, 1), le=date(2100, 12, 31))] | None
    ) = None
    saved_amount: SavedMoney | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "GoalUpdate":
        if all(v is None for v in self.model_dump().values()):
            raise ValueError("choose something to change")
        return self


class GoalRead(BaseModel):
    """A goal with its progress."""

    id: int
    name: str
    target_amount: Decimal
    target_date: date
    saved_amount: Decimal
    progress: float  # saved / target; above 1 once the goal is passed
    remaining: Decimal  # never negative
    days_left: int  # negative once the target date has passed
