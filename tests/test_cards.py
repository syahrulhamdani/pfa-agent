"""Boundary: a receipt hint maps to one card, or to none when unsure."""

import pytest

from pfa.schemas.transactions import CardOption
from pfa.services.cards import infer_card

CARDS = [
    CardOption(id=1, label="BCA Visa 1234", last4="1234", bank_name="BCA"),
    CardOption(id=2, label="BCA Gold 9999", last4="9999", bank_name="BCA"),
    CardOption(id=3, label="Mandiri Debit 1234", last4="1234", bank_name="Mandiri"),
]


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("VISA ****9999", 2),  # unique last four
        ("xxxx 9999 approved", 2),
        ("1234", None),  # two cards share the digits
        ("Mandiri 1234", 3),  # digits are shared, the bank name narrows it
        ("Mandiri", 3),  # one Mandiri card
        ("BCA", None),  # two BCA cards
        ("", None),
        (None, None),
        ("   ", None),
        ("12345", None),  # five digits are not a last-four
    ],
)
def test_infer_card(hint, expected):
    assert infer_card(hint, CARDS) == expected


def test_infer_card_with_no_cards():
    assert infer_card("BCA 1234", []) is None
