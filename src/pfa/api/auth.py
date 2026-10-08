"""Sign-in routes: exchange a Telegram link for a session cookie."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.api.deps import get_session, require_session
from pfa.bot.formatting import signed_in_text
from pfa.core.config import Settings, get_settings
from pfa.core.exceptions import AuthError
from pfa.repository.finance import AuthStateRepository, LoginTokenRepository
from pfa.schemas.auth import TokenType
from pfa.services.auth import (
    SESSION_COOKIE,
    create_token,
    decode_token,
    session_is_revoked,
)

router = APIRouter(prefix="/auth", tags=["auth"])
Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


class ExchangeRequest(BaseModel):
    """Body for exchanging a login link token."""

    token: str = Field(min_length=1, max_length=2048)


async def notify_sign_in(request: Request, settings: Settings) -> None:
    """Tells the owner on Telegram that a sign-in link was just used.

    Best effort: a failure here is logged and never affects the sign-in itself.
    """
    application = getattr(request.app.state, "telegram", None)
    if application is None:
        return
    try:
        when = datetime.now(ZoneInfo(settings.timezone))
        await application.bot.send_message(
            chat_id=settings.telegram_chat_id, text=signed_in_text(when)
        )
    except Exception:
        logger.exception("Could not send the sign-in notice")


@router.post("/exchange")
async def exchange(
    body: ExchangeRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    session: Session,
    settings: Config,
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
    # The session is stamped with the moment the exchange began, before the link is
    # consumed. A /signout landing at any point after that revokes this session too.
    issued_at = datetime.now(UTC)
    if not await LoginTokenRepository(session).consume(claims["jti"], issued_at):
        raise rejected

    days = settings.auth_session_days
    token, _, _ = create_token(
        settings.auth_secret,
        TokenType.SESSION,
        timedelta(days=days),
        now=issued_at,
    )
    valid_after = await AuthStateRepository(session).sessions_valid_after()
    if session_is_revoked(int(issued_at.timestamp()), valid_after):
        raise rejected  # /signout ran while this exchange was in flight
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=days * 24 * 3600,
        httponly=True,  # not readable by page scripts
        samesite="lax",  # not sent on cross-site POSTs
        secure=settings.auth_cookie_secure,
        path="/",
    )
    background.add_task(notify_sign_in, request, settings)  # after the response
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
