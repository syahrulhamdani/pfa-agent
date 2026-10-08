"""LangSmith tracing that never uploads receipt images or statement contents.

LangSmith records every model call's inputs and outputs. For extraction those carry
the receipt photo, the statement PDF, the rows of a CSV or Excel statement, and the
list of transactions the model read out of it. None of that may leave this machine.
The redactor below runs on the copy that is uploaded to LangSmith, after the run has
been recorded. The request that goes to Gemini, and the answer that comes back, are
built separately and are never changed by it.

Traces keep their structure (run names, timings, errors, token counts), so they are
still useful for debugging. Extracted receipt fields are not masked.
"""

import re
from typing import Any

import langsmith
from langsmith import Client

REDACTED = "[image redacted]"
REDACTED_ROWS = "[statement rows redacted]"
REDACTED_LINES = "[statement lines redacted]"
REDACTED_CARD = "[card redacted]"

# The statement extractor puts spreadsheet rows after this marker in its prompt, so
# the redactor can recognise them as plain text. Keep the two in step.
STATEMENT_ROWS_MARKER = "Statement rows:"

_DATA_URL_PREFIXES = ("data:image/", "data:application/", "data:audio/", "data:video/")
_BINARY_KEYS = ("base64", "data", "bytes", "image")
_LINES_KEY = "transactions"  # the list of lines a model read from a statement
_CARD_KEY = "card_hint"  # a bank name and last four digits read from a document
_LINES_IN_JSON = re.compile(rf'"{_LINES_KEY}"\s*:\s*\[')


def redact_sensitive(value: Any) -> Any:
    """Returns a copy of `value` with images, files and statement contents replaced.

    Handles base64 content blocks (``{"type": "image", "base64": ...}``), blocks
    that carry a MIME type next to raw data, ``data:`` URLs, spreadsheet rows sent as
    text after `STATEMENT_ROWS_MARKER`, the ``transactions`` list a model returns
    for a statement (as a structure or as JSON text), and the ``card_hint`` it read.
    All of it is found
    anywhere in a nested structure. Everything else is left as it was, and the input
    is never modified.
    """
    if isinstance(value, str):
        if value.startswith(_DATA_URL_PREFIXES):
            return REDACTED
        if STATEMENT_ROWS_MARKER in value:
            head = value.split(STATEMENT_ROWS_MARKER, 1)[0]
            return f"{head}{STATEMENT_ROWS_MARKER} {REDACTED_ROWS}"
        if _LINES_IN_JSON.search(value):
            return REDACTED_LINES
        return value
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, dict):
        carries_binary = "mime_type" in value or "mimeType" in value
        return {
            key: _redact_entry(key, item, carries_binary) for key, item in value.items()
        }
    if isinstance(value, bytes | bytearray):
        return REDACTED
    return value


def _redact_entry(key: Any, item: Any, carries_binary: bool) -> Any:
    if key == _LINES_KEY and isinstance(item, list):
        return REDACTED_LINES
    if key == _CARD_KEY and isinstance(item, str):
        return REDACTED_CARD
    if (
        key in _BINARY_KEYS
        and isinstance(item, str | bytes | bytearray)
        and (carries_binary or key == "base64")
    ):
        return REDACTED
    return redact_sensitive(item)


def configure_tracing() -> None:
    """Makes every LangChain and LangGraph trace go through the redacting client.

    Call once at startup, before any graph runs, and only when tracing is enabled.
    The API key and project come from the usual LANGSMITH_* environment variables.
    """
    langsmith.configure(client=Client(anonymizer=redact_sensitive))
