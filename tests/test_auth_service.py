"""Boundary: a token is accepted only if signed, current, and of the right kind."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from pfa.services.auth import (
    AuthError,
    TokenType,
    create_token,
    decode_token,
)

SECRET = "unit-test-secret-" + "k" * 32
TEN_MIN = timedelta(minutes=10)


def test_login_token_roundtrip_has_a_unique_id():
    token, jti, expires = create_token(SECRET, TokenType.LOGIN, TEN_MIN)
    claims = decode_token(SECRET, token, TokenType.LOGIN)
    assert claims["jti"] == jti
    assert claims["typ"] == "login"
    assert expires - datetime.now(UTC) <= TEN_MIN
    _, other_jti, _ = create_token(SECRET, TokenType.LOGIN, TEN_MIN)
    assert other_jti != jti


def test_session_token_roundtrip_has_no_id():
    token, jti, _ = create_token(SECRET, TokenType.SESSION, timedelta(days=7))
    assert jti is None
    assert decode_token(SECRET, token, TokenType.SESSION)["typ"] == "session"


def test_token_kinds_are_not_interchangeable():
    login, _, _ = create_token(SECRET, TokenType.LOGIN, TEN_MIN)
    session, _, _ = create_token(SECRET, TokenType.SESSION, TEN_MIN)
    with pytest.raises(AuthError):
        decode_token(SECRET, login, TokenType.SESSION)
    with pytest.raises(AuthError):
        decode_token(SECRET, session, TokenType.LOGIN)


def test_wrong_secret_is_rejected():
    token, _, _ = create_token(SECRET, TokenType.SESSION, TEN_MIN)
    with pytest.raises(AuthError):
        decode_token("a-different-secret-" + "z" * 32, token, TokenType.SESSION)


def test_expired_token_is_rejected():
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    token, _, _ = create_token(SECRET, TokenType.LOGIN, TEN_MIN, now=long_ago)
    with pytest.raises(AuthError):
        decode_token(SECRET, token, TokenType.LOGIN)


def test_tampered_payload_is_rejected():
    token, _, _ = create_token(SECRET, TokenType.SESSION, TEN_MIN)
    header, payload, signature = token.split(".")
    forged = jwt.encode(
        {"sub": "owner", "typ": "session", "iat": 1, "exp": 9999999999},
        "attacker-key-" + "a" * 32,
        algorithm="HS256",
    ).split(".")[1]
    with pytest.raises(AuthError):
        decode_token(SECRET, f"{header}.{forged}.{signature}", TokenType.SESSION)


def test_unsigned_alg_none_token_is_rejected():
    claims = {
        "sub": "owner",
        "typ": "session",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + TEN_MIN,
    }
    unsigned = jwt.encode(claims, key=None, algorithm="none")
    with pytest.raises(AuthError):
        decode_token(SECRET, unsigned, TokenType.SESSION)


@pytest.mark.parametrize("missing", ["exp", "iat", "sub", "typ"])
def test_tokens_missing_required_claims_are_rejected(missing):
    claims = {
        "sub": "owner",
        "typ": "session",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + TEN_MIN,
    }
    del claims[missing]
    with pytest.raises(AuthError):
        decode_token(SECRET, jwt.encode(claims, SECRET, "HS256"), TokenType.SESSION)


def test_wrong_subject_is_rejected():
    claims = {
        "sub": "someone-else",
        "typ": "session",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + TEN_MIN,
    }
    with pytest.raises(AuthError):
        decode_token(SECRET, jwt.encode(claims, SECRET, "HS256"), TokenType.SESSION)


def test_login_token_without_an_id_is_rejected():
    claims = {
        "sub": "owner",
        "typ": "login",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + TEN_MIN,
    }
    with pytest.raises(AuthError):
        decode_token(SECRET, jwt.encode(claims, SECRET, "HS256"), TokenType.LOGIN)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer xyz", "....."])
def test_garbage_is_rejected(garbage):
    with pytest.raises(AuthError):
        decode_token(SECRET, garbage, TokenType.SESSION)


# --- /signout: which sessions count as revoked ---


def test_never_revoked_means_no_session_is_revoked():
    from pfa.services.auth import session_is_revoked

    assert session_is_revoked(1_000, None) is False


def test_sessions_issued_before_or_in_the_revocation_second_are_revoked():
    from pfa.services.auth import session_is_revoked

    revoked_at = datetime(2026, 10, 6, 12, 0, 0, 900_000, tzinfo=UTC)
    second = int(revoked_at.timestamp())
    assert session_is_revoked(second - 3600, revoked_at) is True
    assert session_is_revoked(second, revoked_at) is True  # same second: revoked


def test_sessions_issued_after_the_revocation_second_are_valid():
    from pfa.services.auth import session_is_revoked

    revoked_at = datetime(2026, 10, 6, 12, 0, 0, 900_000, tzinfo=UTC)
    assert session_is_revoked(int(revoked_at.timestamp()) + 1, revoked_at) is False
