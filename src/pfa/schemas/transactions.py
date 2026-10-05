"""Pydantic models for transactions awaiting confirmation."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


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
