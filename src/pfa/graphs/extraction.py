"""Extraction graph: read a receipt or statement, pause for the user, then save it.

Receipt: extract -> review (interrupt) -> confirm: commit
                                    -> card button or correction: apply -> review
                                    -> typed text: parse_text -> apply -> review
Statement: extract_statement -> review_statement (interrupt)
                                  -> confirm: commit_statement
                                  -> card button: apply_statement_card -> review
The pending row in Postgres is the source of truth; the graph state only carries
ids and the user's latest decision, so it stays small in the checkpointer.
"""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pfa.core.exceptions import StatementError
from pfa.models import Direction, UploadStatus
from pfa.repository.finance import (
    CardRepository,
    CategoryRepository,
    TransactionRepository,
    UploadRepository,
)
from pfa.schemas.extraction import (
    CorrectionResult,
    ExtractedReceipt,
    ExtractedStatement,
)
from pfa.schemas.statements import Spend, StatementFormat, StatementSummary
from pfa.schemas.transactions import PendingTransaction
from pfa.services.cards import infer_card
from pfa.services.pending import (
    apply_changes,
    load_pending,
    parse_amount,
    parse_date,
)
from pfa.services.statements import (
    SUPPORTED_TEXT,
    looks_like_duplicate,
    normalize_rows,
    statement_format,
    summarize_by_direction,
)
from pfa.services.validation import missing_fields

Extractor = Callable[[bytes, str, list[str]], Awaitable[ExtractedReceipt]]
FileSource = Callable[[int], bytes]
StatementExtractor = Callable[
    [bytes, StatementFormat, list[str]], Awaitable[ExtractedStatement]
]
CorrectionParser = Callable[
    [str, PendingTransaction, list[str], list[str]], Awaitable[CorrectionResult]
]

NOT_A_CORRECTION = "not_correction"


class ExtractionState(TypedDict, total=False):
    """Small state: ids plus the user's latest decision."""

    upload_id: int
    kind: str  # "image" or "statement"
    transaction_id: int  # receipts only
    skipped: dict[str, int]  # statements: lines left out, by reason
    saved_count: int  # statements: how many transactions were saved
    decision: dict[str, Any] | None
    notice: str | None


def thread_config(upload_id: int) -> dict[str, Any]:
    """Returns the run config for one upload's graph thread."""
    return {
        "configurable": {"thread_id": f"upload-{upload_id}"},
        "run_name": "extraction",
        "tags": ["pfa", "extraction"],
    }


def pending_interrupt(result: dict[str, Any]) -> dict[str, Any] | None:
    """Returns the review payload if the graph paused for the user, else None."""
    interrupts = result.get("__interrupt__")
    return interrupts[0].value if interrupts else None


def _summary_json(summary: StatementSummary) -> dict[str, Any]:
    """Turns a summary into plain JSON values, as the checkpointer needs."""
    return {
        "count": summary.count,
        "total": str(summary.total),
        "highest": None if summary.highest is None else str(summary.highest),
        "lowest": None if summary.lowest is None else str(summary.lowest),
    }


async def _statement_snapshot(session: AsyncSession, upload_id: int):
    """Loads a statement's pending lines and works out which are already saved.

    A line is a duplicate when `looks_like_duplicate` matches a transaction the user
    already confirmed on the same card in the same date range. Only the card's
    confirmed transactions count, never other lines of this statement.

    Returns:
        (pending, duplicate ids, lines that would be saved, the card id or None).
    """
    repo = TransactionRepository(session)
    pending = await repo.pending_for_upload(upload_id)
    card_id = next((t.card_id for t in pending if t.card_id is not None), None)
    duplicates: set[int] = set()
    if card_id is not None and pending:
        days = [t.occurred_on for t in pending]
        known = [
            Spend(
                merchant=e.merchant or "",
                amount=e.amount,
                occurred_on=e.occurred_on,
                direction=Direction(e.direction),
            )
            for e in await repo.confirmed_on_card_between(card_id, min(days), max(days))
            if e.amount is not None and e.occurred_on is not None
        ]
        duplicates = {
            t.id
            for t in pending
            if any(
                looks_like_duplicate(
                    Spend(
                        merchant=t.merchant,
                        amount=t.amount,
                        occurred_on=t.occurred_on,
                        direction=Direction(t.direction),
                    ),
                    k,
                )
                for k in known
            )
        }
    keep = [t for t in pending if t.id not in duplicates]
    return pending, duplicates, keep, card_id


