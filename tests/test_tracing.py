"""Boundary: what is uploaded to LangSmith has no images; what the model gets does."""

import base64
import copy
import json
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tracers.langchain import LangChainTracer
from langsmith import Client
from langsmith import run_trees as rt

from pfa.core.tracing import REDACTED, configure_tracing, redact_images

PIXELS = b"\xff\xd8\xff\xe0 PRIVATE-RECEIPT-PIXELS"
B64 = base64.b64encode(PIXELS).decode()


def test_base64_image_blocks_are_redacted_and_text_is_kept():
    blocks = [
        {"type": "text", "text": "Read this receipt"},
        {"type": "image", "base64": B64, "mime_type": "image/jpeg"},
    ]
    result = redact_images(blocks)
    assert result[0] == {"type": "text", "text": "Read this receipt"}
    assert result[1] == {
        "type": "image",
        "base64": REDACTED,
        "mime_type": "image/jpeg",  # metadata stays, only the pixels go
    }


@pytest.mark.parametrize(
    "block",
    [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{B64}"}},
        {"inline_data": {"mime_type": "image/png", "data": B64}},
        {"type": "file", "mime_type": "application/pdf", "data": B64},
        {"mimeType": "image/png", "data": B64},
        {"type": "image", "base64": B64},  # no mime type given
    ],
)
def test_other_image_shapes_are_redacted(block):
    assert B64 not in json.dumps(redact_images({"messages": [[block]]}))


def test_raw_bytes_are_redacted():
    assert redact_images({"content": PIXELS}) == {"content": REDACTED}


def test_deeply_nested_structures_are_walked():
    nested = {"a": [{"b": {"kwargs": {"content": [{"type": "image", "base64": B64}]}}}]}
    assert B64 not in json.dumps(redact_images(nested))


def test_ordinary_data_is_untouched():
    data = {
        "text": "Indomaret",
        "amount": 45000.5,
        "ok": True,
        "none": None,
        "data": "a short note",  # a "data" key without a MIME type is just text
        "nested": [1, 2, {"x": "y"}],
        "url": "https://example.com/page",
    }
    assert redact_images(data) == data


def test_the_input_is_not_modified():
    original = {"content": [{"type": "image", "base64": B64, "mime_type": "image/png"}]}
    snapshot = copy.deepcopy(original)
    redact_images(original)
    assert original == snapshot


# --- end to end: a real LangChain run, uploaded through a LangSmith client ---


def test_configure_tracing_installs_a_global_redacting_client(monkeypatch):
    from langchain_core.tracers.langchain import get_client

    class OfflineClient:
        """Stands in for the real client, which would contact LangSmith on creation."""

        def __init__(self, **kwargs):
            self.anonymizer = kwargs["anonymizer"]

    monkeypatch.setattr("pfa.core.tracing.Client", OfflineClient)
    monkeypatch.setattr(rt, "_CLIENT", None)
    configure_tracing()
    client = get_client()  # what LangChain and LangGraph use
    assert isinstance(client, OfflineClient)
    assert client.anonymizer is redact_images


def test_uploaded_trace_has_no_image_but_the_model_received_it(monkeypatch):
    client = Client(
        api_key="not-a-real-key", anonymizer=redact_images, auto_batch_tracing=False
    )
    uploads = MagicMock()
    # Capture what would be sent to LangSmith. The client forbids instance patching.
    monkeypatch.setattr(Client, "request_with_retries", uploads)

    model = GenericFakeChatModel(messages=iter([AIMessage(content="ok")]))
    seen_by_model = []
    original_generate = model._generate

    def spy(messages, *args, **kwargs):
        seen_by_model.append(messages)
        return original_generate(messages, *args, **kwargs)

    model._generate = spy
    message = HumanMessage(
        content=[
            {"type": "text", "text": "Read this receipt"},
            {"type": "image", "base64": B64, "mime_type": "image/jpeg"},
        ]
    )

    model.invoke([message], config={"callbacks": [LangChainTracer(client=client)]})
    client.flush()

    # The model got the real image, untouched.
    assert seen_by_model[0][0].content[1]["base64"] == B64

    # Everything uploaded to LangSmith is free of it, and the text is still there.
    assert uploads.called
    uploaded = " ".join(
        str(call.kwargs.get("request_kwargs", {}).get("data", b""))
        for call in uploads.call_args_list
    )
    assert B64 not in uploaded
    assert "PRIVATE-RECEIPT-PIXELS" not in uploaded
    assert REDACTED in uploaded
    assert "Read this receipt" in uploaded
