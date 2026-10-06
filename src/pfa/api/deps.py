"""FastAPI dependencies."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.core.config import Settings, get_settings
from pfa.repository.finance import AuthStateRepository
from pfa.services.auth import (
    SESSION_COOKIE,
    AuthError,
    TokenType,
    decode_token,
    session_is_revoked,
)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yields a database session from the app's session factory."""
    async with request.app.state.session_factory() as session:
        yield session


async def require_session(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Rejects requests without a valid, unrevoked session cookie with a 401."""
    token = request.cookies.get(SESSION_COOKIE)
    try:
        if not token:
            raise AuthError("no session cookie")
        claims = decode_token(settings.auth_secret, token, TokenType.SESSION)
        valid_after = await AuthStateRepository(session).sessions_valid_after()
        if session_is_revoked(claims["iat"], valid_after):
            raise AuthError("session was ended by /signout")
    except AuthError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Sign in with the link from Telegram"
        ) from None
