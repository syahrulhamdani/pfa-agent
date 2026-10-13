"""Weekly summaries: which week to write about, and writing each week only once.

The Monday job summarises the week that just ended (Monday to Sunday). A summary is
kept once per week: the job never rewrites or resends a finished week, while the
on-demand demo always writes a fresh one. A demo run in a week with nothing recorded
in the last full week falls back to the current week so far; that one is marked
partial, so the real Monday job still replaces it.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pfa.models import WeeklySummary
from pfa.repository.summaries import SummaryRepository
from pfa.schemas.analytics import Period
from pfa.schemas.insights import InsightFacts, WeeklySummaryRead
from pfa.services.analytics import today_in
from pfa.services.insights import gather_facts


def last_full_week(today: date) -> tuple[date, date]:
    """Returns the Monday and Sunday of the most recent week that has ended."""
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(days=7)
    return start, start + timedelta(days=6)


def this_week_start(today: date) -> date:
    """Returns the Monday of the week containing `today`."""
    return today - timedelta(days=today.weekday())


def read_summary(row: WeeklySummary) -> WeeklySummaryRead:
    """Turns a stored row back into the summary that was written."""
    facts = InsightFacts.model_validate(row.stats_json["facts"])
    return WeeklySummaryRead(
        week_start=row.week_start,
        week_end=facts.end,
        facts=facts,
        recommendations=[line for line in row.recommendations_text.split("\n") if line],
        source=row.stats_json.get("source", "model"),
        created_at=row.created_at,
    )


@dataclass(frozen=True)
class SummaryResult:
    """A summary and whether this call wrote it (False: it was already there)."""

    summary: WeeklySummaryRead
    created: bool


class SummaryService:
    """Writes weekly summaries through the recommendation graph."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        graph: CompiledStateGraph,
        timezone: str,
    ) -> None:
        """Keeps what is needed to read, write and run the graph."""
        self._session_factory = session_factory
        self._graph = graph
        self._timezone = timezone

    async def _run(self, week_start: date, today: date, partial: bool) -> SummaryResult:
        state = await self._graph.ainvoke(
            {"week_start": week_start, "today": today, "partial": partial},
            config={"run_name": "weekly_summary", "tags": ["pfa", "summary"]},
        )
        return SummaryResult(state["summary"], True)

    async def latest(self) -> WeeklySummaryRead | None:
        """Returns the most recent saved summary, or None."""
        async with self._session_factory() as session:
            row = await SummaryRepository(session).latest()
        return read_summary(row) if row else None

    async def monday_summary(self, now: datetime | None = None) -> SummaryResult:
        """Summarises the week that just ended, unless that is already done.

        Returns:
            The summary, with `created` False when a finished one already existed
            (so the caller must not send it again).
        """
        today = today_in(self._timezone, now)
        start, _ = last_full_week(today)
        async with self._session_factory() as session:
            row = await SummaryRepository(session).get(start)
        if row is not None:
            existing = read_summary(row)
            if not existing.facts.partial:
                return SummaryResult(existing, False)
        return await self._run(start, today, partial=False)

    async def demo_summary(self, now: datetime | None = None) -> SummaryResult:
        """Writes a fresh summary right now, for the demo.

        Uses the last full week, or the current week so far if the last one had
        nothing recorded.
        """
        today = today_in(self._timezone, now)
        start, _ = last_full_week(today)
        async with self._session_factory() as session:
            facts = await gather_facts(session, Period.WEEK, start, today)
        if facts.has_activity:
            return await self._run(start, today, partial=False)
        return await self._run(this_week_start(today), today, partial=True)
