"""Boundary: a statement is read, summarised, and saved only after one confirmation.

Gemini is replaced by a stub; Postgres is real (the pfa_test database).
"""

import base64
from datetime import date
from decimal import Decimal

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from pfa.core.exceptions import LLMError, StatementError
from pfa.graphs.extraction import NOT_A_CORRECTION, pending_interrupt
from pfa.models import Category, Transaction, UploadStatus
from pfa.repository.finance import (
    BankRepository,
    CardRepository,
    CategoryRepository,
    UploadRepository,
)
from pfa.schemas.extraction import ExtractedStatement, ExtractedStatementRow
from test_extraction_graph import make_graph, run

CSV = b"Date,Merchant,Amount\n2026-10-01,Indomaret,45000\n"


def line(merchant, amount, day, category="Groceries", **fields):
    return ExtractedStatementRow(
        merchant=merchant, amount=amount, occurred_on=day, category=category, **fields
    )


THREE = [
    line("Indomaret", 45000, "2026-10-01"),
    line("Grab", 30000, "2026-10-02", "Transport"),
    line("Warung", 25000.5, "2026-10-03", "Dining"),
]


def statement_of(rows=THREE, card_hint="BCA ****1234"):
    return ExtractedStatement(card_hint=card_hint, transactions=rows)


def graph_for(session_factory, statement, seen=None, **kwargs):
    async def extractor(content, fmt, categories, own_accounts):
        if seen is not None:
            seen.append((content, fmt, categories, own_accounts))
        if isinstance(statement, Exception):
            raise statement
        return statement

    kwargs.setdefault("file_source", lambda upload_id: CSV)
    return make_graph(session_factory, statement=extractor, **kwargs)


async def new_statement(
    session_factory, filename="march.csv", mime="text/csv", with_card=True
):
    async with session_factory() as session:
        card_id = None
        if with_card:
            bank = await BankRepository(session).add("BCA")
            card = await CardRepository(session).add(bank.id, "Visa", "1234")
            card_id = card.id
        upload = await UploadRepository(session).add(
            telegram_message_id=20,
            kind="statement",
            filename=filename,
            mime_type=mime,
        )
        return upload.id, card_id


async def transactions(session_factory):
    async with session_factory() as session:
        rows = await session.execute(
            select(Transaction, Category.name)
            .outerjoin(Category, Category.id == Transaction.category_id)
            .order_by(Transaction.id)
        )
        return [(t, name) for t, name in rows]


def by_status(rows, status):
    return [t for t, _ in rows if t.status == status]


async def upload_status(session_factory, upload_id):
    async with session_factory() as session:
        return (await UploadRepository(session).get(upload_id)).status


async def add_confirmed(session_factory, card_id, merchant, amount, day):
    async with session_factory() as session:
        session.add(
            Transaction(
                card_id=card_id,
                merchant=merchant,
                amount=Decimal(amount),
                occurred_on=day,
                status="confirmed",
            )
        )
        await session.commit()


# --- reading and summarising ---


async def test_the_summary_is_computed_in_code_and_nothing_is_saved_yet(
    session_factory,
):
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of())

    payload = pending_interrupt(await run(graph, upload_id))

    assert payload["kind"] == "statement"
    assert payload["summary"]["out"] == {
        "count": 3,
        "total": "100000.50",
        "highest": "45000.00",
        "lowest": "25000.50",
    }
    assert payload["summary"]["in"]["count"] == 0
    assert payload["card"] == "BCA Visa 1234"
    assert payload["missing"] == []
    assert payload["duplicates"] == 0
    rows = await transactions(session_factory)
    assert len(by_status(rows, "pending")) == 3
    assert by_status(rows, "confirmed") == []
    assert await upload_status(session_factory, upload_id) == (
        UploadStatus.AWAITING_CONFIRMATION
    )


async def test_one_confirmation_saves_every_line(session_factory):
    upload_id, card_id = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of())
    await run(graph, upload_id)

    result = await run(graph, upload_id, {"action": "confirm"})

    assert pending_interrupt(result) is None
    assert result["saved_count"] == 3
    rows = await transactions(session_factory)
    assert len(by_status(rows, "confirmed")) == 3
    assert by_status(rows, "pending") == []
    assert {t.card_id for t, _ in rows} == {card_id}
    assert all(t.confirmed_at is not None for t, _ in rows)
    assert await upload_status(session_factory, upload_id) == UploadStatus.DONE


