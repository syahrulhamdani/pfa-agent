"""Tables for banks, cards, categories, uploads and transactions."""

import enum
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Time,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pfa.models.base import Base


class UploadStatus(enum.StrEnum):
    """Where an upload is in the extraction and confirmation flow."""

    PROCESSING = "processing"
    NEEDS_INPUT = "needs_input"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DONE = "done"
    FAILED = "failed"


class TransactionStatus(enum.StrEnum):
    """Only confirmed transactions count in analytics."""

    PENDING = "pending"
    CONFIRMED = "confirmed"


class Direction(enum.StrEnum):
    """Which way money moved: out is an expense, in is income."""

    OUT = "out"
    IN = "in"


# The category a statement line gets when the model sees money moved between the
# user's own cards, accounts or pockets. It only sets the transfer flag at that moment;
# after that the category and the flag are independent.
TRANSFER_CATEGORY = "Transfer"


class Bank(Base):
    """A bank that owns one or more cards."""

    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Card(Base):
    """A card under a bank."""

    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id"))
    name: Mapped[str] = mapped_column(String(100))
    last4: Mapped[str | None] = mapped_column(String(4))


class Category(Base):
    """A spending category from the seeded list."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)


class Upload(Base):
    """A file the user sent on Telegram."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_message_id: Mapped[int]
    kind: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(30), default=UploadStatus.PROCESSING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Transaction(Base):
    """One transaction. Fields stay null until read or entered by the user."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "direction in ('in', 'out')", name="transactions_direction_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"))
    merchant: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    occurred_on: Mapped[date | None] = mapped_column(Date)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    description: Mapped[str | None] = mapped_column(String(500))
    # The amount is always positive; the direction says whether it came in or went out.
    direction: Mapped[str] = mapped_column(
        String(3), default=Direction.OUT.value, server_default=Direction.OUT.value
    )
    # A move between the user's own cards, accounts or pockets: listed, but never
    # counted as spending or income. Separate from the category, which is kept.
    is_transfer: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    status: Mapped[str] = mapped_column(
        String(20), default=TransactionStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BudgetVersion(Base):
    """One version of a category's budget for a month.

    Editing a budget adds a version and never changes an earlier one, so the history
    stays viewable. The current budget is the highest version.
    """

    __tablename__ = "budget_versions"
    __table_args__ = (
        UniqueConstraint(
            "category_id", "month", "version", name="budget_versions_unique_version"
        ),
        CheckConstraint("amount > 0", name="budget_versions_amount_positive"),
        CheckConstraint("version >= 1", name="budget_versions_version_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    month: Mapped[date] = mapped_column(Date)  # always the first day of the month
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Goal(Base):
    """A savings goal. The saved amount is edited by hand."""

    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint("target_amount > 0", name="goals_target_positive"),
        CheckConstraint("saved_amount >= 0", name="goals_saved_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    target_date: Mapped[date] = mapped_column(Date)
    saved_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WeeklySummary(Base):
    """The summary of one week: the figures it was written from, and the advice.

    There is one per week (the Monday it starts on). The figures are stored as they
    were computed, so what the dashboard shows is exactly what was sent to Telegram.
    """

    __tablename__ = "weekly_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, unique=True)
    stats_json: Mapped[dict] = mapped_column(JSONB)
    recommendations_text: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LoginToken(Base):
    """A sign-in link that has been issued. Each one can be used once."""

    __tablename__ = "login_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuthState(Base):
    """One row holding when sessions were last revoked, for the /signout command."""

    __tablename__ = "auth_state"
    __table_args__ = (CheckConstraint("id = 1", name="auth_state_single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    sessions_valid_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class NudgeSlot(Base):
    """A time of day at which pfa nudges the user to upload receipts."""

    __tablename__ = "nudge_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    time_of_day: Mapped[time] = mapped_column(Time)
    source: Mapped[str] = mapped_column(String(10))  # "default" or "learned"
