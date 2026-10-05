"""Which required fields of a pending transaction still need the user."""

from datetime import date

from pfa.schemas.transactions import PendingTransaction

REQUIRED_FIELDS = ("merchant", "amount", "occurred_on", "category", "card")


def missing_fields(tx: PendingTransaction, today: date) -> list[str]:
    """Lists required fields that are empty or unusable.

    A transaction can only be confirmed when this returns an empty list.

    Args:
        tx: The pending transaction.
        today: The current date, passed in so tests control it.

    Returns:
        Field names from REQUIRED_FIELDS that the user must supply.
    """
    missing = [
        name
        for name in REQUIRED_FIELDS
        if (tx.card_id if name == "card" else getattr(tx, name)) is None
    ]
    # Present but implausible values are treated as unreadable, so the user is asked.
    if tx.occurred_on is not None and tx.occurred_on > today:
        missing.append("occurred_on")
    if tx.amount is not None and tx.amount <= 0:
        missing.append("amount")
    return missing
