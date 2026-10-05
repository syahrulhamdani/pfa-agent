"""Boundary: what the user sees and which buttons they get at confirmation."""

from pfa.bot.formatting import format_review, review_keyboard

TX = {
    "merchant": "Indomaret",
    "amount": "45000.00",
    "occurred_on": "2026-10-04",
    "category": "Groceries",
    "card": "BCA Visa 1234",
    "description": None,
}


def payload(missing=(), cards=(), notice=None, tx=None):
    return {
        "upload_id": 7,
        "transaction": tx or TX,
        "missing": list(missing),
        "cards": list(cards),
        "notice": notice,
    }


def buttons(markup):
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


def test_complete_receipt_offers_confirm():
    p = payload()
    text = format_review(p)
    assert "Merchant: Indomaret" in text
    assert "Description: not found" in text
    assert "Confirm to save" in text
    assert buttons(review_keyboard(p)) == [("Confirm", "confirm:7")]


def test_missing_card_lists_cards_as_buttons():
    cards = [{"id": 1, "label": "BCA Visa 1234"}, {"id": 2, "label": "Mandiri 9999"}]
    p = payload(missing=["card"], cards=cards, tx={**TX, "card": None})
    assert "Card: not found" in format_review(p)
    assert buttons(review_keyboard(p)) == [
        ("BCA Visa 1234", "card:7:1"),
        ("Mandiri 9999", "card:7:2"),
    ]


def test_missing_card_with_no_cards_has_no_buttons_and_says_why():
    p = payload(missing=["card"], tx={**TX, "card": None})
    assert review_keyboard(p) is None
    assert "no cards yet" in format_review(p)


def test_missing_other_field_has_no_confirm_button():
    p = payload(missing=["amount", "occurred_on"], tx={**TX, "amount": None})
    assert review_keyboard(p) is None
    assert "amount, occurred on" in format_review(p)


def test_notices_are_shown():
    assert "Still missing: card" in format_review(payload(notice="missing:card"))
    assert "couldn't use" in format_review(payload(notice="rejected:category"))
    assert format_review(payload(notice="not_correction")).startswith("Here is")
