"""Boundary: the setup checks tell a newcomer what is wrong, and never print a secret.

What is tested: reading settings from the environment, spotting placeholders left over
from .env.example, the database and migration checks against real Postgres, the
Telegram and Gemini checks against a fake HTTP server, finding a chat id, and that no
secret ever appears in anything shown to the person running the checks.
"""

import os
from pathlib import Path

import httpx
import psycopg
import pytest

from pfa.cli import format_chats, format_report
from pfa.core.config import Settings
from pfa.services.diagnostics import (
    ChatDiscoveryError,
    check_database,
    check_gemini_key,
    check_gemini_models,
    check_migrations,
    check_settings,
    check_telegram_chat,
    check_telegram_token,
    describe_database,
    discover_chats,
    load_settings,
    migration_head,
    run_doctor,
)

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "987654:SECRET-TELEGRAM-TOKEN"
KEY = "SECRET-GEMINI-KEY"
PASSWORD = "hunter2"
GOOD_ENV = {
    "TELEGRAM_BOT_TOKEN": TOKEN,
    "TELEGRAM_CHAT_ID": "4242",
    "GEMINI_API_KEY": KEY,
    "AUTH_SECRET": "real-secret-" + "x" * 40,
    "TIMEZONE": "Asia/Jakarta",
    "CATEGORIES_FILE": str(ROOT / "config" / "categories.json"),
}
SETTING_NAMES = [
    "DATABASE_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GEMINI_API_KEY",
    "GEMINI_CHAT_MODEL",
    "GEMINI_EXTRACT_MODEL",
    "AUTH_SECRET",
    "TIMEZONE",
    "CATEGORIES_FILE",
]


@pytest.fixture
def set_env(monkeypatch):
    """Replaces the settings environment with exactly the given values."""
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)

    def _set(**values: str):
        for name, value in {**GOOD_ENV, **values}.items():
            monkeypatch.setenv(name, value)

    return _set


@pytest.fixture
def good_settings(set_env, test_database_url) -> Settings:
    set_env(DATABASE_URL=test_database_url)
    return Settings()  # type: ignore[call-arg]


def settings_with(**overrides) -> Settings:
    base = {
        "telegram_bot_token": TOKEN,
        "telegram_chat_id": 4242,
        "gemini_api_key": KEY,
        "auth_secret": "real-secret-" + "x" * 40,
        "categories_file": str(ROOT / "config" / "categories.json"),
        "database_url": f"postgresql+asyncpg://pfa:{PASSWORD}@localhost:1/none",
    }
    return Settings(**{**base, **overrides})


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def reply(status: int, body: dict | None = None):
    return lambda request: httpx.Response(status, json=body or {})


# --- reading the settings ---


def test_missing_settings_are_named_with_what_to_do(set_env, monkeypatch):
    set_env()
    for name in ("TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY", "AUTH_SECRET"):
        monkeypatch.delenv(name)
    settings, problems = load_settings()
    assert settings is None
    names = {p.name for p in problems}
    assert {"Setting TELEGRAM_BOT_TOKEN", "Setting GEMINI_API_KEY"} <= names
    assert all(not p.ok and ".env" in p.fix for p in problems)
    assert all(p.detail == "is missing" for p in problems)


def test_a_too_short_secret_is_explained(set_env):
    set_env(AUTH_SECRET="short")
    settings, problems = load_settings()
    assert settings is None
    (problem,) = problems
    assert problem.name == "Setting AUTH_SECRET"
    assert "at least 32" in problem.detail


def test_good_settings_load_without_complaint(set_env):
    set_env()
    settings, problems = load_settings()
    assert settings is not None and problems == []


# --- placeholders from .env.example ---


def test_every_placeholder_from_the_example_file_is_caught():
    settings = Settings(
        telegram_bot_token="replace-me",
        telegram_chat_id=0,
        gemini_api_key="replace-me",
        auth_secret="replace-me-with-at-least-32-random-characters",
    )
    checks = {c.name: c for c in check_settings(settings)}
    for name in (
        "Telegram token",
        "Telegram chat id",
        "Gemini API key",
        "Sign-in secret",
    ):
        assert not checks[name].ok and checks[name].fix
    assert "BotFather" in checks["Telegram token"].fix
    assert "pfa chat-id" in checks["Telegram chat id"].fix
    assert "aistudio.google.com" in checks["Gemini API key"].fix
    assert "secrets.token_urlsafe" in checks["Sign-in secret"].fix