async def test_the_extractor_gets_the_stashed_bytes_and_the_detected_format(
    session_factory,
):
    seen: list = []
    upload_id, _ = await new_statement(session_factory)
    await run(graph_for(session_factory, statement_of(), seen=seen), upload_id)
    content, fmt, categories, accounts = seen[0]
    assert (content, fmt) == (CSV, "csv")
    assert "Groceries" in categories


@pytest.mark.parametrize(
    ("filename", "mime", "fmt"),
    [
        ("march.pdf", "application/pdf", "pdf"),
        ("march.xlsx", None, "xlsx"),
        ("march", "text/csv", "csv"),
    ],
)
async def test_each_supported_format_is_detected(session_factory, filename, mime, fmt):
    seen: list = []
    upload_id, _ = await new_statement(session_factory, filename, mime or "x/y")
    await run(graph_for(session_factory, statement_of(), seen=seen), upload_id)
    assert seen[0][1] == fmt


# --- what is left out, and why ---


async def test_money_in_is_kept_and_unreadable_lines_are_counted_not_saved(
    session_factory,
):
    rows = [
        *THREE,
        line("Salary", 9_000_000, "2026-10-01", "Salary", direction="in"),
        ExtractedStatementRow(merchant="Blurry", amount=None, occurred_on="2026-10-04"),
        ExtractedStatementRow(merchant="Nodate", amount=100, occurred_on=None),
    ]
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of(rows))

    payload = pending_interrupt(await run(graph, upload_id))

    assert payload["summary"]["out"]["count"] == 3
    assert payload["summary"]["in"] == {
        "count": 1,
        "total": "9000000.00",
        "highest": "9000000.00",
        "lowest": "9000000.00",
    }
    assert payload["skipped_unreadable"] == 2
    stored = await transactions(session_factory)
    assert len(stored) == 4  # three out, one in; nothing guessed or stored for the rest
    directions = {t.merchant: t.direction for t, _ in stored}
    assert directions == {
        "Indomaret": "out",
        "Grab": "out",
        "Warung": "out",
        "Salary": "in",
    }


async def test_unknown_or_missing_categories_fall_back_to_other(session_factory):
    rows = [
        line("A", 10, "2026-10-01", "groceries"),  # case-insensitive match
        line("B", 20, "2026-10-01", "Yachts"),
        line("C", 30, "2026-10-01", None),
    ]
    upload_id, _ = await new_statement(session_factory)
    await run(graph_for(session_factory, statement_of(rows)), upload_id)
    names = {t.merchant: name for t, name in await transactions(session_factory)}
    assert names == {"A": "Groceries", "B": "Other", "C": "Other"}


async def test_a_statement_with_no_usable_lines_is_refused_and_saves_nothing(
    session_factory,
):
    unreadable = [
        ExtractedStatementRow(merchant="Blurry", amount=None, occurred_on="2026-10-04"),
        ExtractedStatementRow(merchant=None, amount=5, occurred_on="2026-10-04"),
    ]
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of(unreadable))
    with pytest.raises(StatementError, match="couldn't find any transactions"):
        await run(graph, upload_id)
    assert await transactions(session_factory) == []


async def test_an_unsupported_file_type_is_refused_before_the_model_is_called(
    session_factory,
):
    seen: list = []
    upload_id, _ = await new_statement(session_factory, "notes.txt", "text/plain")
    with pytest.raises(StatementError, match="PDF, CSV or Excel"):
        await run(graph_for(session_factory, statement_of(), seen=seen), upload_id)
    assert seen == []


async def test_a_model_failure_leaves_nothing_behind(session_factory):
    upload_id, _ = await new_statement(session_factory)
    with pytest.raises(LLMError):
        await run(graph_for(session_factory, LLMError("rate limited")), upload_id)
    assert await transactions(session_factory) == []


async def test_a_missing_file_fails_rather_than_guessing(session_factory):
    def gone(upload_id):
        raise LookupError("no file held")

    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of(), file_source=gone)
    with pytest.raises(LookupError):
        await run(graph, upload_id)


# --- choosing the card ---


