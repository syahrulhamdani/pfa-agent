"""Tables for banks, cards, categories, uploads and transactions."""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
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
    file_path: Mapped[str] = mapped_column(String(500))
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

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"))
    merchant: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    occurred_on: Mapped[date | None] = mapped_column(Date)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(20), default=TransactionStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
