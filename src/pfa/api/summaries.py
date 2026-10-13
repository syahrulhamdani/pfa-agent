"""Route for the latest weekly summary."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.api.deps import get_session
from pfa.repository.summaries import SummaryRepository
from pfa.schemas.insights import WeeklySummaryRead
from pfa.services.summaries import read_summary

router = APIRouter(tags=["summaries"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/summary", response_model=WeeklySummaryRead)
async def get_latest_summary(session: Session):
    """Returns the most recent weekly summary, exactly as it was written and sent."""
    row = await SummaryRepository(session).latest()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "There is no weekly summary yet. The first one arrives on Monday morning.",
        )
    return read_summary(row)
