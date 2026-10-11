"""Async repositories for budget versions and savings goals."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.models import BudgetVersion, Category, Goal


class BudgetRepository:
    """Stores budget versions. Nothing here ever changes or deletes a version."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def add_version(
        self, category_id: int, month: date, amount: Decimal
    ) -> BudgetVersion:
        """Saves `amount` as the newest version of a category's budget for a month.

        Edits to the same budget at the same moment queue up on a lock held until the
        commit, so each reads the version before it and none picks a number twice.
        """
        await self._session.execute(
            select(func.pg_advisory_xact_lock(category_id, month.toordinal()))
        )
        newest = await self._session.scalar(
            select(func.coalesce(func.max(BudgetVersion.version), 0)).where(
                BudgetVersion.category_id == category_id,
                BudgetVersion.month == month,
            )
        )
        created = BudgetVersion(
            category_id=category_id, month=month, amount=amount, version=newest + 1
        )
        self._session.add(created)
        await self._session.commit()
        await self._session.refresh(created)  # as the database stored it
        return created

    async def current_through(self, month: date) -> list[tuple[BudgetVersion, str]]:
        """Returns the current (highest) version of every budget up to a month.

        Includes earlier months so that a month without a budget of its own can fall
        back on one set before it, if the rules allow that.

        Returns:
            Rows of the version and its category name.
        """
        newest = (
            select(
                BudgetVersion.category_id,
                BudgetVersion.month,
                func.max(BudgetVersion.version).label("version"),
            )
            .where(BudgetVersion.month <= month)
            .group_by(BudgetVersion.category_id, BudgetVersion.month)
            .subquery()
        )
        rows = await self._session.execute(
            select(BudgetVersion, Category.name)
            .join(
                newest,
                (BudgetVersion.category_id == newest.c.category_id)
                & (BudgetVersion.month == newest.c.month)
                & (BudgetVersion.version == newest.c.version),
            )
            .join(Category, Category.id == BudgetVersion.category_id)
            .order_by(Category.name, BudgetVersion.month)
        )
        return [(version, name) for version, name in rows]

    async def history(self, category_id: int, month: date) -> list[BudgetVersion]:
        """Returns every version for a category and month, newest first."""
        result = await self._session.scalars(
            select(BudgetVersion)
            .where(
                BudgetVersion.category_id == category_id, BudgetVersion.month == month
            )
            .order_by(BudgetVersion.version.desc())
        )
        return list(result)


class GoalRepository:
    """Stores savings goals."""

    def __init__(self, session: AsyncSession) -> None:
        """Binds the repository to a session."""
        self._session = session

    async def add(self, **fields: Any) -> Goal:
        """Creates a goal."""
        goal = Goal(**fields)
        self._session.add(goal)
        await self._session.commit()
        await self._session.refresh(goal)  # as the database stored it
        return goal

    async def get(self, goal_id: int) -> Goal | None:
        """Returns a goal, or None."""
        return await self._session.get(Goal, goal_id)

    async def list_all(self) -> list[Goal]:
        """Returns goals, the nearest target date first."""
        result = await self._session.scalars(
            select(Goal).order_by(Goal.target_date, Goal.id)
        )
        return list(result)

    async def update(self, goal_id: int, **fields: Any) -> Goal | None:
        """Changes the given fields of a goal; returns it, or None if missing."""
        await self._session.execute(
            update(Goal).where(Goal.id == goal_id).values(**fields)
        )
        await self._session.commit()
        goal = await self.get(goal_id)
        if goal is not None:
            await self._session.refresh(goal)
        return goal

    async def delete(self, goal_id: int) -> bool:
        """Deletes a goal; returns whether it existed."""
        result = await self._session.execute(delete(Goal).where(Goal.id == goal_id))
        await self._session.commit()
        return result.rowcount > 0
