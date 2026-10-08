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

from pfa.core.tracing import REDACTED, configure_tracing, redact_sensitive

PIXELS = b"\xff\xd8\xff\xe0 PRIVATE-RECEIPT-PIXELS"
B64 = base64.b64encode(PIXELS).decode()


def test_base64_image_blocks_are_redacted_and_text_is_kept():
    blocks = [
        {"type": "text", "text": "Read this receipt"},
        {"type": "image", "base64": B64, "mime_type": "image/jpeg"},
    ]
    result = redact_sensitive(blocks)
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
    assert B64 not in json.dumps(redact_sensitive({"messages": [[block]]}))


def test_raw_bytes_are_redacted():
    assert redact_sensitive({"content": PIXELS}) == {"content": REDACTED}


def test_deeply_nested_structures_are_walked():
    nested = {"a": [{"b": {"kwargs": {"content": [{"type": "image", "base64": B64}]}}}]}
    assert B64 not in json.dumps(redact_sensitive(nested))


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
    assert redact_sensitive(data) == data


def test_the_input_is_not_modified():
    original = {"content": [{"type": "image", "base64": B64, "mime_type": "image/png"}]}
    snapshot = copy.deepcopy(original)
    redact_sensitive(original)
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
    assert client.anonymizer is redact_sensitive


