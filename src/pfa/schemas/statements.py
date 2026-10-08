"""Pydantic models for reading statements: plain data, no behaviour."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pfa.models.finance import Direction

StatementFormat = Literal["pdf", "csv", "xlsx"]


class ParsedRow(BaseModel):
    """A statement line that is complete enough to save."""

    model_config = ConfigDict(frozen=True)

    merchant: str
    amount: Decimal
    occurred_on: date
    direction: Direction
    category: str | None
    description: str | None


class NormalizedRows(BaseModel):
    """The usable lines of a statement, and how many were set aside and why."""

    model_config = ConfigDict(frozen=True)

    rows: list[ParsedRow]
    skipped_unreadable: int


class Spend(BaseModel):
    """The parts of a transaction that identify it for duplicate checks."""

    model_config = ConfigDict(frozen=True)

    merchant: str
    amount: Decimal
    occurred_on: date
    direction: Direction


class StatementSummary(BaseModel):
    """Count, total, highest and lowest amount of the lines that would be saved."""

    model_config = ConfigDict(frozen=True)

    count: int
    total: Decimal
    highest: Decimal | None
    lowest: Decimal | None


class StatementTotals(BaseModel):
    """The summary of a statement, kept apart for money out and money in."""

    model_config = ConfigDict(frozen=True)

    money_out: StatementSummary
    money_in: StatementSummary
