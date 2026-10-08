"""Boundary: the domain value objects are immutable and validate what they hold."""

from datetime import date, time
from decimal import Decimal

import pytest
from pydantic import ValidationError

from pfa.models.finance import Direction
from pfa.schemas.auth import TokenType
from pfa.schemas.nudges import Slot, SlotSource
from pfa.schemas.statements import (
    NormalizedRows,
    ParsedRow,
    Spend,
    StatementSummary,
)


def spend(**overrides) -> Spend:
    base = {
        "merchant": "Kopi",
        "amount": Decimal("5.00"),
        "occurred_on": date(2026, 10, 1),
        "direction": Direction.OUT,
    }
    return Spend(**{**base, **overrides})


@pytest.mark.parametrize(
    "build",
    [
        lambda: spend(),
        lambda: Slot(at=time(8), source=SlotSource.DEFAULT),
        lambda: StatementSummary(
            count=1, total=Decimal("1"), highest=None, lowest=None
        ),
        lambda: NormalizedRows(rows=[], skipped_unreadable=0),
    ],
    ids=["Spend", "Slot", "StatementSummary", "NormalizedRows"],
)
def test_value_objects_cannot_be_changed_after_creation(build):
    value = build()
    field = next(iter(type(value).model_fields))
    with pytest.raises(ValidationError, match="frozen"):
        setattr(value, field, None)


def test_equal_values_are_equal_and_hashable():
    assert spend() == spend()
    assert spend() != spend(amount=Decimal("6.00"))
    slots = {Slot(at=time(8), source=SlotSource.LEARNED)}
    assert Slot(at=time(8), source=SlotSource.LEARNED) in slots  # usable in sets


def test_amounts_are_coerced_to_decimal_and_garbage_is_rejected():
    assert spend(amount="12.50").amount == Decimal("12.50")
    assert isinstance(spend(amount=7).amount, Decimal)
    with pytest.raises(ValidationError):
        spend(amount="a lot")


def test_dates_are_validated():
    assert spend(occurred_on="2026-10-01").occurred_on == date(2026, 10, 1)
    with pytest.raises(ValidationError):
        spend(occurred_on="2026-02-30")


def test_a_slot_only_accepts_a_real_source_and_time():
    assert Slot(at="07:30:00", source="learned").source is SlotSource.LEARNED
    with pytest.raises(ValidationError):
        Slot(at=time(8), source="guessed")
    with pytest.raises(ValidationError):
        Slot(at="25:00", source=SlotSource.DEFAULT)


def test_a_parsed_row_requires_its_core_fields():
    with pytest.raises(ValidationError):
        ParsedRow(
            merchant="Kopi",
            amount=Decimal("5"),
            direction=Direction.OUT,
            category=None,
            description=None,
        )


def test_token_types_are_the_two_known_kinds():
    assert {t.value for t in TokenType} == {"login", "session"}
    assert TokenType("login") is TokenType.LOGIN
    with pytest.raises(ValueError):
        TokenType("admin")


def test_a_direction_is_one_of_in_or_out():
    assert {d.value for d in Direction} == {"in", "out"}
    assert spend(direction="in").direction is Direction.IN
    with pytest.raises(ValidationError):
        spend(direction="sideways")
    with pytest.raises(ValidationError):
        spend(direction=None)