async def test_without_a_card_it_asks_and_applies_the_choice_to_every_line(
    session_factory,
):
    upload_id, card_id = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of(card_hint=None))

    asked = pending_interrupt(await run(graph, upload_id))
    assert asked["missing"] == ["card"]
    assert asked["card"] is None
    assert [c["id"] for c in asked["cards"]] == [card_id]
    assert await upload_status(session_factory, upload_id) == UploadStatus.NEEDS_INPUT

    blocked = pending_interrupt(await run(graph, upload_id, {"action": "confirm"}))
    assert blocked["notice"] == "missing:card"
    assert by_status(await transactions(session_factory), "confirmed") == []

    ready = pending_interrupt(
        await run(graph, upload_id, {"action": "set_card", "card_id": card_id})
    )
    assert ready["missing"] == []
    assert ready["card"] == "BCA Visa 1234"
    rows = await transactions(session_factory)
    assert {t.card_id for t, _ in rows} == {card_id}

    result = await run(graph, upload_id, {"action": "confirm"})
    assert result["saved_count"] == 3
    assert len(by_status(await transactions(session_factory), "confirmed")) == 3


# --- duplicates of what is already saved ---


async def test_lines_already_saved_on_the_same_card_are_skipped(session_factory):
    upload_id, card_id = await new_statement(session_factory)
    await add_confirmed(
        session_factory, card_id, "indomaret", "45000", date(2026, 10, 1)
    )
    graph = graph_for(session_factory, statement_of())

    payload = pending_interrupt(await run(graph, upload_id))
    assert payload["duplicates"] == 1
    assert payload["summary"]["out"]["count"] == 2
    assert payload["summary"]["out"]["total"] == "55000.50"  # the duplicate is excluded

    result = await run(graph, upload_id, {"action": "confirm"})
    assert result["saved_count"] == 2
    rows = await transactions(session_factory)
    assert len(by_status(rows, "confirmed")) == 3  # the old one plus the two new
    assert by_status(rows, "pending") == []
    assert sorted(t.merchant for t, _ in rows) == ["Grab", "Warung", "indomaret"]


async def test_the_same_purchase_on_another_card_is_not_a_duplicate(session_factory):
    upload_id, _ = await new_statement(session_factory)
    async with session_factory() as session:
        other_bank = await BankRepository(session).add("Mandiri")
        other = await CardRepository(session).add(other_bank.id, "Debit", "9999")
    await add_confirmed(
        session_factory, other.id, "Indomaret", "45000", date(2026, 10, 1)
    )

    payload = pending_interrupt(
        await run(graph_for(session_factory, statement_of()), upload_id)
    )
    assert payload["duplicates"] == 0
    assert payload["summary"]["out"]["count"] == 3


async def test_identical_lines_within_one_statement_are_both_kept(session_factory):
    twice = [line("Kopi", 20000, "2026-10-01"), line("Kopi", 20000, "2026-10-01")]
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of(twice))
    payload = pending_interrupt(await run(graph, upload_id))
    assert payload["duplicates"] == 0
    assert payload["summary"]["out"]["count"] == 2
    result = await run(graph, upload_id, {"action": "confirm"})
    assert result["saved_count"] == 2


async def test_a_statement_that_is_already_fully_saved_finishes_without_asking(
    session_factory,
):
    upload_id, card_id = await new_statement(session_factory)
    for row in THREE:
        await add_confirmed(
            session_factory,
            card_id,
            row.merchant,
            str(row.amount),
            date.fromisoformat(row.occurred_on),
        )
    graph = graph_for(session_factory, statement_of())

    result = await run(graph, upload_id)

    assert pending_interrupt(result) is None  # nothing to confirm
    assert result["saved_count"] == 0
    rows = await transactions(session_factory)
    assert len(rows) == 3  # only the originals remain
    assert by_status(rows, "pending") == []
    assert await upload_status(session_factory, upload_id) == UploadStatus.DONE


# --- typed text during a statement ---


async def test_typed_text_cannot_correct_a_statement_so_chat_takes_over(
    session_factory,
):
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of())
    await run(graph, upload_id)
    before = await transactions(session_factory)

    after = pending_interrupt(
        await run(graph, upload_id, {"action": "text", "text": "how am I doing?"})
    )

    assert after["notice"] == NOT_A_CORRECTION
    assert [t.id for t, _ in await transactions(session_factory)] == [
        t.id for t, _ in before
    ]
    assert after["summary"]["out"]["count"] == 3


