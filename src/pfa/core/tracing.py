"""LangSmith tracing that never uploads receipt images.

LangSmith records every model call's inputs. For extraction those inputs include the
receipt photo as base64, which must not leave this machine. The redactor below runs
on the copy that is uploaded to LangSmith, after the run has been recorded. The
request that goes to Gemini is built separately and is never changed by it.
"""

from typing import Any

import langsmith
from langsmith import Client

REDACTED = "[image redacted]"
_DATA_URL_PREFIXES = ("data:image/", "data:application/", "data:audio/", "data:video/")
_BINARY_KEYS = ("base64", "data", "bytes", "image")


def redact_images(value: Any) -> Any:
    """Returns a copy of `value` with embedded images and files replaced.

    Handles base64 content blocks (``{"type": "image", "base64": ...}``), blocks
    that carry a MIME type next to raw data, and ``data:`` URLs, anywhere in a
    nested structure. Everything else, including text, is left as it was. The
    input is never modified.
    """
    if isinstance(value, str):
        return REDACTED if value.startswith(_DATA_URL_PREFIXES) else value
    if isinstance(value, list):
        return [redact_images(item) for item in value]
    if isinstance(value, dict):
        carries_binary = "mime_type" in value or "mimeType" in value
        return {
            key: (
                REDACTED
                if key in _BINARY_KEYS
                and isinstance(item, str | bytes | bytearray)
                and (carries_binary or key == "base64")
                else redact_images(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, bytes | bytearray):
        return REDACTED
    return value


def configure_tracing() -> None:
    """Makes every LangChain and LangGraph trace go through the redacting client.

    Call once at startup, before any graph runs, and only when tracing is enabled.
    The API key and project come from the usual LANGSMITH_* environment variables.
    """
    langsmith.configure(client=Client(anonymizer=redact_images))
