"""Telegram message text and buttons for the confirmation step."""

from datetime import datetime
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

NUDGE_TEXT = "Any purchases to record? Send a receipt photo and I'll add it."
PROCESSING_TEXT = "Processing this now. You can keep chatting in the meantime."
FAILED_TEXT = "I couldn't process this file. Please send it again."
UNSUPPORTED_TEXT = "I can read receipt photos for now. Statements are coming soon."

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


def saved_text(link: str, ttl_minutes: int) -> str:
    """Formats the reply sent after a transaction is saved, with a sign-in link."""
    return (
        f"Saved. Open your transactions (sign-in link, valid for {ttl_minutes} "
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
