"""Telegram message text and buttons for the confirmation step."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

NUDGE_TEXT = "Any purchases to record? Send a receipt photo and I'll add it."
PROCESSING_TEXT = "Processing this now. You can keep chatting in the meantime."
FAILED_TEXT = "I couldn't process this file. Please send it again."
UNSUPPORTED_TEXT = (
    "I can read receipt photos, and statements as PDF, CSV or Excel (.xlsx)."
)

_FIELDS = (
    ("merchant", "Merchant"),
    ("amount", "Amount"),
    ("occurred_on", "Date"),
    ("category", "Category"),
    ("card", "Card"),
    ("description", "Description"),
)
_NOTICES = {
    "not_correction": "",
    "missing": "Still missing: {}.",
    "rejected": "I couldn't use the value you gave for: {}.",
}


def _notice_text(notice: str | None) -> str:
    if not notice or ":" not in notice:
        return ""
    kind, _, detail = notice.partition(":")
    template = _NOTICES.get(kind, "")
    return (
        template.format(detail.replace(",", ", ").replace("_", " ")) if template else ""
    )


def format_review(payload: dict[str, Any]) -> str:
    """Formats the extracted fields and what the user should do next."""
    tx = payload["transaction"]
    lines = []
    notice = _notice_text(payload.get("notice"))
    if notice:
        lines += [notice, ""]
    lines.append("Here is what I read:")
    for key, label in _FIELDS:
        value = tx.get(key)
        lines.append(f"{label}: {value if value not in (None, '') else 'not found'}")
    lines.append("")
    missing = payload["missing"]
    if missing:
        names = ", ".join(m.replace("_", " ") for m in missing)
        lines.append(f"I need the following before I can save it: {names}.")
        if "card" in missing and not payload["cards"]:
            lines.append("You have no cards yet. Add one first, then send this again.")
        else:
            lines.append("Reply with the values, or pick the card below.")
    else:
        lines.append("Confirm to save it, or reply with a correction.")
    return "\n".join(lines)


def review_keyboard(payload: dict[str, Any]) -> InlineKeyboardMarkup | None:
    """Builds Confirm, or one button per card when the card is missing."""
    upload_id = payload["upload_id"]
    missing = payload["missing"]
    if not missing:
        button = InlineKeyboardButton("Confirm", callback_data=f"confirm:{upload_id}")
        return InlineKeyboardMarkup([[button]])
    if "card" in missing and payload["cards"]:
        rows = [
            [
                InlineKeyboardButton(
                    c["label"], callback_data=f"card:{upload_id}:{c['id']}"
                )
            ]
            for c in payload["cards"]
        ]
        return InlineKeyboardMarkup(rows)
    return None


def saved_text(link: str, ttl_minutes: int, count: int | None = None) -> str:
    """Formats the reply sent after saving, with a sign-in link.

    Args:
        link: The single-use sign-in link.
        ttl_minutes: How long the link stays valid.
        count: How many transactions a statement saved; None for a single receipt.
    """
    if count is None:
        opening = "Saved."
    elif count == 0:
        opening = "Nothing new to save: this statement is already recorded."
    else:
        opening = f"Saved {count} transaction{'s' if count != 1 else ''}."
    return (
        f"{opening} Open your transactions (sign-in link, valid for {ttl_minutes} "
        f"minutes, works once): {link}"
    )


def login_text(link: str, ttl_minutes: int) -> str:
    """Formats the reply to /login."""
    return f"Your sign-in link (valid for {ttl_minutes} minutes, works once): {link}"


def signed_in_text(when: datetime) -> str:
    """Formats the notice sent to Telegram when a sign-in link has been used."""
    return (
        f"Signed in to the web app on {when:%d %b} at {when:%H:%M}. "
        "Not you? Send /signout."
    )


SIGNED_OUT_TEXT = (
    "Signed out of the web app everywhere, and any unused sign-in links no longer "
    "work. Send /login for a new link."
)


def _money(value: str | None) -> str:
    return "none" if value is None else f"{Decimal(value):,.2f}"


def _signed_money(value: Decimal) -> str:
    """Formats an amount with an explicit sign: +1,000.00 or -1,000.00."""
    if value == 0:
        return "0.00"
    return f"{'+' if value > 0 else '-'}{abs(value):,.2f}"


def _direction_line(label: str, summary: dict[str, Any], with_extremes: bool) -> str:
    if summary["count"] == 0:
        return f"{label}: none"
    line = f"{label}: {summary['count']}, total {_money(summary['total'])}"
    if with_extremes and summary["count"] > 1:
        line += (
            f" (highest {_money(summary['highest'])}, "
            f"lowest {_money(summary['lowest'])})"
        )
    return line


def format_statement_review(payload: dict[str, Any]) -> str:
    """Formats a statement summary and what the user should do next.

    Money out and money in are shown apart, with the net between them. The numbers
    come from code, not the model, so they can be checked against the statement
    before confirming.
    """
    money_out, money_in = payload["summary"]["out"], payload["summary"]["in"]
    count = money_out["count"] + money_in["count"]
    net = Decimal(money_in["total"]) - Decimal(money_out["total"])
    lines = []
    notice = _notice_text(payload.get("notice"))
    if notice:
        lines += [notice, ""]
    transfers = payload.get("transfers") or {"count": 0, "total": "0.00"}
    count += transfers["count"]
    lines += [
        f"Statement read: {count} transaction{'s' if count != 1 else ''}",
        _direction_line("Money out", money_out, with_extremes=True),
        _direction_line("Money in", money_in, with_extremes=True),
        f"Net: {_signed_money(net)}",
    ]
    if transfers["count"]:
        lines.append(
            f"Between your own accounts: {transfers['count']}, total "
            f"{_money(transfers['total'])} (not counted as spending or income)"
        )
    lines.append(f"Card: {payload['card'] or 'not found'}")
    left_out = []
    if payload["skipped_unreadable"]:
        left_out.append(f"{payload['skipped_unreadable']} I couldn't read")
    if payload["duplicates"]:
        left_out.append(f"{payload['duplicates']} already saved")
    if left_out:
        lines += ["", "Left out: " + ", ".join(left_out) + "."]
    lines.append("")
    if payload["missing"]:
        if payload["cards"]:
            lines.append("Which card is this statement for? Pick it below.")
        else:
            lines.append("You have no cards yet. Add one first, then send this again.")
    else:
        lines.append(f"Confirm to save all {count}.")
    return "\n".join(lines)
