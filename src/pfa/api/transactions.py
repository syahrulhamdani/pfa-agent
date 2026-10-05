"""Routes for transactions."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.api.deps import get_session
from pfa.core.config import Settings, get_settings
from pfa.schemas.transactions import TransactionRead
from pfa.services.transactions import todays_transactions

router = APIRouter(tags=["transactions"])


@router.get("/transactions/today", response_model=list[TransactionRead])
async def list_today(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Lists transactions confirmed today, newest first."""
    return await todays_transactions(session, settings.timezone)
