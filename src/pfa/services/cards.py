"""Matching a receipt's payment hint to one of the user's cards."""

import re

from pfa.schemas.transactions import CardOption

_LAST4 = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def infer_card(hint: str | None, cards: list[CardOption]) -> int | None:
    """Finds the one card a hint points to.

    Matches by last four digits first, then by card or bank name. Returns None
    when the hint is empty or ambiguous, so the user is asked instead of guessed at.

    Args:
        hint: Free text from the receipt, such as "BCA Visa ****1234".
        cards: The user's cards.

    Returns:
        The card id, or None if there is no single match.
    """
    if not hint or not hint.strip():
        return None
    for digits in _LAST4.findall(hint):
        matches = [c for c in cards if c.last4 == digits]
        if len(matches) == 1:
            return matches[0].id
    lowered = hint.lower()
    matches = [
        c
        for c in cards
        if c.label.lower() in lowered
        or (c.bank_name and c.bank_name.lower() in lowered)
    ]
    return matches[0].id if len(matches) == 1 else None