# --- privacy and durability ---


async def test_a_statement_confirmation_survives_a_restart(
    session_factory, test_database_url
):
    conn = test_database_url.replace("+asyncpg", "", 1)
    upload_id, _ = await new_statement(session_factory)

    async with AsyncPostgresSaver.from_conn_string(conn) as saver:
        await saver.setup()
        graph = graph_for(session_factory, statement_of(), saver=saver)
        assert pending_interrupt(await run(graph, upload_id)) is not None

    async with AsyncPostgresSaver.from_conn_string(conn) as saver:  # a "restart"
        graph = graph_for(session_factory, statement_of(), saver=saver)
        result = await run(graph, upload_id, {"action": "confirm"})

    assert result["saved_count"] == 3
    assert await upload_status(session_factory, upload_id) == UploadStatus.DONE


async def test_statement_bytes_never_reach_the_checkpoint_tables(
    session_factory, test_database_url
):
    secret = b"Date,Merchant,Amount\n2026-10-01,PRIVATE-STATEMENT-LINE,12345\n"
    conn = test_database_url.replace("+asyncpg", "", 1)
    upload_id, _ = await new_statement(session_factory)

    async with AsyncPostgresSaver.from_conn_string(conn) as saver:
        await saver.setup()
        graph = graph_for(
            session_factory, statement_of(), saver=saver, file_source=lambda _: secret
        )
        await run(graph, upload_id)
        await run(graph, upload_id, {"action": "confirm"})

    queries = (
        "select count(*) from checkpoint_blobs where position(:raw in blob) > 0",
        "select count(*) from checkpoint_writes where position(:raw in blob) > 0",
        "select count(*) from checkpoints where checkpoint::text like :b64",
        "select count(*) from checkpoints where metadata::text like :b64",
    )
    params = {"raw": secret, "b64": f"%{base64.b64encode(secret).decode()[:16]}%"}
    engine = create_async_engine(test_database_url)
    async with engine.connect() as db:
        hits = [
            await db.scalar(text(sql), {k: v for k, v in params.items() if k in sql})
            for sql in queries
        ]
    await engine.dispose()
    assert hits == [0, 0, 0, 0]


async def test_categories_are_seeded_for_these_tests(session_factory):
    async with session_factory() as session:
        assert await CategoryRepository(session).get_id_by_name("Other") is not None


# --- money in and money out ---


async def test_confirming_saves_both_directions_with_the_right_labels(session_factory):
    rows = [
        line("Indomaret", 45000, "2026-10-01"),
        line("Salary", 9_000_000, "2026-10-01", "Salary", direction="in"),
        line("Refund Tokopedia", 150000, "2026-10-02", "Refund", direction="in"),
    ]
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of(rows))
    await run(graph, upload_id)

    result = await run(graph, upload_id, {"action": "confirm"})

    assert result["saved_count"] == 3
    saved = {
        t.merchant: (t.direction, name)
        for t, name in await transactions(session_factory)
    }
    assert saved == {
        "Indomaret": ("out", "Groceries"),
        "Salary": ("in", "Salary"),
        "Refund Tokopedia": ("in", "Refund"),
    }
    assert all(t.status == "confirmed" for t, _ in await transactions(session_factory))


async def test_a_statement_of_only_money_in_is_valid(session_factory):
    only_in = [line("Salary", 9_000_000, "2026-10-01", "Salary", direction="in")]
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of(only_in))

    payload = pending_interrupt(await run(graph, upload_id))
    assert payload["summary"]["out"]["count"] == 0
    assert payload["summary"]["in"]["count"] == 1

    result = await run(graph, upload_id, {"action": "confirm"})
    assert result["saved_count"] == 1


async def test_a_refund_is_not_mistaken_for_the_purchase_it_undoes(session_factory):
    upload_id, card_id = await new_statement(session_factory)
    # The purchase is already saved; the statement now shows the same amount coming in.
    await add_confirmed(
        session_factory, card_id, "Tokopedia", "154900", date(2026, 10, 6)
    )
    refund = [line("Tokopedia", 154900, "2026-10-06", "Refund", direction="in")]
    graph = graph_for(session_factory, statement_of(refund))

    payload = pending_interrupt(await run(graph, upload_id))

    assert (
        payload["duplicates"] == 0
    )  # same merchant, date and amount, but opposite way
    assert payload["summary"]["in"]["count"] == 1