def build_extraction_graph(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    extractor: Extractor,
    statement_extractor: StatementExtractor,
    file_source: FileSource,
    parse_correction: CorrectionParser,
    checkpointer: BaseCheckpointSaver,
    today: Callable[[], date] = date.today,
) -> CompiledStateGraph:
    """Builds the extraction graph.

    Args:
        session_factory: Creates database sessions.
        extractor: Reads receipt image bytes into fields (Gemini Pro in the app).
        statement_extractor: Reads a statement file into its lines (Gemini Pro).
        file_source: Returns the in-memory file for an upload id. Files are never
            stored in graph state, so the checkpointer never holds them.
        parse_correction: Interprets typed text as a correction (Flash Lite).
        checkpointer: Stores the paused state between Telegram messages.
        today: Returns the current date; injectable for tests.

    Returns:
        The compiled graph. Start it with `{"upload_id": id}`; resume it with
        `Command(resume={"action": ...})`.
    """

    async def extract(state: ExtractionState) -> dict:
        async with session_factory() as session:
            upload = await UploadRepository(session).get(state["upload_id"])
            categories = CategoryRepository(session)
            names = [c.name for c in await categories.list_all()]
            cards = await CardRepository(session).list_options()
            receipt = await extractor(
                file_source(state["upload_id"]), upload.mime_type, names
            )
            category_id = (
                await categories.get_id_by_name(receipt.category)
                if receipt.category
                else None
            )
            tx = await TransactionRepository(session).add_pending(
                upload.id,
                merchant=(receipt.merchant or "").strip() or None,
                amount=parse_amount(receipt.amount),
                occurred_on=parse_date(receipt.occurred_on),
                category_id=category_id,
                card_id=infer_card(receipt.card_hint, cards),
                description=(receipt.description or "").strip() or None,
            )
        return {"transaction_id": tx.id}

    async def review(state: ExtractionState) -> dict:
        async with session_factory() as session:
            view = await load_pending(session, state["transaction_id"])
            cards = await CardRepository(session).list_options()
            missing = missing_fields(view, today())
            await UploadRepository(session).set_status(
                state["upload_id"],
                (
                    UploadStatus.NEEDS_INPUT
                    if missing
                    else UploadStatus.AWAITING_CONFIRMATION
                ),
            )
        decision = interrupt(
            {
                "upload_id": state["upload_id"],
                "transaction": view.model_dump(mode="json"),
                "missing": missing,
                "cards": [c.model_dump() for c in cards],
                "notice": state.get("notice"),
            }
        )
        if decision.get("action") == "confirm" and missing:
            # Nothing is saved until every required field is present.
            return {
                "decision": {"action": "noop"},
                "notice": f"missing:{','.join(missing)}",
            }
        return {"decision": decision, "notice": None}

    def route_decision(state: ExtractionState) -> str:
        routes = {
            "confirm": "commit",
            "set_card": "apply",
            "correct": "apply",
            "text": "parse_text",
        }
        return routes.get(state["decision"]["action"], "review")

    async def parse_text(state: ExtractionState) -> dict:
        async with session_factory() as session:
            view = await load_pending(session, state["transaction_id"])
            names = [c.name for c in await CategoryRepository(session).list_all()]
            cards = await CardRepository(session).list_options()
        result = await parse_correction(
            state["decision"]["text"], view, names, [c.label for c in cards]
        )
        if not result.is_correction:
            return {"decision": {"action": "noop"}, "notice": NOT_A_CORRECTION}
        changes = result.model_dump(exclude={"is_correction"}, exclude_none=True)
        return {"decision": {"action": "correct", "changes": changes}}

    def route_after_parse(state: ExtractionState) -> str:
        return "apply" if state["decision"]["action"] == "correct" else "review"

    async def apply(state: ExtractionState) -> dict:
        decision = state["decision"]
        changes = decision.get("changes") or {}
        if decision["action"] == "set_card":
            changes = {"card_id": decision["card_id"]}
        async with session_factory() as session:
            cards = await CardRepository(session).list_options()
            rejected = await apply_changes(
                session, state["transaction_id"], changes, cards
            )
        return {
            "decision": None,
            "notice": f"rejected:{','.join(rejected)}" if rejected else None,
        }

    async def commit(state: ExtractionState) -> dict:
        async with session_factory() as session:
            await TransactionRepository(session).confirm(state["transaction_id"])
            await UploadRepository(session).set_status(
                state["upload_id"], UploadStatus.DONE
            )
        return {"decision": None}

    async def load(state: ExtractionState) -> dict:
        async with session_factory() as session:
            upload = await UploadRepository(session).get(state["upload_id"])
        return {"kind": upload.kind}

    def route_kind(state: ExtractionState) -> str:
        return "extract_statement" if state["kind"] == "statement" else "extract"

    async def extract_statement(state: ExtractionState) -> dict:
        async with session_factory() as session:
            upload = await UploadRepository(session).get(state["upload_id"])
            fmt = statement_format(upload.filename, upload.mime_type)
            if fmt is None:
                raise StatementError(f"I can read statements as {SUPPORTED_TEXT}.")
            categories = await CategoryRepository(session).list_all()
            cards = await CardRepository(session).list_options()
            statement = await statement_extractor(
                file_source(state["upload_id"]), fmt, [c.name for c in categories]
            )
            normalized = normalize_rows(statement.transactions)
            if not normalized.rows:
                raise StatementError(
                    "I couldn't find any transactions in this statement."
                )
            by_name = {c.name.casefold(): c.id for c in categories}
            fallback = by_name.get("other")  # a line with no usable category
            await TransactionRepository(session).add_pending_many(
                upload.id,
                infer_card(statement.card_hint, cards),
                [
                    {
                        "merchant": row.merchant,
                        "amount": row.amount,
                        "occurred_on": row.occurred_on,
                        "direction": row.direction.value,
                        "category_id": by_name.get(
                            (row.category or "").casefold(), fallback
                        ),
                        "description": row.description,
                    }
                    for row in normalized.rows
                ],
            )
        return {"skipped": {"unreadable": normalized.skipped_unreadable}}

    async def review_statement(state: ExtractionState) -> dict:
        async with session_factory() as session:
            _, duplicates, keep, card_id = await _statement_snapshot(
                session, state["upload_id"]
            )
            cards = await CardRepository(session).list_options()
            card = next((c for c in cards if c.id == card_id), None)
            totals = summarize_by_direction(
                (Direction(t.direction), t.amount) for t in keep
            )
            missing = [] if card_id is not None else ["card"]
            await UploadRepository(session).set_status(
                state["upload_id"],
                (
                    UploadStatus.NEEDS_INPUT
                    if missing
                    else UploadStatus.AWAITING_CONFIRMATION
                ),
            )
        if not keep and not missing:
            # Everything is already saved, so there is nothing to confirm: finish.
            return {"decision": {"action": "confirm"}, "notice": None}
        skipped = state.get("skipped") or {}
        decision = interrupt(
            {
                "kind": "statement",
                "upload_id": state["upload_id"],
                "summary": {
                    "out": _summary_json(totals.money_out),
                    "in": _summary_json(totals.money_in),
                },
                "card": card.label if card else None,
                "missing": missing,
                "cards": [c.model_dump() for c in cards],
                "duplicates": len(duplicates),
                "skipped_unreadable": skipped.get("unreadable", 0),
                "notice": state.get("notice"),
            }
        )
        action = decision.get("action")
        if action == "confirm" and missing:
            return {"decision": {"action": "noop"}, "notice": "missing:card"}
        if action == "text":
            # Typed text cannot correct a statement; let normal chat answer it.
            return {"decision": {"action": "noop"}, "notice": NOT_A_CORRECTION}
        return {"decision": decision, "notice": None}

    def route_statement_decision(state: ExtractionState) -> str:
        routes = {"confirm": "commit_statement", "set_card": "apply_statement_card"}
        return routes.get(state["decision"]["action"], "review_statement")

    async def apply_statement_card(state: ExtractionState) -> dict:
        async with session_factory() as session:
            await TransactionRepository(session).set_card_for_upload(
                state["upload_id"], state["decision"]["card_id"]
            )
        return {"decision": None, "notice": None}

    async def commit_statement(state: ExtractionState) -> dict:
        async with session_factory() as session:
            _, duplicates, keep, _ = await _statement_snapshot(
                session, state["upload_id"]
            )
            repo = TransactionRepository(session)
            await repo.delete_many(sorted(duplicates))  # already saved before
            await repo.confirm_many([t.id for t in keep])
            await UploadRepository(session).set_status(
                state["upload_id"], UploadStatus.DONE
            )
        return {"decision": None, "saved_count": len(keep)}

    graph = StateGraph(ExtractionState)
    graph.add_node("extract", extract)
    graph.add_node("review", review)
    graph.add_node("parse_text", parse_text)
    graph.add_node("apply", apply)
    graph.add_node("commit", commit)
    graph.add_node("load", load)
    graph.add_node("extract_statement", extract_statement)
    graph.add_node("review_statement", review_statement)
    graph.add_node("apply_statement_card", apply_statement_card)
    graph.add_node("commit_statement", commit_statement)
    graph.add_edge(START, "load")
    graph.add_conditional_edges("load", route_kind)
    graph.add_edge("extract_statement", "review_statement")
    graph.add_conditional_edges("review_statement", route_statement_decision)
    graph.add_edge("apply_statement_card", "review_statement")
    graph.add_edge("commit_statement", END)
    graph.add_edge("extract", "review")
    graph.add_conditional_edges("review", route_decision)
    graph.add_conditional_edges("parse_text", route_after_parse)
    graph.add_edge("apply", "review")
    graph.add_edge("commit", END)
    return graph.compile(checkpointer=checkpointer)
