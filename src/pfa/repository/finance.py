"""Async repositories for banks, cards, categories, uploads and transactions."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.models import (
    AuthState,
    Bank,
    Card,
    Category,
    Direction,
    LoginToken,
    NudgeSlot,
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
        mime_type: str,
    ) -> Upload:
        """Records a new upload in the processing state."""
        upload = Upload(
            telegram_message_id=telegram_message_id,
            kind=kind,
            filename=filename,
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
        direction: Direction | None = None,
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
        if direction is not None:
            conditions.append(Transaction.direction == direction.value)
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

    async def add_pending_many(
        self, upload_id: int, card_id: int | None, rows: list[dict[str, Any]]
    ) -> list[Transaction]:
        """Creates pending transactions for every line of a statement."""
        created = [
            Transaction(
                upload_id=upload_id,
                card_id=card_id,
                status=TransactionStatus.PENDING.value,
                **row,
            )
            for row in rows
        ]
        self._session.add_all(created)
        await self._session.commit()
        return created

    async def pending_for_upload(self, upload_id: int) -> list[Transaction]:
        """Returns an upload's pending transactions in the order they were read."""
        result = await self._session.scalars(
            select(Transaction)
            .where(
                Transaction.upload_id == upload_id,
                Transaction.status == TransactionStatus.PENDING.value,
            )
            .order_by(Transaction.id)
        )
        return list(result)

    async def set_card_for_upload(self, upload_id: int, card_id: int) -> None:
        """Assigns one card to every pending transaction of an upload."""
        await self._session.execute(
            update(Transaction)
            .where(
                Transaction.upload_id == upload_id,
                Transaction.status == TransactionStatus.PENDING.value,
            )
            .values(card_id=card_id)
        )
        await self._session.commit()

    async def confirmed_on_card_between(
        self, card_id: int, start: date, end: date
    ) -> list[Transaction]:
        """Returns confirmed transactions on a card dated within [start, end]."""
        result = await self._session.scalars(
            select(Transaction).where(
                Transaction.status == TransactionStatus.CONFIRMED.value,
                Transaction.card_id == card_id,
                Transaction.occurred_on >= start,
                Transaction.occurred_on <= end,
            )
        )
        return list(result)

    async def delete_many(self, ids: list[int]) -> None:
        """Deletes transactions by id."""
        if ids:
            await self._session.execute(
                delete(Transaction).where(Transaction.id.in_(ids))
            )
            await self._session.commit()

    async def confirm_many(self, ids: list[int]) -> None:
        """Flips the given pending transactions to confirmed."""
        if ids:
            await self._session.execute(
                update(Transaction)
                .where(Transaction.id.in_(ids))
                .values(
                    status=TransactionStatus.CONFIRMED.value,
                    confirmed_at=datetime.now(UTC),
                )
            )
            await self._session.commit()

    async def confirmed_times(self) -> list[datetime]:
        """Returns when each confirmed transaction was confirmed, oldest first."""
        result = await self._session.scalars(
            select(Transaction.confirmed_at)
            .where(
                Transaction.status == TransactionStatus.CONFIRMED.value,
                Transaction.confirmed_at.is_not(None),
            )
            .order_by(Transaction.confirmed_at)
        )
        return list(result)

    async def list_confirmed_between(
        self, start: datetime, end: datetime
    ) -> list[tuple[Transaction, str | None, str | None]]:
        """Returns transactions confirmed in [start, end), newest first."""
        return await self.search_confirmed(confirmed_from=start, confirmed_to=end)


class LoginTokenRepository:
    """Tracks issued sign-in links so each works only once."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def add(self, jti: str, expires_at: datetime, now: datetime) -> None:
        """Records a newly issued link and drops long-expired ones."""
        await self._session.execute(
            delete(LoginToken).where(LoginToken.expires_at < now - timedelta(days=1))
        )
        self._session.add(LoginToken(jti=jti, expires_at=expires_at))
        await self._session.commit()

    async def consume(self, jti: str, now: datetime) -> bool:
        """Marks a link used if it is known, unused and unexpired.

        The check and the update are one statement, so two simultaneous requests
        with the same link cannot both succeed.

        Returns:
            True if this call used the link; False otherwise.
        """
        result = await self._session.execute(
            update(LoginToken)
            .where(
                LoginToken.jti == jti,
                LoginToken.used_at.is_(None),
                LoginToken.expires_at > now,
            )
            .values(used_at=now)
        )
        await self._session.commit()
        return result.rowcount == 1

    async def expire_unused(self, now: datetime) -> None:
        """Marks every unused link as used, so none can be exchanged any more."""
        await self._session.execute(
            update(LoginToken).where(LoginToken.used_at.is_(None)).values(used_at=now)
        )
        await self._session.commit()


class AuthStateRepository:
    """Remembers when all sessions were last revoked."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def sessions_valid_after(self) -> datetime | None:
        """Returns the revocation time, or None if sessions were never revoked."""
        return await self._session.scalar(select(AuthState.sessions_valid_after))

    async def revoke_sessions(self, now: datetime) -> None:
        """Rejects every session issued up to now."""
        stmt = insert(AuthState).values(id=1, sessions_valid_after=now)
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=["id"], set_={"sessions_valid_after": now}
            )
        )
        await self._session.commit()


class NudgeSlotRepository:
    """Stores the times of day pfa nudges at."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def list_all(self) -> list[NudgeSlot]:
        """Returns the current slots, earliest first."""
        result = await self._session.scalars(
            select(NudgeSlot).order_by(NudgeSlot.time_of_day)
        )
        return list(result)

    async def replace_all(self, slots: list[tuple[time, str]]) -> None:
        """Replaces every slot with the given (time, source) pairs, atomically."""
        await self._session.execute(delete(NudgeSlot))
        self._session.add_all(
            NudgeSlot(time_of_day=at, source=source) for at, source in slots
        )
        await self._session.commit()
