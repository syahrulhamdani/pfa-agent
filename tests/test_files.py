"""Boundary: files are held in memory, handed over once, and then forgotten."""

import base64

import pytest
from langchain_core.messages import HumanMessage

from pfa.graphs.extractors import GeminiExtractor
from pfa.schemas.extraction import ExtractedReceipt
from pfa.services.files import FileStash


def test_stash_holds_and_returns_bytes():
    stash = FileStash()
    stash.put(1, b"abc")
    assert stash.get(1) == b"abc"
    assert stash.get(1) == b"abc"  # reading does not remove it
    assert len(stash) == 1


def test_discard_forgets_and_is_idempotent():
    stash = FileStash()
    stash.put(1, b"abc")
    stash.discard(1)
    stash.discard(1)  # no error the second time
    assert len(stash) == 0
    with pytest.raises(LookupError):
        stash.get(1)


def test_unknown_upload_raises_lookup_error():
    with pytest.raises(LookupError, match="42"):
        FileStash().get(42)


class RecordingModel:
    """Stands in for the chat model: records what the extractor sends it."""

    def __init__(self):
        self.messages = None

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages, config=None):
        self.messages = messages
        return ExtractedReceipt(merchant="Indomaret")


async def test_extractor_sends_the_bytes_straight_to_the_model():
    model = RecordingModel()
    content = b"\xff\xd8 raw jpeg bytes"
    result = await GeminiExtractor(model)(content, "image/jpeg", ["Groceries", "Other"])

    assert result.merchant == "Indomaret"
    (message,) = model.messages
    assert isinstance(message, HumanMessage)
    text_block, image_block = message.content
    assert "Groceries, Other" in text_block["text"]
    assert image_block["mime_type"] == "image/jpeg"
    assert base64.b64decode(image_block["base64"]) == content
