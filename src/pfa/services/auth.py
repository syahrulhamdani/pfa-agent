"""JWT sign-in: a short-lived single-use login link and a longer session cookie."""

import enum
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pfa.core.config import Settings
from pfa.core.exceptions import PfaError
from pfa.repository.finance import LoginTokenRepository

ALGORITHM = "HS256"
SESSION_COOKIE = "pfa_session"
OWNER = "owner"  # pfa has one user, so every token has the same subject


class AuthError(PfaError):
    """Raised when a token is missing, invalid, expired or of the wrong kind."""


class TokenType(enum.StrEnum):
    """A login link token cannot be used as a session, and the other way round."""

    LOGIN = "login"
    SESSION = "session"


def create_token(
    secret: str,
    token_type: TokenType,
    ttl: timedelta,
    now: datetime | None = None,
) -> tuple[str, str | None, datetime]:
    """Creates a signed token.

    Args:
        secret: The signing secret (`AUTH_SECRET`).
        token_type: Login link or session.
        ttl: How long the token stays valid.
        now: The issue time; injectable for tests.

    Returns:
        The token, its unique id (login tokens only, else None) and its expiry.
    """
    issued = now or datetime.now(UTC)
    expires = issued + ttl
    claims: dict[str, Any] = {
        "sub": OWNER,
        "typ": token_type.value,
        "iat": issued,
        "exp": expires,
    }
    jti = None
    if token_type is TokenType.LOGIN:
        jti = uuid.uuid4().hex
        claims["jti"] = jti
    return jwt.encode(claims, secret, algorithm=ALGORITHM), jti, expires


def decode_token(secret: str, token: str, expected: TokenType) -> dict[str, Any]:
    """Verifies a token's signature, expiry, subject and type.

    Raises:
        AuthError: If the token is not valid for the expected purpose.
    """
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],  # never trust the algorithm the token names
            options={"require": ["exp", "iat", "sub", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"invalid token: {exc}") from exc
    if claims["sub"] != OWNER or claims["typ"] != expected.value:
        raise AuthError("token is not valid for this purpose")
    if expected is TokenType.LOGIN and not claims.get("jti"):
        raise AuthError("login token has no id")
    return claims


async def issue_login_link(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    next_path: str = "/transactions/today",
    now: datetime | None = None,
) -> str:
    """Creates a single-use sign-in URL for the web app.

    The token is recorded so that the first successful use consumes it.
    """
    issued = now or datetime.now(UTC)
    token, jti, expires = create_token(
        settings.auth_secret,
        TokenType.LOGIN,
        timedelta(minutes=settings.auth_link_ttl_minutes),
        issued,
    )
    async with session_factory() as session:
        await LoginTokenRepository(session).add(jti, expires, issued)
    query = urlencode({"token": token, "next": next_path})
    return f"{settings.web_base_url}/auth?{query}"


LinkIssuer = Callable[[], Awaitable[str]]
