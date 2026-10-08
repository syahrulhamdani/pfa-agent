"""Boundary: amounts and dates from a model become safe values or None."""

from datetime import date
from decimal import Decimal

import pytest

from pfa.services.pending import parse_amount, parse_date


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (45000, Decimal("45000.00")),
        (45000.5, Decimal("45000.50")),
        ("12.345", Decimal("12.35")),  # rounds to two decimals
        (Decimal("7"), Decimal("7.00")),
        (0, Decimal("0.00")),
        (-5, Decimal("-5.00")),
    ],
)
def test_parse_amount_accepts_ordinary_numbers(value, expected):
    assert parse_amount(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "abc",
        "",
        "1,000",
        float("nan"),
        float("inf"),
        float("-inf"),
        "NaN",
        "Infinity",
    ],
)
def test_parse_amount_rejects_anything_that_is_not_a_finite_number(value):
    assert parse_amount(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-05", date(2026, 10, 5)),
        (" 2026-10-05 ", date(2026, 10, 5)),
        (date(2026, 10, 5), date(2026, 10, 5)),
        (None, None),
    ],
)
def test_parse_date_accepts_iso_dates(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize("value", ["5 Oct", "2026-02-30", "2026-13-01", "", "tomorrow"])
def test_parse_date_rejects_everything_else(value):
    assert parse_date(value) is None
