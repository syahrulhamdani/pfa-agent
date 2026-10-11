"""Savings goals: progress is the saved amount against the target."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfa.core.exceptions import NotFoundError
from pfa.models import Goal
from pfa.repository.budgets import GoalRepository
from pfa.schemas.budgets import GoalCreate, GoalRead, GoalUpdate


def goal_read(goal: Goal, today: date) -> GoalRead:
    """Shows a goal with its progress as of `today`."""
    return GoalRead(
        id=goal.id,
        name=goal.name,
        target_amount=goal.target_amount,
        target_date=goal.target_date,
        saved_amount=goal.saved_amount,
        progress=round(float(goal.saved_amount / goal.target_amount), 4),
        remaining=max(goal.target_amount - goal.saved_amount, Decimal("0.00")),
        days_left=(goal.target_date - today).days,
    )


async def list_goals(session: AsyncSession, today: date) -> list[GoalRead]:
    """Lists goals, the nearest target date first."""
    return [goal_read(g, today) for g in await GoalRepository(session).list_all()]


async def create_goal(session: AsyncSession, body: GoalCreate, today: date) -> GoalRead:
    """Creates a goal."""
    goal = await GoalRepository(session).add(
        name=body.name.strip(),
        target_amount=body.target_amount,
        target_date=body.target_date,
        saved_amount=body.saved_amount,
    )
    return goal_read(goal, today)


async def update_goal(
    session: AsyncSession, goal_id: int, body: GoalUpdate, today: date
) -> GoalRead:
    """Changes the fields that were sent.

    Raises:
        NotFoundError: If there is no such goal.
    """
    changes: dict[str, Any] = body.model_dump(exclude_none=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    goal = await GoalRepository(session).update(goal_id, **changes)
    if goal is None:
        raise NotFoundError("There is no such goal.")
    return goal_read(goal, today)


async def delete_goal(session: AsyncSession, goal_id: int) -> None:
    """Deletes a goal.

    Raises:
        NotFoundError: If there is no such goal.
    """
    if not await GoalRepository(session).delete(goal_id):
        raise NotFoundError("There is no such goal.")
