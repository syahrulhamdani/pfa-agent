"""Routes for monthly budgets and savings goals."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.api.deps import get_session
from pfa.core.config import Settings, get_settings
from pfa.core.exceptions import NotFoundError
from pfa.schemas.budgets import (
    BudgetsCopied,
    BudgetsCopy,
    BudgetSet,
    BudgetsRead,
    BudgetVersionRead,
    GoalCreate,
    GoalRead,
    GoalUpdate,
    MonthText,
)
from pfa.services.analytics import today_in
from pfa.services.budgets import (
    budget_history,
    build_budgets,
    copy_budgets,
    parse_month,
    set_budget,
)
from pfa.services.goals import create_goal, delete_goal, list_goals, update_goal

router = APIRouter(tags=["budgets and goals"])
Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]
Month = Annotated[MonthText | None, Query()]


@router.get("/budgets", response_model=BudgetsRead)
async def get_budgets(session: Session, settings: Config, month: Month = None):
    """Returns the budgets that apply to a month (this month by default), with spent."""
    first = parse_month(month) if month else today_in(settings.timezone).replace(day=1)
    return await build_budgets(session, first)


@router.put("/budgets", response_model=BudgetVersionRead)
async def put_budget(body: BudgetSet, session: Session):
    """Sets a budget. This adds a new version; earlier versions are kept."""
    try:
        return await set_budget(
            session, body.category, parse_month(body.month), body.amount
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None


@router.post("/budgets/copy", response_model=BudgetsCopied)
async def copy_month_budgets(body: BudgetsCopy, session: Session):
    """Copies one month's budgets into another, never overwriting an existing one."""
    return await copy_budgets(
        session, parse_month(body.from_month), parse_month(body.to_month)
    )


@router.get("/budgets/history", response_model=list[BudgetVersionRead])
async def get_budget_history(
    session: Session,
    category: Annotated[str, Query(min_length=1, max_length=50)],
    month: Annotated[MonthText, Query()],
):
    """Lists every version of one category's budget for a month, newest first."""
    try:
        return await budget_history(session, category, parse_month(month))
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None


@router.get("/goals", response_model=list[GoalRead])
async def get_goals(session: Session, settings: Config):
    """Lists savings goals, the nearest target date first."""
    return await list_goals(session, today_in(settings.timezone))


@router.post("/goals", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
async def post_goal(body: GoalCreate, session: Session, settings: Config):
    """Creates a savings goal."""
    return await create_goal(session, body, today_in(settings.timezone))


@router.patch("/goals/{goal_id}", response_model=GoalRead)
async def patch_goal(
    goal_id: int, body: GoalUpdate, session: Session, settings: Config
):
    """Changes a goal: its name, target, date or saved amount."""
    try:
        return await update_goal(session, goal_id, body, today_in(settings.timezone))
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_goal(goal_id: int, session: Session):
    """Deletes a goal."""
    try:
        await delete_goal(session, goal_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
