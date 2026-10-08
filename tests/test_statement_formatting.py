"""Boundary: the statement summary the user confirms against, and its buttons."""

from pfa.bot.formatting import format_statement_review, review_keyboard, saved_text


def side(count, total="0.00", highest=None, lowest=None):
    return {"count": count, "total": total, "highest": highest, "lowest": lowest}


OUT = side(3, "1234567.80", "1000000.00", "0.80")
IN = side(1, "9000000.00", "9000000.00", "9000000.00")
NONE = side(0)


def payload(out=OUT, money_in=IN, **overrides):
    base = {
        "kind": "statement",
        "upload_id": 9,
        "summary": {"out": out, "in": money_in},
        "card": "BCA Visa 1234",
        "missing": [],
        "cards": [],
        "duplicates": 0,
        "skipped_unreadable": 0,
        "notice": None,
    }
    return {**base, **overrides}


def buttons(markup):
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


def test_money_out_and_in_are_shown_apart_with_the_net_and_the_card():
    text = format_statement_review(payload())
    assert "Statement read: 4 transactions" in text
    assert (
        "Money out: 3, total 1,234,567.80 (highest 1,000,000.00, lowest 0.80)" in text
    )
    assert "Money in: 1, total 9,000,000.00" in text
    assert "Net: +7,765,432.20" in text  # in minus out, with a sign
    assert "Card: BCA Visa 1234" in text
    assert "Confirm to save all 4." in text
    assert "Left out" not in text


def test_the_net_is_negative_when_more_went_out_than_came_in():
    text = format_statement_review(
        payload(
            out=side(1, "500.00", "500.00", "500.00"),
            money_in=side(1, "200.00", "200.00", "200.00"),
        )
    )
    assert "Net: -300.00" in text


def test_the_net_is_zero_without_a_sign_when_they_cancel():
    one = side(1, "100.00", "100.00", "100.00")
    assert "Net: 0.00" in format_statement_review(payload(out=one, money_in=one))


def test_a_side_with_nothing_says_none():
    text = format_statement_review(payload(money_in=NONE))
    assert "Money in: none" in text
    assert "Money out: 3" in text
    text = format_statement_review(payload(out=NONE))
    assert "Money out: none" in text


def test_extremes_are_only_shown_when_there_is_more_than_one_line():
    one = side(1, "500.00", "500.00", "500.00")
    text = format_statement_review(payload(out=one))
    assert "Money out: 1, total 500.00\n" in text + "\n"
    assert "highest" not in text.split("Money in")[0]


def test_a_single_transaction_is_not_pluralised():
    text = format_statement_review(payload(out=side(1, "5.00"), money_in=NONE))
    assert "Statement read: 1 transaction\n" in text + "\n"
    assert "Confirm to save all 1." in text


def test_everything_left_out_is_listed_with_its_reason():
    text = format_statement_review(payload(skipped_unreadable=2, duplicates=4))
    assert "Left out: 2 I couldn't read, 4 already saved." in text


def test_only_the_reasons_that_apply_are_listed():
    text = format_statement_review(payload(duplicates=2))
    assert "Left out: 2 already saved." in text
    assert "couldn't read" not in text


def test_credits_are_no_longer_a_reason_to_leave_a_line_out():
    assert "credits" not in format_statement_review(payload())


def test_a_missing_card_asks_for_it_and_offers_the_cards():
    cards = [{"id": 1, "label": "BCA Visa 1234"}, {"id": 2, "label": "Mandiri 9999"}]
    p = payload(card=None, missing=["card"], cards=cards)
    text = format_statement_review(p)
    assert "Card: not found" in text
    assert "Which card is this statement for?" in text
    assert buttons(review_keyboard(p)) == [
        ("BCA Visa 1234", "card:9:1"),
        ("Mandiri 9999", "card:9:2"),
    ]


def test_with_no_cards_at_all_it_says_to_add_one_first():
    p = payload(card=None, missing=["card"], cards=[])
    assert "no cards yet" in format_statement_review(p)
    assert review_keyboard(p) is None


def test_a_complete_summary_offers_a_single_confirm_button():
    assert buttons(review_keyboard(payload())) == [("Confirm", "confirm:9")]


def test_notices_are_shown_above_the_summary():
    text = format_statement_review(payload(notice="missing:card"))
    assert text.startswith("Still missing: card.")


def test_an_all_empty_summary_does_not_crash():
    text = format_statement_review(payload(out=NONE, money_in=NONE))
    assert "Statement read: 0 transactions" in text
    assert "Money out: none" in text
    assert "Money in: none" in text
    assert "Net: 0.00" in text


def test_the_saved_message_depends_on_what_was_saved():
    link = "http://web/auth?token=T"
    assert saved_text(link, 10).startswith("Saved. Open")  # a receipt
    assert saved_text(link, 10, 1).startswith("Saved 1 transaction. Open")
    assert saved_text(link, 10, 33).startswith("Saved 33 transactions. Open")
    assert saved_text(link, 10, 0).startswith("Nothing new to save")
    assert link in saved_text(link, 10, 33)
