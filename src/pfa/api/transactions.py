"""Routes for transactions and categories."""

import calendar
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.api.deps import get_session
from pfa.core.config import Settings, get_settings
from pfa.core.exceptions import NotFoundError
from pfa.models.finance import Direction
from pfa.repository.finance import CategoryRepository
from pfa.schemas.transactions import (
    DateBasis,
    TransactionChange,
    TransactionFilter,
    TransactionRead,
    TransactionsChanged,
)
from pfa.services.transactions import (
    change_transactions,
    search_transactions,
    todays_transactions,
)

router = APIRouter(tags=["transactions"])
Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


@router.get("/transactions/today", response_model=list[TransactionRead])
async def list_today(session: Session, settings: Config):
    """Lists transactions confirmed today, newest first."""
    return await todays_transactions(session, settings.timezone)


@router.get("/transactions", response_model=list[TransactionRead])
async def list_transactions(
    session: Session,
    settings: Config,
    basis: DateBasis = DateBasis.OCCURRED,
    date_from: date | None = None,
    date_to: date | None = None,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
    min_amount: Annotated[Decimal | None, Query(ge=0)] = None,
    max_amount: Annotated[Decimal | None, Query(ge=0)] = None,
    category: Annotated[list[str] | None, Query()] = None,
    direction: Direction | None = None,
):
    """Lists confirmed transactions with optional filters, newest first.

    `basis` picks which date `date_from`, `date_to` and `month` apply to: the
    receipt date (`occurred`) or the day it was confirmed (`confirmed`). `month`
    (YYYY-MM) is a shorthand for the first to last day and cannot be combined with
    `date_from` or `date_to`. Repeat `category` to match several categories.
    """
    if month is not None:
        if date_from or date_to:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Use either month or date_from/date_to, not both",
            )
        year, number = map(int, month.split("-"))
        date_from = date(year, number, 1)
        date_to = date(year, number, calendar.monthrange(year, number)[1])
    try:
        flt = TransactionFilter(
            basis=basis,
            date_from=date_from,
            date_to=date_to,
            min_amount=min_amount,
            max_amount=max_amount,
            categories=category or [],
            direction=direction,
        )
    except ValidationError as exc:
        message = "; ".join(
            e["msg"].removeprefix("Value error, ") for e in exc.errors()
        )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message) from None
    return await search_transactions(session, settings.timezone, flt)


@router.patch("/transactions", response_model=TransactionsChanged)
async def change_saved_transactions(body: TransactionChange, session: Session):
    """Changes the category and/or direction of one or many saved transactions."""
    try:
        updated = await change_transactions(
            session, body.ids, body.category, body.direction
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    return TransactionsChanged(updated=updated)


@router.get("/categories", response_model=list[str])
async def list_categories(session: Session):
    """Lists category names for filter dropdowns."""
    return [c.name for c in await CategoryRepository(session).list_all()]