def test_real_values_pass_and_the_categories_are_counted():
    checks = check_settings(settings_with())
    assert all(c.ok for c in checks)
    assert any(
        c.name == "Categories file" and "15 categories" in c.detail for c in checks
    )


def test_an_unknown_timezone_is_caught():
    checks = {c.name: c for c in check_settings(settings_with(timezone="Mars/Olympus"))}
    assert not checks["Timezone"].ok
    assert "Asia/Jakarta" in checks["Timezone"].fix


def test_a_missing_categories_file_is_caught():
    checks = {
        c.name: c
        for c in check_settings(settings_with(categories_file="/nowhere/c.json"))
    }
    assert not checks["Categories file"].ok


# --- the database ---


def test_the_database_is_described_without_its_password():
    text = describe_database(
        f"postgresql+asyncpg://pfa:{PASSWORD}@db.example:6543/shop"
    )
    assert text == "db.example:6543/shop" and PASSWORD not in text


async def test_a_reachable_database_is_reported(good_settings):
    check = await check_database(good_settings)
    assert check.ok and "localhost:5433/pfa_test" in check.detail


async def test_an_unreachable_database_says_how_to_start_it():
    check = await check_database(settings_with())
    assert not check.ok
    assert "docker compose up -d db" in check.fix
    assert PASSWORD not in check.detail + check.fix  # the password never shows


async def test_migrations_up_to_date(good_settings):
    check = await check_migrations(good_settings)
    assert check.ok and migration_head() in check.detail


@pytest.fixture
def blank_database():
    """An empty scratch database, removed afterwards."""
    name = "pfa_doctor_scratch"
    admin = psycopg.connect(
        "postgresql://pfa:pfa@localhost:5433/postgres", autocommit=True
    )
    admin.execute(f"drop database if exists {name}")
    admin.execute(f"create database {name}")
    yield name
    admin.execute(f"drop database if exists {name} with (force)")
    admin.close()


async def test_a_database_without_migrations_says_to_run_them(blank_database):
    url = f"postgresql+asyncpg://pfa:pfa@localhost:5433/{blank_database}"
    check = await check_migrations(settings_with(database_url=url))
    assert not check.ok and "none applied" in check.detail
    assert "alembic upgrade head" in check.fix


async def test_an_out_of_date_database_names_both_versions(blank_database):
    with psycopg.connect(f"postgresql://pfa:pfa@localhost:5433/{blank_database}") as c:
        c.execute("create table alembic_version (version_num varchar(32) not null)")
        c.execute("insert into alembic_version values ('0001')")
    url = f"postgresql+asyncpg://pfa:pfa@localhost:5433/{blank_database}"
    check = await check_migrations(settings_with(database_url=url))
    assert not check.ok
    assert f"at 0001, latest is {migration_head()}" in check.detail


# --- Telegram ---


async def test_a_good_token_names_the_bot():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"ok": True, "result": {"username": "pfa_bot"}})

    async with client_for(handler) as client:
        check = await check_telegram_token(settings_with(), client)
    assert check.ok and check.detail == "bot @pfa_bot"
    assert seen == [f"https://api.telegram.org/bot{TOKEN}/getMe"]
    assert TOKEN not in check.detail


@pytest.mark.parametrize("status", [401, 404])
async def test_a_rejected_token_says_to_copy_it_again(status):
    async with client_for(reply(status, {"ok": False})) as client:
        check = await check_telegram_token(settings_with(), client)
    assert not check.ok and "BotFather" in check.fix
    assert TOKEN not in check.detail + check.fix


async def test_a_network_failure_never_leaks_the_token():
    def handler(request):
        raise httpx.ConnectError(f"cannot connect to {request.url}")  # has the token

    async with client_for(handler) as client:
        check = await check_telegram_token(settings_with(), client)
    assert not check.ok and "internet" in check.fix
    assert TOKEN not in check.detail + check.fix + check.name