def test_uploaded_trace_has_no_image_but_the_model_received_it(monkeypatch):
    client = Client(
        api_key="not-a-real-key", anonymizer=redact_sensitive, auto_batch_tracing=False
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


# --- statements: PDF, CSV and Excel contents must stay out of uploaded traces ---

PDF_BYTES = b"%PDF-1.7 PRIVATE-PDF-CONTENT 4111-1111"
SECRETS = ["PRIVATE-MERCHANT-ALPHA", "PRIVATE-EXTRACTED-MERCHANT", "PRIVATE-CARD-HINT"]


def _statement_csv() -> bytes:
    return (
        b"Date,Merchant,Amount\n"
        b"2026-10-01,PRIVATE-MERCHANT-ALPHA,98765\n"
        b"2026-10-02,PRIVATE-MERCHANT-ALPHA,24680\n"
    )


def _statement_xlsx() -> bytes:
    import io

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Date", "Merchant", "Amount"])
    sheet.append(["2026-10-01", "PRIVATE-MERCHANT-ALPHA", 98765])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class _StructuredFake:
    """A model whose structured output traces like the real one: model, then parser."""

    def __init__(self, answer_json: str):
        self._answer = answer_json

    def with_structured_output(self, schema):
        import itertools

        from langchain_core.runnables import RunnableLambda

        chat = GenericFakeChatModel(
            messages=itertools.cycle([AIMessage(content=self._answer)])
        )
        return chat | RunnableLambda(
            lambda msg: schema.model_validate_json(msg.content)
        )


async def _traced_statement_upload(monkeypatch, content, fmt, masked=True):
    """Runs a statement extraction under tracing; returns everything uploaded."""
    import langsmith
    from langchain_core.tracers.langchain import wait_for_all_tracers

    from pfa.graphs.extractors import GeminiStatementExtractor
    from pfa.schemas.extraction import ExtractedStatement, ExtractedStatementRow

    client = Client(
        api_key="not-a-real-key",
        anonymizer=redact_sensitive if masked else None,
        auto_batch_tracing=False,
    )
    uploads = MagicMock()
    monkeypatch.setattr(Client, "request_with_retries", uploads)
    answer = ExtractedStatement(
        card_hint="PRIVATE-CARD-HINT 1234",
        transactions=[
            ExtractedStatementRow(
                merchant="PRIVATE-EXTRACTED-MERCHANT",
                amount=13579,
                occurred_on="2026-10-01",
            )
        ],
    ).model_dump_json()
    extractor = GeminiStatementExtractor(_StructuredFake(answer))
    with langsmith.tracing_context(enabled=True, client=client):
        result = await extractor(
            content, fmt, ["Groceries", "Other"], ["BCA Visa 1234"]
        )
    wait_for_all_tracers()
    client.flush()
    uploaded = " ".join(
        str(call.kwargs.get("request_kwargs", {}).get("data", b""))
        for call in uploads.call_args_list
    )
    return result, uploaded


STATEMENTS = [
    ("pdf", PDF_BYTES),
    ("csv", _statement_csv()),
    ("xlsx", _statement_xlsx()),
]


@pytest.mark.parametrize(("fmt", "content"), STATEMENTS, ids=[f for f, _ in STATEMENTS])
async def test_statement_contents_never_reach_an_uploaded_trace(
    monkeypatch, fmt, content
):
    result, uploaded = await _traced_statement_upload(monkeypatch, content, fmt)

    assert "extract_statement" in uploaded  # the run IS traced: structure stays visible
    for secret in SECRETS:
        assert secret not in uploaded, f"{secret} leaked into the {fmt} trace"
    assert base64.b64encode(PDF_BYTES).decode()[:24] not in uploaded
    assert "13579" not in uploaded  # an extracted amount
    # ...and the model itself was not affected: the real result came back whole.
    assert result.transactions[0].merchant == "PRIVATE-EXTRACTED-MERCHANT"
    assert result.card_hint == "PRIVATE-CARD-HINT 1234"


@pytest.mark.parametrize(("fmt", "content"), STATEMENTS, ids=[f for f, _ in STATEMENTS])
async def test_control_without_masking_the_same_run_does_leak(
    monkeypatch, fmt, content
):
    """Proves the search above can find the data, so a clean result means something."""
    _, uploaded = await _traced_statement_upload(
        monkeypatch, content, fmt, masked=False
    )
    assert "PRIVATE-EXTRACTED-MERCHANT" in uploaded
    if fmt == "pdf":
        assert base64.b64encode(PDF_BYTES).decode()[:24] in uploaded
    else:
        assert "PRIVATE-MERCHANT-ALPHA" in uploaded


# --- the individual masking rules ---


def test_spreadsheet_rows_after_the_marker_are_masked_but_the_instructions_stay():
    prompt = (
        "Read this statement.\n\nStatement rows:\nDate\tMerchant\n2026-10-01\tKopi\t5"
    )
    result = redact_sensitive({"messages": [[{"text": prompt}]]})
    masked = result["messages"][0][0]["text"]
    assert masked == "Read this statement.\n\nStatement rows: [statement rows redacted]"
    assert "Kopi" not in masked


def test_a_transactions_list_is_masked_wherever_it_appears():
    answer = {"card_hint": None, "transactions": [{"merchant": "Kopi", "amount": 5}]}
    nested = {"outputs": {"output": answer}, "other": [{"transactions": [{"a": 1}]}]}
    result = redact_sensitive(nested)
    assert result["outputs"]["output"]["transactions"] == "[statement lines redacted]"
    assert result["other"][0]["transactions"] == "[statement lines redacted]"
    assert "Kopi" not in json.dumps(result)


@pytest.mark.parametrize(
    "text",
    [
        '{"card_hint": null, "transactions": [{"merchant": "Kopi"}]}',
        '{"transactions":[{"merchant":"Kopi"}]}',
        'prefix {"transactions"  :  [ {"merchant": "Kopi"}]} suffix',
    ],
)
def test_json_text_holding_transactions_is_masked(text):
    assert redact_sensitive(text) == "[statement lines redacted]"


def test_the_card_hint_is_masked_but_other_text_is_not():
    result = redact_sensitive({"card_hint": "BCA 1234", "merchant": "Kopi"})
    assert result == {"card_hint": "[card redacted]", "merchant": "Kopi"}
    assert redact_sensitive({"card_hint": None}) == {"card_hint": None}


def test_ordinary_prompts_and_numbers_are_untouched_by_the_statement_rules():
    data = {
        "text": "Read this receipt and return its fields.",
        "transactions_count": 3,  # a different key
        "note": "I made 3 transactions today",  # the word, not the JSON key
        "nested": {"transactions": 5},  # not a list
    }
    assert redact_sensitive(data) == data


def test_the_marker_in_the_extractor_prompt_matches_the_one_the_redactor_uses():
    from pfa.core.tracing import STATEMENT_ROWS_MARKER

    assert STATEMENT_ROWS_MARKER == "Statement rows:"
    # The extractor builds its text from this constant, so the two cannot drift apart.
    import inspect

    from pfa.graphs import extractors

    assert "STATEMENT_ROWS_MARKER" in inspect.getsource(
        extractors.GeminiStatementExtractor
    )
