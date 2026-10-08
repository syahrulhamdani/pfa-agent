"""Loading and editing a pending transaction in the shape the user sees."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfa.models import Category
from pfa.repository.finance import (
    CardRepository,
    CategoryRepository,
    TransactionRepository,
)
from pfa.schemas.transactions import CardOption, PendingTransaction
from pfa.services.cards import infer_card


def parse_date(value: str | date | None) -> date | None:
    """Parses a YYYY-MM-DD string. Returns None if it is not a valid date."""
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def parse_amount(value: float | int | str | Decimal | None) -> Decimal | None:
    """Converts a number to a two-decimal Decimal, rounding half up.

    Returns None for anything that is not a finite number.
    """
    if value is None:
        return None
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    # NaN and infinity do not raise above, but must never be saved as an amount.
    return amount if amount.is_finite() else None


async def load_pending(
    session: AsyncSession, transaction_id: int
) -> PendingTransaction:
    """Builds the user-facing view of a transaction, with names instead of ids."""
    tx = await TransactionRepository(session).get(transaction_id)
    if tx is None:
        raise LookupError(f"transaction {transaction_id} not found")
    category = await session.get(Category, tx.category_id) if tx.category_id else None
    cards = {c.id: c for c in await CardRepository(session).list_options()}
    card = cards.get(tx.card_id) if tx.card_id else None
    return PendingTransaction(
        transaction_id=tx.id,
        merchant=tx.merchant,
        amount=tx.amount,
        occurred_on=tx.occurred_on,
        category=category.name if category else None,
        card_id=tx.card_id,
        card=card.label if card else None,
        description=tx.description,
    )


async def apply_changes(
    session: AsyncSession,
    transaction_id: int,
    changes: dict[str, Any],
    cards: list[CardOption],
) -> list[str]:
    """Applies user corrections to a pending transaction.

    Args:
        session: Database session.
        transaction_id: The pending transaction to edit.
        changes: Any of merchant, amount, occurred_on, category, card, card_id,
            description. Empty values are ignored.
        cards: The user's cards, for resolving a card name or digits.

    Returns:
        Names of the fields that could not be understood, so the user can be told.
    """
    updates: dict[str, Any] = {}
    rejected: list[str] = []
    if changes.get("merchant"):
        updates["merchant"] = changes["merchant"].strip()
    if changes.get("description"):
        updates["description"] = changes["description"].strip()
    if changes.get("amount") is not None:
        amount = parse_amount(changes["amount"])
        if amount is None:
            rejected.append("amount")
        else:
            updates["amount"] = amount
    if changes.get("occurred_on"):
        day = parse_date(changes["occurred_on"])
        if day is None:
            rejected.append("occurred_on")
        else:
            updates["occurred_on"] = day
    if changes.get("category"):
        category_id = await CategoryRepository(session).get_id_by_name(
            changes["category"]
        )
        if category_id is None:
            rejected.append("category")
        else:
            updates["category_id"] = category_id
    if changes.get("card_id") is not None:
        updates["card_id"] = changes["card_id"]
    elif changes.get("card"):
        card_id = infer_card(changes["card"], cards)
        if card_id is None:
            rejected.append("card")
        else:
            updates["card_id"] = card_id
    if updates:
        await TransactionRepository(session).update(transaction_id, **updates)
    return rejected
