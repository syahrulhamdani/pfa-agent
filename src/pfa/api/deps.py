"""FastAPI dependencies."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.core.config import Settings, get_settings
from pfa.services.auth import SESSION_COOKIE, AuthError, TokenType, decode_token


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yields a database session from the app's session factory."""
    async with request.app.state.session_factory() as session:
        yield session


async def require_session(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    """Rejects requests that lack a valid session cookie with a 401."""
    token = request.cookies.get(SESSION_COOKIE)
    try:
        if not token:
            raise AuthError("no session cookie")
        decode_token(settings.auth_secret, token, TokenType.SESSION)
    except AuthError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Sign in with the link from Telegram"
        ) from None
