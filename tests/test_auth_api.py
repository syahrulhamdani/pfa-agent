"""Boundary: a Telegram link is exchanged once for a session; routes need it."""

import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from pfa.core.config import Settings, get_settings
from pfa.main import app
from pfa.models import LoginToken
from pfa.repository.finance import LoginTokenRepository
from pfa.schemas.auth import TokenType
from pfa.services.auth import (
    SESSION_COOKIE,
    create_token,
    decode_token,
    issue_login_link,
)


def token_from(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


async def fresh_token(session_factory, api_settings) -> str:
    return token_from(await issue_login_link(session_factory, api_settings))


async def exchange(client, token):
    return await client.post("/auth/exchange", json={"token": token})


# --- issuing a link ---


async def test_a_link_lands_on_the_dashboard_unless_told_otherwise(
    session_factory, api_settings
):
    link = await issue_login_link(session_factory, api_settings)
    assert parse_qs(urlparse(link).query)["next"] == ["/dashboard"]


async def test_link_points_at_the_web_app_and_records_the_token(
    session_factory, api_settings
):
    link = await issue_login_link(session_factory, api_settings, "/budgets")
    parsed = urlparse(link)
    assert link.startswith(api_settings.web_base_url + "/auth?")
    assert parse_qs(parsed.query)["next"] == ["/budgets"]

    claims = decode_token(api_settings.auth_secret, token_from(link), TokenType.LOGIN)
    async with session_factory() as session:
        stored = await session.scalar(
            select(LoginToken).where(LoginToken.jti == claims["jti"])
        )
    assert stored is not None
    assert stored.used_at is None


async def test_issuing_drops_long_expired_links(session_factory, api_settings):
    now = datetime.now(UTC)
    async with session_factory() as session:
        repo = LoginTokenRepository(session)
        await repo.add("old", now - timedelta(days=3), now - timedelta(days=3))
        await repo.add("recent", now - timedelta(hours=1), now - timedelta(hours=1))
    await issue_login_link(session_factory, api_settings)
    async with session_factory() as session:
        jtis = set(await session.scalars(select(LoginToken.jti)))
    assert "old" not in jtis
    assert "recent" in jtis


# --- exchanging a link ---


async def test_exchange_sets_a_locked_down_session_cookie(
    anon_client, session_factory, api_settings
):
    response = await exchange(
        anon_client, await fresh_token(session_factory, api_settings)
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE}=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert f"max-age={7 * 24 * 3600}" in cookie
    assert "path=/" in cookie
    assert (await anon_client.get("/auth/me")).status_code == 200


async def test_a_link_works_only_once(anon_client, session_factory, api_settings):
    token = await fresh_token(session_factory, api_settings)
    assert (await exchange(anon_client, token)).status_code == 200
    again = await exchange(anon_client, token)
    assert again.status_code == 401
    assert "/login" in again.json()["detail"]


async def test_simultaneous_use_of_one_link_succeeds_only_once(
    anon_client, session_factory, api_settings
):
    token = await fresh_token(session_factory, api_settings)
    results = await asyncio.gather(*[exchange(anon_client, token) for _ in range(5)])
    assert sorted(r.status_code for r in results) == [200, 401, 401, 401, 401]


async def test_expired_link_is_rejected(anon_client, session_factory, api_settings):
    past = datetime.now(UTC) - timedelta(hours=1)
    token, jti, expires = create_token(
        api_settings.auth_secret, TokenType.LOGIN, timedelta(minutes=10), now=past
    )
    async with session_factory() as session:
        await LoginTokenRepository(session).add(jti, expires, past)
    assert (await exchange(anon_client, token)).status_code == 401


async def test_a_signed_link_we_never_issued_is_rejected(anon_client, api_settings):
    token, _, _ = create_token(
        api_settings.auth_secret, TokenType.LOGIN, timedelta(minutes=10)
    )
    assert (await exchange(anon_client, token)).status_code == 401


async def test_a_session_token_cannot_be_used_as_a_link(anon_client, api_settings):
    token, _, _ = create_token(
        api_settings.auth_secret, TokenType.SESSION, timedelta(days=1)
    )
    assert (await exchange(anon_client, token)).status_code == 401


@pytest.mark.parametrize("token", ["garbage", "a.b.c"])
async def test_garbage_link_is_rejected(anon_client, token):
    assert (await exchange(anon_client, token)).status_code == 401


@pytest.mark.parametrize("token", ["", "x" * 2049])
async def test_empty_or_oversized_token_is_a_validation_error(anon_client, token):
    assert (await exchange(anon_client, token)).status_code == 422


async def test_cookie_is_marked_secure_when_configured(
    anon_client, session_factory, api_settings
):
    secure = Settings(**{**api_settings.model_dump(), "auth_cookie_secure": True})
    app.dependency_overrides[get_settings] = lambda: secure
    response = await exchange(anon_client, await fresh_token(session_factory, secure))
    assert "secure" in response.headers["set-cookie"].lower()


# --- the session guards every data route ---

PROTECTED = [
    ("GET", "/transactions"),
    ("GET", "/transactions/today"),
    ("GET", "/categories"),
    ("GET", "/banks"),
    ("POST", "/banks"),
    ("GET", "/cards"),
    ("POST", "/banks/1/cards"),
    ("GET", "/auth/me"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_data_routes_need_a_session(anon_client, method, path):
    response = await anon_client.request(method, path, json={})
    assert response.status_code == 401
    assert "Telegram" in response.json()["detail"]


@pytest.mark.parametrize(("method", "path"), PROTECTED[:6])
async def test_data_routes_work_with_a_session(authed_client, method, path):
    response = await authed_client.request(method, path, json={"name": "Bank"})
    assert response.status_code in (200, 201)


async def test_a_login_token_is_not_a_session(
    anon_client, session_factory, api_settings
):
    token = await fresh_token(session_factory, api_settings)
    anon_client.cookies.set(SESSION_COOKIE, token)
    assert (await anon_client.get("/auth/me")).status_code == 401


async def test_an_expired_session_is_rejected(anon_client, api_settings):
    past = datetime.now(UTC) - timedelta(days=30)
    token, _, _ = create_token(
        api_settings.auth_secret, TokenType.SESSION, timedelta(days=7), now=past
    )
    anon_client.cookies.set(SESSION_COOKIE, token)
    assert (await anon_client.get("/transactions")).status_code == 401


async def test_a_session_signed_with_another_secret_is_rejected(anon_client):
    token, _, _ = create_token(
        "another-secret-" + "q" * 32, TokenType.SESSION, timedelta(days=1)
    )
    anon_client.cookies.set(SESSION_COOKIE, token)
    assert (await anon_client.get("/transactions")).status_code == 401


async def test_health_and_exchange_stay_open(anon_client):
    assert (await anon_client.get("/health")).status_code == 200
    assert (await exchange(anon_client, "garbage")).status_code == 401  # not 403/404


async def test_logout_ends_the_session(anon_client, session_factory, api_settings):
    await exchange(anon_client, await fresh_token(session_factory, api_settings))
    assert (await anon_client.get("/auth/me")).status_code == 200
    assert (await anon_client.post("/auth/logout")).status_code == 200
    assert (await anon_client.get("/auth/me")).status_code == 401


# --- the owner is told on Telegram when a link is used ---


@pytest.fixture
def fake_bot(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    bot = SimpleNamespace(send_message=AsyncMock())
    monkeypatch.setattr(app.state, "telegram", SimpleNamespace(bot=bot), raising=False)
    return bot


async def test_successful_sign_in_notifies_the_owner_on_telegram(
    anon_client, session_factory, api_settings, fake_bot
):
    token = await fresh_token(session_factory, api_settings)
    assert (await exchange(anon_client, token)).status_code == 200
    fake_bot.send_message.assert_awaited_once()
    kwargs = fake_bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == api_settings.telegram_chat_id
    assert kwargs["text"].startswith("Signed in to the web app on ")
    assert "AUTH_SECRET" not in kwargs["text"]  # no internals in user-facing text
    assert token not in kwargs["text"]  # the notice never repeats the credential


async def test_rejected_links_do_not_notify(
    anon_client, session_factory, api_settings, fake_bot
):
    token = await fresh_token(session_factory, api_settings)
    await exchange(anon_client, token)
    fake_bot.send_message.reset_mock()
    assert (await exchange(anon_client, token)).status_code == 401  # reused
    assert (await exchange(anon_client, "garbage")).status_code == 401
    fake_bot.send_message.assert_not_called()


async def test_a_failing_notice_never_blocks_sign_in(
    anon_client, session_factory, api_settings, fake_bot
):
    fake_bot.send_message.side_effect = RuntimeError("telegram down")
    token = await fresh_token(session_factory, api_settings)
    response = await exchange(anon_client, token)
    assert response.status_code == 200
    assert (await anon_client.get("/auth/me")).status_code == 200


# --- /signout ends every session and every unused link ---


async def revoke_a_minute_ago(session_factory):
    """Revokes at a fixed earlier moment, so tests can sign in again straight after."""
    from pfa.services.auth import revoke_all_sessions

    await revoke_all_sessions(
        session_factory, now=datetime.now(UTC) - timedelta(minutes=1)
    )


def old_session_cookie(api_settings) -> str:
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    token, _, _ = create_token(
        api_settings.auth_secret, TokenType.SESSION, timedelta(days=7), now=long_ago
    )
    return token


async def test_signout_ends_sessions_issued_before_it(
    anon_client, session_factory, api_settings
):
    anon_client.cookies.set(SESSION_COOKIE, old_session_cookie(api_settings))
    assert (await anon_client.get("/auth/me")).status_code == 200  # valid so far

    await revoke_a_minute_ago(session_factory)

    assert (await anon_client.get("/auth/me")).status_code == 401
    assert (await anon_client.get("/transactions")).status_code == 401


async def test_signing_in_again_after_signout_works(
    anon_client, session_factory, api_settings
):
    await revoke_a_minute_ago(session_factory)
    token = await fresh_token(session_factory, api_settings)
    assert (await exchange(anon_client, token)).status_code == 200
    assert (await anon_client.get("/auth/me")).status_code == 200


async def test_signout_kills_unused_links(anon_client, session_factory, api_settings):
    from pfa.services.auth import revoke_all_sessions

    token = await fresh_token(session_factory, api_settings)  # issued, not yet used
    await revoke_all_sessions(session_factory)
    response = await exchange(anon_client, token)
    assert response.status_code == 401
    assert "/login" in response.json()["detail"]


async def test_revoking_twice_keeps_one_row_and_the_latest_time(session_factory):
    from sqlalchemy import func

    from pfa.models import AuthState
    from pfa.repository.finance import AuthStateRepository
    from pfa.services.auth import revoke_all_sessions

    first = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    second = first + timedelta(hours=1)
    await revoke_all_sessions(session_factory, now=first)
    await revoke_all_sessions(session_factory, now=second)
    async with session_factory() as session:
        rows = await session.scalar(select(func.count()).select_from(AuthState))
        stored = await AuthStateRepository(session).sessions_valid_after()
    assert rows == 1
    assert stored == second


async def test_the_sign_in_notice_offers_signout():
    from pfa.bot.formatting import signed_in_text

    assert "/signout" in signed_in_text(datetime(2026, 10, 6, 11, 23))


async def test_signout_during_an_exchange_leaves_no_working_session(
    anon_client, session_factory, api_settings, monkeypatch
):
    from pfa.services.auth import revoke_all_sessions

    original = LoginTokenRepository.consume

    async def consume_then_signout(self, jti, now):
        used = await original(self, jti, now)
        await revoke_all_sessions(session_factory)  # /signout lands mid-exchange
        return used

    monkeypatch.setattr(LoginTokenRepository, "consume", consume_then_signout)
    token = await fresh_token(session_factory, api_settings)

    response = await exchange(anon_client, token)

    assert response.status_code == 401
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")
    assert (await anon_client.get("/auth/me")).status_code == 401