async def test_a_chat_the_bot_can_see_is_found():
    async with client_for(reply(200, {"ok": True, "result": {"id": 4242}})) as client:
        check = await check_telegram_chat(settings_with(), client)
    assert check.ok and "4242" in check.detail


async def test_a_chat_the_bot_cannot_find_says_to_message_it_first():
    async with client_for(reply(400, {"ok": False})) as client:
        check = await check_telegram_chat(settings_with(), client)
    assert not check.ok
    assert "send it a message" in check.fix and "pfa chat-id" in check.fix


# --- finding the chat id ---


def update(chat: dict, *, edited=False) -> dict:
    return {"edited_message" if edited else "message": {"chat": chat}}


async def test_chats_are_listed_newest_first_without_repeats():
    updates = [
        update({"id": 1, "type": "private", "first_name": "Old", "last_name": "Chat"}),
        update({"id": 2, "type": "group", "title": "Family"}),
        update({"id": 1, "type": "private", "first_name": "Old", "last_name": "Chat"}),
        update({"id": 3, "type": "private", "username": "ada"}, edited=True),
        {"callback_query": {}},  # not a message: ignored
    ]
    async with client_for(reply(200, {"ok": True, "result": updates})) as client:
        chats = await discover_chats(TOKEN, client)
    assert [(c.id, c.kind, c.name) for c in chats] == [
        (3, "private", "ada"),
        (1, "private", "Old Chat"),
        (2, "group", "Family"),
    ]


async def test_no_messages_means_no_chats():
    async with client_for(reply(200, {"ok": True, "result": []})) as client:
        assert await discover_chats(TOKEN, client) == []


async def test_a_chat_with_no_name_still_has_one():
    updates = [update({"id": 9, "type": "private"})]
    async with client_for(reply(200, {"ok": True, "result": updates})) as client:
        (chat,) = await discover_chats(TOKEN, client)
    assert chat.name == "unnamed"


async def test_a_running_app_is_explained():
    async with client_for(reply(409, {"ok": False})) as client:
        with pytest.raises(ChatDiscoveryError, match="Stop it"):
            await discover_chats(TOKEN, client)


async def test_a_rejected_token_when_finding_chats():
    async with client_for(reply(401, {"ok": False})) as client:
        with pytest.raises(ChatDiscoveryError, match="BotFather"):
            await discover_chats(TOKEN, client)


async def test_no_internet_when_finding_chats_does_not_leak_the_token():
    def handler(request):
        raise httpx.ConnectError(str(request.url))

    async with client_for(handler) as client:
        with pytest.raises(ChatDiscoveryError) as caught:
            await discover_chats(TOKEN, client)
    assert TOKEN not in str(caught.value)


def test_the_chat_list_says_which_id_to_copy():
    from pfa.services.diagnostics import ChatInfo

    one = format_chats([ChatInfo(77, "private", "Ada")])
    assert "TELEGRAM_CHAT_ID=77" in one
    many = format_chats([ChatInfo(1, "private", "A"), ChatInfo(2, "private", "B")])
    assert "TELEGRAM_CHAT_ID=" not in many and "your own private chat" in many
    assert "press Start" in format_chats([])


# --- Gemini ---


async def test_a_good_key_is_accepted_and_sent_as_a_header_not_in_the_url():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"models": []})

    async with client_for(handler) as client:
        check = await check_gemini_key(settings_with(), client)
    assert check.ok
    assert seen[0].headers["x-goog-api-key"] == KEY
    assert KEY not in str(seen[0].url)


async def test_a_rate_limited_key_still_counts_as_working():
    async with client_for(reply(429)) as client:
        check = await check_gemini_key(settings_with(), client)
    assert check.ok and "rate limited" in check.detail


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_a_rejected_key_says_where_to_get_one(status):
    async with client_for(reply(status)) as client:
        check = await check_gemini_key(settings_with(), client)
    assert not check.ok and "aistudio.google.com" in check.fix
    assert KEY not in check.detail + check.fix


async def test_no_internet_for_gemini():
    def handler(request):
        raise httpx.ConnectError("down")

    async with client_for(handler) as client:
        check = await check_gemini_key(settings_with(), client)
    assert not check.ok and "internet" in check.fix


