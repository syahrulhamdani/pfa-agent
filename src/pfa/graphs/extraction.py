"""Extraction graph: read a receipt, pause for the user, then save it.

Flow: extract -> review (interrupt) -> confirm: commit
                                    -> card button or correction: apply -> review
                                    -> typed text: parse_text -> apply -> review
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

from pfa.models import UploadStatus
from pfa.repository.finance import (
    CardRepository,
    CategoryRepository,
    TransactionRepository,
    UploadRepository,
)
from pfa.schemas.extraction import CorrectionResult, ExtractedReceipt
from pfa.schemas.transactions import PendingTransaction
from pfa.services.cards import infer_card
from pfa.services.pending import (
    apply_changes,
    load_pending,
    parse_amount,
    parse_date,
)
from pfa.services.validation import missing_fields

Extractor = Callable[[bytes, str, list[str]], Awaitable[ExtractedReceipt]]
ImageSource = Callable[[int], bytes]
CorrectionParser = Callable[
    [str, PendingTransaction, list[str], list[str]], Awaitable[CorrectionResult]
]

NOT_A_CORRECTION = "not_correction"


class ExtractionState(TypedDict, total=False):
    """Small state: ids plus the user's latest decision."""

    upload_id: int
    transaction_id: int
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


def build_extraction_graph(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    extractor: Extractor,
    image_source: ImageSource,
    parse_correction: CorrectionParser,
    checkpointer: BaseCheckpointSaver,
    today: Callable[[], date] = date.today,
) -> CompiledStateGraph:
    """Builds the extraction graph.

    Args:
        session_factory: Creates database sessions.
        extractor: Reads receipt image bytes into fields (Gemini Pro in the app).
        image_source: Returns the in-memory image for an upload id. Images are never
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
                image_source(state["upload_id"]), upload.mime_type, names
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

    graph = StateGraph(ExtractionState)
    graph.add_node("extract", extract)
    graph.add_node("review", review)
    graph.add_node("parse_text", parse_text)
    graph.add_node("apply", apply)
    graph.add_node("commit", commit)
    graph.add_edge(START, "extract")
    graph.add_edge("extract", "review")
    graph.add_conditional_edges("review", route_decision)
    graph.add_conditional_edges("parse_text", route_after_parse)
    graph.add_edge("apply", "review")
    graph.add_edge("commit", END)
    return graph.compile(checkpointer=checkpointer)