async def test_money_in_that_is_already_saved_is_skipped_like_any_duplicate(
    session_factory,
):
    upload_id, card_id = await new_statement(session_factory)
    async with session_factory() as session:
        session.add(
            Transaction(
                card_id=card_id,
                merchant="Salary",
                amount=Decimal("9000000"),
                occurred_on=date(2026, 10, 1),
                direction="in",
                status="confirmed",
            )
        )
        await session.commit()
    again = [line("Salary", 9_000_000, "2026-10-01", "Salary", direction="in")]
    graph = graph_for(session_factory, statement_of(again))

    result = await run(graph, upload_id)  # nothing new, so it finishes by itself

    assert pending_interrupt(result) is None
    assert result["saved_count"] == 0


async def test_the_model_not_giving_a_direction_means_money_out(session_factory):
    unspecified = ExtractedStatementRow(
        merchant="Kopi", amount=20000, occurred_on="2026-10-01"
    )
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of([unspecified]))
    await run(graph, upload_id)
    ((tx, _),) = await transactions(session_factory)
    assert tx.direction == "out"


# --- transfers between the user's own accounts ---


async def test_moves_between_own_accounts_are_listed_apart_not_counted(session_factory):
    rows = [
        line("Indomaret", 45000, "2026-10-01"),
        line("Salary", 9_000_000, "2026-10-01", "Salary", direction="in"),
        line("Pay BCA Visa 1234", 2_000_000, "2026-10-02", "Transfer"),
        line("Payment received", 500_000, "2026-10-03", "transfer", direction="in"),
    ]
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of(rows))

    payload = pending_interrupt(await run(graph, upload_id))

    assert payload["summary"]["out"]["count"] == 1  # only the real purchase
    assert payload["summary"]["out"]["total"] == "45000.00"
    assert payload["summary"]["in"]["count"] == 1  # only the real income
    assert payload["summary"]["in"]["total"] == "9000000.00"
    assert payload["transfers"] == {"count": 2, "total": "2500000.00"}


async def test_transfers_are_still_saved_when_the_statement_is_confirmed(
    session_factory,
):
    rows = [
        line("Indomaret", 45000, "2026-10-01"),
        line("Top up e-wallet", 100_000, "2026-10-02", "Transfer"),
    ]
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of(rows))
    await run(graph, upload_id)

    result = await run(graph, upload_id, {"action": "confirm"})

    assert result["saved_count"] == 2  # listed and filterable, just not counted
    saved = {
        t.merchant: (name, t.status) for t, name in await transactions(session_factory)
    }
    assert saved["Top up e-wallet"] == ("Transfer", "confirmed")


async def test_money_sent_to_a_person_or_merchant_still_counts_as_spending(
    session_factory,
):
    # The model gave these ordinary categories, not Transfer, so they are expenses.
    rows = [
        line("Transfer to Budi", 250_000, "2026-10-02", "Other"),
        line("Bayar Warung Bu Sari", 80_000, "2026-10-03", "Dining"),
    ]
    upload_id, _ = await new_statement(session_factory)
    graph = graph_for(session_factory, statement_of(rows))

    payload = pending_interrupt(await run(graph, upload_id))

    assert payload["summary"]["out"]["count"] == 2
    assert payload["summary"]["out"]["total"] == "330000.00"
    assert payload["transfers"] == {"count": 0, "total": "0.00"}


async def test_the_model_is_told_which_cards_are_the_users_own(session_factory):
    seen: list = []
    upload_id, _ = await new_statement(session_factory)
    async with session_factory() as session:
        bank = await BankRepository(session).add("Mandiri")
        await CardRepository(session).add(bank.id, "Debit", "9999")
    await run(graph_for(session_factory, statement_of(), seen=seen), upload_id)

    own_accounts = seen[0][3]
    assert sorted(own_accounts) == ["BCA Visa 1234", "Mandiri Debit 9999"]


async def test_with_no_cards_registered_the_model_gets_an_empty_list(session_factory):
    seen: list = []
    upload_id, _ = await new_statement(session_factory, with_card=False)
    await run(
        graph_for(session_factory, statement_of(card_hint=None), seen=seen), upload_id
    )
    assert seen[0][3] == []