async def test_both_models_are_checked_by_name():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={})

    async with client_for(handler) as client:
        check = await check_gemini_models(settings_with(), client)
    assert check.ok
    assert seen == [
        "/v1beta/models/gemini-flash-lite-latest",
        "/v1beta/models/gemini-pro-latest",
    ]


async def test_a_model_the_key_cannot_use_names_the_setting():
    def handler(request):
        status = 404 if "pro" in request.url.path else 200
        return httpx.Response(status, json={})

    async with client_for(handler) as client:
        check = await check_gemini_models(settings_with(), client)
    assert not check.ok
    assert "GEMINI_EXTRACT_MODEL=gemini-pro-latest" in check.detail
    assert "GEMINI_CHAT_MODEL" not in check.detail


# --- everything together ---


def everything_ok(request):
    if "telegram" in request.url.host:
        body = {"ok": True, "result": {"username": "pfa_bot", "id": 4242}}
        return httpx.Response(200, json=body)
    return httpx.Response(200, json={"models": []})


async def test_a_good_setup_passes_every_check(good_settings):
    async with client_for(everything_ok) as client:
        checks = await run_doctor(client=client)
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert [c.name for c in checks] == [
        "Categories file",
        "Database",
        "Migrations",
        "Telegram token",
        "Telegram chat",
        "Gemini key",
        "Gemini models",
    ]


async def test_offline_mode_makes_no_requests(good_settings):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    async with client_for(handler) as client:
        checks = await run_doctor(network=False, client=client)
    assert calls == []
    assert [c.name for c in checks] == ["Categories file", "Database", "Migrations"]


async def test_placeholder_credentials_are_not_sent_anywhere(
    set_env, test_database_url
):
    set_env(
        DATABASE_URL=test_database_url,
        TELEGRAM_BOT_TOKEN="replace-me",
        GEMINI_API_KEY="replace-me",
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    async with client_for(handler) as client:
        checks = await run_doctor(client=client)
    assert calls == []  # nothing is sent to Telegram or Google with a placeholder
    assert {c.name for c in checks if not c.ok} == {"Telegram token", "Gemini API key"}


async def test_the_chat_check_waits_for_a_real_chat_id(set_env, test_database_url):
    set_env(DATABASE_URL=test_database_url, TELEGRAM_CHAT_ID="0")
    async with client_for(everything_ok) as client:
        checks = await run_doctor(client=client)
    names = [c.name for c in checks]
    assert "Telegram chat id" in names and "Telegram chat" not in names


async def test_without_a_database_the_migration_check_is_skipped(set_env):
    set_env(DATABASE_URL="postgresql+asyncpg://pfa:pfa@localhost:1/none")
    async with client_for(everything_ok) as client:
        checks = await run_doctor(client=client)
    names = [c.name for c in checks]
    assert "Database" in names and "Migrations" not in names


async def test_missing_settings_stop_everything_else(set_env, monkeypatch):
    set_env()
    monkeypatch.delenv("GEMINI_API_KEY")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    async with client_for(handler) as client:
        checks = await run_doctor(client=client)
    assert [c.name for c in checks] == ["Setting GEMINI_API_KEY"]
    assert calls == []


async def test_no_secret_appears_in_the_report_however_it_fails(good_settings):
    def handler(request):
        raise httpx.ConnectError(f"boom {request.url} {request.headers}")

    async with client_for(handler) as client:
        checks = await run_doctor(client=client)
    shown = format_report(checks)
    for secret in (TOKEN, KEY, PASSWORD, GOOD_ENV["AUTH_SECRET"]):
        assert secret not in shown
    assert "✗" in shown


def test_the_report_says_what_to_do_next():
    from pfa.services.diagnostics import Check

    good = format_report([Check("A", True, "fine")])
    assert "Everything looks good" in good and "uvicorn pfa.main:app" in good
    bad = format_report(
        [Check("A", False, "broken", "do this"), Check("B", True, "ok")]
    )
    assert "✗ A: broken\n    → do this" in bad
    assert "1 thing to fix" in bad
    assert "2 things to fix" in format_report(
        [Check("A", False, "x"), Check("B", False, "y")]
    )


def test_the_real_environment_is_untouched_by_these_tests():
    assert os.environ.get("TELEGRAM_BOT_TOKEN") != TOKEN
