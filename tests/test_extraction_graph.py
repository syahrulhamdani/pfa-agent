"""Boundary: the extraction graph saves nothing until the user confirms.

Gemini is replaced by stub callables; Postgres is real (the pfa_test database).
"""

from datetime import date

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from pfa.core.exceptions import LLMError
from pfa.graphs.extraction import (
    NOT_A_CORRECTION,
    build_extraction_graph,
    pending_interrupt,
    thread_config,
)
from pfa.models import TransactionStatus, UploadStatus
from pfa.repository.finance import (
    BankRepository,
    CardRepository,
    TransactionRepository,
    UploadRepository,
)
from pfa.schemas.extraction import CorrectionResult, ExtractedReceipt

TODAY = date(2026, 10, 5)

FULL = ExtractedReceipt(
    merchant="Indomaret",
    amount=45000,
    occurred_on="2026-10-04",
    category="Groceries",
    card_hint="BCA ****1234",
    description="Snacks",
)


def make_graph(session_factory, receipt=FULL, correction=None, saver=None):
    async def extractor(path, mime, categories):
        if isinstance(receipt, Exception):
            raise receipt
        return receipt

    async def parser(text, current, categories, cards):
        return correction or CorrectionResult(is_correction=False)

    return build_extraction_graph(
        session_factory=session_factory,
        extractor=extractor,
        parse_correction=parser,
        checkpointer=saver or InMemorySaver(),
        today=lambda: TODAY,
    )


async def new_upload(session_factory, with_card=True) -> int:
    async with session_factory() as session:
        if with_card:
            bank = await BankRepository(session).add("BCA")
            await CardRepository(session).add(bank.id, "Visa", "1234")
        upload = await UploadRepository(session).add(
            telegram_message_id=10,
            kind="image",
            filename="r.jpg",
            file_path="/tmp/r.jpg",
            mime_type="image/jpeg",
        )
        return upload.id


async def statuses(session_factory, upload_id):
    async with session_factory() as session:
        upload = await UploadRepository(session).get(upload_id)
        repo = TransactionRepository(session)
        pending = await repo.list_by_status(TransactionStatus.PENDING)
        confirmed = await repo.list_by_status(TransactionStatus.CONFIRMED)
        return upload.status, len(pending), len(confirmed)


async def run(graph, upload_id, payload=None):
    config = thread_config(upload_id)
    arg = {"upload_id": upload_id} if payload is None else Command(resume=payload)
    return await graph.ainvoke(arg, config)


async def test_confirm_saves_only_after_confirmation(session_factory):
    upload_id = await new_upload(session_factory)
    graph = make_graph(session_factory)

    paused = pending_interrupt(await run(graph, upload_id))
    assert paused["missing"] == []
    assert paused["transaction"]["merchant"] == "Indomaret"
    assert paused["transaction"]["card"] == "BCA Visa 1234"
    assert await statuses(session_factory, upload_id) == (
        UploadStatus.AWAITING_CONFIRMATION,
        1,
        0,
    )

    result = await run(graph, upload_id, {"action": "confirm"})
    assert pending_interrupt(result) is None
    assert await statuses(session_factory, upload_id) == (UploadStatus.DONE, 0, 1)


async def test_missing_card_blocks_confirm_until_chosen(session_factory):
    upload_id = await new_upload(session_factory)
    other = FULL.model_copy(update={"card_hint": None})
    graph = make_graph(session_factory, receipt=other)

    paused = pending_interrupt(await run(graph, upload_id))
    assert paused["missing"] == ["card"]
    assert len(paused["cards"]) == 1
    assert (await statuses(session_factory, upload_id))[0] == UploadStatus.NEEDS_INPUT

    blocked = pending_interrupt(await run(graph, upload_id, {"action": "confirm"}))
    assert blocked["notice"] == "missing:card"
    assert (await statuses(session_factory, upload_id))[1:] == (1, 0)

    card_id = paused["cards"][0]["id"]
    ready = pending_interrupt(
        await run(graph, upload_id, {"action": "set_card", "card_id": card_id})
    )
    assert ready["missing"] == []
    await run(graph, upload_id, {"action": "confirm"})
    assert await statuses(session_factory, upload_id) == (UploadStatus.DONE, 0, 1)


async def test_unreadable_amount_filled_by_typed_correction(session_factory):
    upload_id = await new_upload(session_factory)
    blurry = FULL.model_copy(update={"amount": None, "occurred_on": "not a date"})
    correction = CorrectionResult(is_correction=True, amount=52500.5)
    graph = make_graph(session_factory, receipt=blurry, correction=correction)

    paused = pending_interrupt(await run(graph, upload_id))
    assert set(paused["missing"]) == {"amount", "occurred_on"}

    after = pending_interrupt(
        await run(graph, upload_id, {"action": "text", "text": "it was 52,500.50"})
    )
    assert after["transaction"]["amount"] == "52500.50"
    assert after["missing"] == ["occurred_on"]


async def test_chit_chat_is_not_a_correction(session_factory):
    upload_id = await new_upload(session_factory)
    graph = make_graph(session_factory)
    await run(graph, upload_id)

    after = pending_interrupt(
        await run(graph, upload_id, {"action": "text", "text": "how am I doing?"})
    )
    assert after["notice"] == NOT_A_CORRECTION
    assert after["transaction"]["merchant"] == "Indomaret"


async def test_unknown_category_is_reported_not_saved(session_factory):
    upload_id = await new_upload(session_factory)
    correction = CorrectionResult(is_correction=True, category="Yachts")
    graph = make_graph(session_factory, correction=correction)
    await run(graph, upload_id)

    after = pending_interrupt(
        await run(graph, upload_id, {"action": "text", "text": "category yachts"})
    )
    assert after["notice"] == "rejected:category"
    assert after["transaction"]["category"] == "Groceries"


async def test_extraction_failure_leaves_nothing_behind(session_factory):
    upload_id = await new_upload(session_factory)
    graph = make_graph(session_factory, receipt=LLMError("rate limited"))
    with pytest.raises(LLMError):
        await run(graph, upload_id)
    assert (await statuses(session_factory, upload_id))[1:] == (0, 0)


async def test_confirmation_survives_a_restart(session_factory, test_database_url):
    conn = test_database_url.replace("+asyncpg", "", 1)
    upload_id = await new_upload(session_factory)

    async with AsyncPostgresSaver.from_conn_string(conn) as saver:
        await saver.setup()
        graph = make_graph(session_factory, saver=saver)
        assert pending_interrupt(await run(graph, upload_id)) is not None

    # A new saver and a new graph: what a restarted process would build.
    async with AsyncPostgresSaver.from_conn_string(conn) as saver:
        graph = make_graph(session_factory, saver=saver)
        result = await run(graph, upload_id, {"action": "confirm"})

    assert pending_interrupt(result) is None
    assert await statuses(session_factory, upload_id) == (UploadStatus.DONE, 0, 1)
