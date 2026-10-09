"""Route for the dashboard's aggregated figures."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.api.deps import get_session
from pfa.core.config import Settings, get_settings
from pfa.schemas.analytics import AnalyticsRead, Period
from pfa.services.analytics import build_analytics, today_in

router = APIRouter(tags=["analytics"])
Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


@router.get("/analytics", response_model=AnalyticsRead)
async def get_analytics(
    session: Session,
    settings: Config,
    period: Period = Period.MONTH,
    on: Annotated[
        date | None, Query(alias="date", ge=date(1970, 1, 1), le=date(2100, 12, 31))
    ] = None,
):
    """Returns the dashboard for the period containing `date` (today by default).

    Money out and money in are reported apart, moves between the user's own accounts
    are left out of both, and the previous period is included for comparison.
    """
    anchor = on or today_in(settings.timezone)
    return await build_analytics(session, period, anchor)
