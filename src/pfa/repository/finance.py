"""Async repositories for banks, cards, categories, uploads and transactions."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.models import (
    Bank,
    Card,
    Category,
    Transaction,
    TransactionStatus,
    Upload,
    UploadStatus,
)
from pfa.schemas.transactions import CardOption
from pfa.services.cards import card_label


class CategoryRepository:
    """Reads the seeded categories."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def list_all(self) -> list[Category]:
        """Returns every category ordered by name."""
        result = await self._session.scalars(select(Category).order_by(Category.name))
        return list(result)

    async def get_id_by_name(self, name: str) -> int | None:
        """Finds a category id by name, ignoring case."""
        return await self._session.scalar(
            select(Category.id).where(func.lower(Category.name) == name.strip().lower())
        )


class BankRepository:
    """Creates and lists banks."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def add(self, name: str) -> Bank:
        """Creates a bank."""
        bank = Bank(name=name)
        self._session.add(bank)
        await self._session.commit()
        return bank

    async def get(self, bank_id: int) -> Bank | None:
        """Returns a bank by id."""
        return await self._session.get(Bank, bank_id)

    async def get_by_name(self, name: str) -> Bank | None:
        """Returns a bank by exact name."""
        return await self._session.scalar(select(Bank).where(Bank.name == name))

    async def list_all(self) -> list[Bank]:
        """Returns every bank ordered by name."""
        result = await self._session.scalars(select(Bank).order_by(Bank.name))
        return list(result)


class CardRepository:
    """Creates and lists cards."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def add(self, bank_id: int, name: str, last4: str | None) -> Card:
        """Creates a card under a bank."""
        card = Card(bank_id=bank_id, name=name, last4=last4)
        self._session.add(card)
        await self._session.commit()
        return card

    async def list_all(self) -> list[Card]:
        """Returns every card ordered by id."""
        result = await self._session.scalars(select(Card).order_by(Card.id))
        return list(result)

    async def list_options(self) -> list[CardOption]:
        """Returns cards with readable labels for buttons and matching."""
        rows = await self._session.execute(
            select(Card, Bank.name)
            .join(Bank, Bank.id == Card.bank_id)
            .order_by(Card.id)
        )
        return [
            CardOption(
                id=card.id,
                label=card_label(bank_name, card.name, card.last4),
                last4=card.last4,
                bank_name=bank_name,
            )
            for card, bank_name in rows
        ]


class UploadRepository:
    """Tracks files the user sent."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def add(
        self,
        *,
        telegram_message_id: int,
        kind: str,
        filename: str,
        file_path: str,
        mime_type: str,
    ) -> Upload:
        """Records a new upload in the processing state."""
        upload = Upload(
            telegram_message_id=telegram_message_id,
            kind=kind,
            filename=filename,
            file_path=file_path,
            mime_type=mime_type,
            status=UploadStatus.PROCESSING.value,
        )
        self._session.add(upload)
        await self._session.commit()
        return upload

    async def get(self, upload_id: int) -> Upload | None:
        """Returns an upload by id."""
        return await self._session.get(Upload, upload_id)

    async def set_status(self, upload_id: int, status: UploadStatus) -> None:
        """Updates an upload's status."""
        upload = await self._session.get(Upload, upload_id)
        if upload is not None:
            upload.status = status.value
            await self._session.commit()

    async def latest_open(self) -> Upload | None:
        """Returns the newest upload still waiting on the user."""
        open_states = (
            UploadStatus.NEEDS_INPUT.value,
            UploadStatus.AWAITING_CONFIRMATION.value,
        )
        return await self._session.scalar(
            select(Upload)
            .where(Upload.status.in_(open_states))
            .order_by(Upload.id.desc())
        )


class TransactionRepository:
    """Stores pending and confirmed transactions."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def add_pending(self, upload_id: int, **fields: Any) -> Transaction:
        """Creates a pending transaction. Unknown fields stay null."""
        tx = Transaction(
            upload_id=upload_id, status=TransactionStatus.PENDING.value, **fields
        )
        self._session.add(tx)
        await self._session.commit()
        return tx

    async def get(self, transaction_id: int) -> Transaction | None:
        """Returns a transaction by id."""
        return await self._session.get(Transaction, transaction_id)

    async def update(self, transaction_id: int, **fields: Any) -> None:
        """Sets the given fields on a transaction."""
        tx = await self._session.get(Transaction, transaction_id)
        if tx is None:
            return
        for name, value in fields.items():
            setattr(tx, name, value)
        await self._session.commit()

    async def confirm(self, transaction_id: int) -> None:
        """Flips a pending transaction to confirmed."""
        await self.update(
            transaction_id,
            status=TransactionStatus.CONFIRMED.value,
            confirmed_at=datetime.now(UTC),
        )

    async def list_by_status(self, status: TransactionStatus) -> list[Transaction]:
        """Returns transactions in a status, oldest first."""
        result = await self._session.scalars(
            select(Transaction)
            .where(Transaction.status == status.value)
            .order_by(Transaction.id)
        )
        return list(result)

    async def search_confirmed(
        self,
        *,
        confirmed_from: datetime | None = None,
        confirmed_to: datetime | None = None,
        occurred_from: date | None = None,
        occurred_to: date | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        category_names: list[str] | None = None,
        limit: int = 500,
    ) -> list[tuple[Transaction, str | None, str | None]]:
        """Searches confirmed transactions, newest confirmation first.

        Ranges are inclusive at the start and exclusive at the end for
        `confirmed_*`, and inclusive on both ends for `occurred_*`.

        Returns:
            Rows of the transaction, its category name and its card label.
        """
        conditions = [Transaction.status == TransactionStatus.CONFIRMED.value]
        if confirmed_from is not None:
            conditions.append(Transaction.confirmed_at >= confirmed_from)
        if confirmed_to is not None:
            conditions.append(Transaction.confirmed_at < confirmed_to)
        if occurred_from is not None:
            conditions.append(Transaction.occurred_on >= occurred_from)
        if occurred_to is not None:
            conditions.append(Transaction.occurred_on <= occurred_to)
        if min_amount is not None:
            conditions.append(Transaction.amount >= min_amount)
        if max_amount is not None:
            conditions.append(Transaction.amount <= max_amount)
        if category_names:
            conditions.append(Category.name.in_(category_names))
        rows = await self._session.execute(
            select(Transaction, Category.name, Bank.name, Card.name, Card.last4)
            .outerjoin(Category, Category.id == Transaction.category_id)
            .outerjoin(Card, Card.id == Transaction.card_id)
            .outerjoin(Bank, Bank.id == Card.bank_id)
            .where(*conditions)
            .order_by(Transaction.confirmed_at.desc(), Transaction.id.desc())
            .limit(limit)
        )
        return [
            (
                tx,
                category,
                card_label(bank, card, last4) if card is not None else None,
            )
            for tx, category, bank, card, last4 in rows
        ]

    async def list_confirmed_between(
        self, start: datetime, end: datetime
    ) -> list[tuple[Transaction, str | None, str | None]]:
        """Returns transactions confirmed in [start, end), newest first."""
        return await self.search_confirmed(confirmed_from=start, confirmed_to=end)
