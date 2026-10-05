"""Boundary: only a fully populated transaction can be confirmed."""

from datetime import date
from decimal import Decimal

from pfa.schemas.transactions import PendingTransaction
from pfa.services.validation import missing_fields

TODAY = date(2026, 10, 5)


def tx(**overrides) -> PendingTransaction:
    base = {
        "transaction_id": 1,
        "merchant": "Indomaret",
        "amount": Decimal("45000.00"),
        "occurred_on": date(2026, 10, 4),
        "category": "Groceries",
        "card_id": 1,
        "card": "BCA Visa 1234",
    }
    return PendingTransaction(**{**base, **overrides})


def test_complete_transaction_has_nothing_missing():
    assert missing_fields(tx(), TODAY) == []


def test_description_is_optional():
    assert missing_fields(tx(description=None), TODAY) == []


def test_each_required_field_is_reported():
    empty = tx(
        merchant=None, amount=None, occurred_on=None, category=None, card_id=None
    )
    assert missing_fields(empty, TODAY) == [
        "merchant",
        "amount",
        "occurred_on",
        "category",
        "card",
    ]


def test_future_date_is_treated_as_missing():
    assert missing_fields(tx(occurred_on=date(2026, 10, 6)), TODAY) == ["occurred_on"]


def test_todays_date_is_allowed():
    assert missing_fields(tx(occurred_on=TODAY), TODAY) == []


def test_zero_or_negative_amount_is_treated_as_missing():
    assert missing_fields(tx(amount=Decimal("0")), TODAY) == ["amount"]
    assert missing_fields(tx(amount=Decimal("-5.00")), TODAY) == ["amount"]


def test_empty_values_are_reported_once_and_do_not_crash():
    result = missing_fields(tx(amount=None, occurred_on=None), TODAY)
    assert result == ["amount", "occurred_on"]


def test_bad_amount_and_future_date_are_both_reported():
    result = missing_fields(
        tx(amount=Decimal("0"), occurred_on=date(2027, 1, 1)), TODAY
    )
    assert sorted(result) == ["amount", "occurred_on"]
