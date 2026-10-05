"""Sign-in routes: exchange a Telegram link for a session cookie."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.api.deps import get_session, require_session
from pfa.core.config import Settings, get_settings
from pfa.repository.finance import LoginTokenRepository
from pfa.services.auth import (
    SESSION_COOKIE,
    AuthError,
    TokenType,
    create_token,
    decode_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


class ExchangeRequest(BaseModel):
    """Body for exchanging a login link token."""

    token: str = Field(min_length=1, max_length=2048)


@router.post("/exchange")
async def exchange(
    body: ExchangeRequest, response: Response, session: Session, settings: Config
) -> dict[str, bool]:
    """Trades a valid, unused login token for a session cookie.

    This is a POST done by the web page, not a GET on the link itself, so link
    previews and other bots that merely fetch the URL cannot use up the token.
    """
    rejected = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "This sign-in link is invalid, expired or already used. "
        "Send /login to pfa on Telegram for a new one.",
    )
    try:
        claims = decode_token(settings.auth_secret, body.token, TokenType.LOGIN)
    except AuthError:
        raise rejected from None
    if not await LoginTokenRepository(session).consume(
        claims["jti"], datetime.now(UTC)
    ):
        raise rejected

    days = settings.auth_session_days
    token, _, _ = create_token(
        settings.auth_secret, TokenType.SESSION, timedelta(days=days)
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=days * 24 * 3600,
        httponly=True,  # not readable by page scripts
        samesite="lax",  # not sent on cross-site POSTs
        secure=settings.auth_cookie_secure,
        path="/",
    )
    return {"authenticated": True}


@router.get("/me", dependencies=[Depends(require_session)])
async def me() -> dict[str, bool]:
    """Reports whether the caller has a valid session."""
    return {"authenticated": True}


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    """Clears the session cookie."""
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"authenticated": False}
