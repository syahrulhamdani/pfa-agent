"""Async repository for weekly summaries."""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.models import WeeklySummary


class SummaryRepository:
    """Stores one summary per week."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def get(self, week_start: date) -> WeeklySummary | None:
        """Returns the summary of the week starting on `week_start`, or None."""
        return await self._session.scalar(
            select(WeeklySummary).where(WeeklySummary.week_start == week_start)
        )

    async def latest(self) -> WeeklySummary | None:
        """Returns the most recent week's summary, or None."""
        return await self._session.scalar(
            select(WeeklySummary).order_by(WeeklySummary.week_start.desc()).limit(1)
        )

    async def save(
        self, week_start: date, stats: dict[str, Any], recommendations_text: str
    ) -> WeeklySummary:
        """Saves a week's summary, replacing the one already there for that week.

        A week never has two rows: saving again (a demo, or a partial week that has
        since ended) replaces the earlier text and figures.
        """
        statement = insert(WeeklySummary).values(
            week_start=week_start,
            stats_json=stats,
            recommendations_text=recommendations_text,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[WeeklySummary.week_start],
            set_={
                "stats_json": statement.excluded.stats_json,
                "recommendations_text": statement.excluded.recommendations_text,
                "created_at": statement.excluded.created_at,
            },
        )
        await self._session.execute(statement)
        await self._session.commit()
        saved = await self.get(week_start)
        assert saved is not None
        await self._session.refresh(saved)
        return saved
