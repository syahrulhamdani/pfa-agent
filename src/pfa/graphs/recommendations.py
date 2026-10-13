"""Recommendation graph: gather the facts, write advice from them, store the summary.

    gather (SQL) -> write (model, checked against the facts) -> store

The facts are computed in code. The model only writes words; if it fails, or quotes a
figure that is not in the facts, a template says the same things instead, so a summary
is always sent and always true.
"""

from datetime import date
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pfa.core.exceptions import LLMError
from pfa.graphs.insights import RECOMMEND_PROMPT, Writer, advice_lines
from pfa.repository.summaries import SummaryRepository
from pfa.schemas.analytics import Period
from pfa.schemas.insights import InsightFacts, WeeklySummaryRead
from pfa.services.insights import (
    fallback_recommendations,
    gather_facts,
    numbers_grounded,
    render_facts,
)

Source = Literal["model", "fallback"]


class SummaryState(TypedDict, total=False):
    """What flows through the graph. Only plain data, never a database object."""

    week_start: date
    today: date
    partial: bool
    facts: InsightFacts
    facts_text: str
    lines: list[str]
    source: Source
    summary: WeeklySummaryRead


def build_summary_graph(
    session_factory: async_sessionmaker[AsyncSession], writer: Writer
) -> CompiledStateGraph:
    """Builds the graph that produces and saves one week's summary.

    Args:
        session_factory: Where facts are read and the summary is saved.
        writer: Writes the advice from the facts text.

    Returns:
        A compiled graph. Invoke it with `week_start`, `today` and `partial`.
    """

    async def gather(state: SummaryState) -> dict:
        async with session_factory() as session:
            facts = await gather_facts(
                session,
                Period.WEEK,
                state["week_start"],
                state["today"],
                budget_month=state["today"].replace(day=1),
                partial=state["partial"],
            )
        return {"facts": facts, "facts_text": render_facts(facts)}

    async def write(state: SummaryState) -> dict:
        facts, facts_text = state["facts"], state["facts_text"]
        try:
            text = await writer(RECOMMEND_PROMPT, facts_text, "")
        except LLMError:
            logger.exception("Recommendation model failed; using the template")
            return {"lines": fallback_recommendations(facts), "source": "fallback"}
        lines = advice_lines(text)
        if not lines or not numbers_grounded("\n".join(lines), facts_text):
            logger.warning(
                "Recommendation quoted figures not in the facts; using template"
            )
            return {"lines": fallback_recommendations(facts), "source": "fallback"}
        return {"lines": lines, "source": "model"}

    async def store(state: SummaryState) -> dict:
        facts = state["facts"]
        async with session_factory() as session:
            saved = await SummaryRepository(session).save(
                facts.start,
                {
                    "facts": facts.model_dump(mode="json"),
                    "source": state["source"],
                },
                "\n".join(state["lines"]),
            )
            summary = WeeklySummaryRead(
                week_start=facts.start,
                week_end=facts.end,
                facts=facts,
                recommendations=state["lines"],
                source=state["source"],
                created_at=saved.created_at,
            )
        return {"summary": summary}

    graph = StateGraph(SummaryState)
    graph.add_node("gather", gather)
    graph.add_node("write", write)
    graph.add_node("store", store)
    graph.add_edge(START, "gather")
    graph.add_edge("gather", "write")
    graph.add_edge("write", "store")
    graph.add_edge("store", END)
    return graph.compile()
