"""Pydantic models for transactions."""

import enum
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from pfa.models.finance import Direction


class CardOption(BaseModel):
    """A card the user can pick, with a readable label."""

    id: int
    label: str
    last4: str | None = None
    bank_name: str = ""


class PendingTransaction(BaseModel):
    """A transaction as shown to the user for confirmation."""

    transaction_id: int
    merchant: str | None = None
    amount: Decimal | None = None
    occurred_on: date | None = None
    category: str | None = None
    card_id: int | None = None
    card: str | None = None
    description: str | None = None


class TransactionRead(BaseModel):
    """A confirmed transaction as shown in the web app."""

    id: int
    merchant: str | None
    amount: Decimal | None
    occurred_on: date | None
    category: str | None
    card: str | None
    description: str | None
    direction: Direction
    # Moves between the user's own accounts: shown, but not counted in totals.
    is_transfer: bool
    confirmed_at: datetime | None


class DateBasis(enum.StrEnum):
    """Which date a date filter applies to."""

    OCCURRED = "occurred"  # the date on the receipt
    CONFIRMED = "confirmed"  # the day the user confirmed it


class TransactionFilter(BaseModel):
    """Filters for listing confirmed transactions. Every field is optional."""

    basis: DateBasis = DateBasis.OCCURRED
    date_from: date | None = None
    date_to: date | None = None
    min_amount: Decimal | None = Field(None, ge=0)
    max_amount: Decimal | None = Field(None, ge=0)
    categories: list[str] = Field(default_factory=list)
    direction: Direction | None = None  # None means money in and money out

    @model_validator(mode="after")
    def _ranges_make_sense(self) -> "TransactionFilter":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount must not exceed max_amount")
        return self


class TransactionChange(BaseModel):
    """A request to change saved transactions: their category, direction, or both."""

    ids: list[int] = Field(min_length=1, max_length=500)
    category: str | None = Field(None, min_length=1, max_length=50)
    direction: Direction | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "TransactionChange":
        if self.category is None and self.direction is None:
            raise ValueError("choose a category, a direction, or both")
        return self


class TransactionsChanged(BaseModel):
    """How many transactions were changed."""

    updated: int
