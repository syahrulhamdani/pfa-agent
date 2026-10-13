"""Setup checks for people running pfa for the first time.

Each check answers one question ("can I reach the database?", "is this a real Telegram
token?") and, when the answer is no, says what to do about it. Nothing here ever
prints a secret: a failing request must not echo the URL it was sent to, because a
Telegram token is part of its URL.
"""

import asyncio
import zoneinfo
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from pfa.core.config import Settings
from pfa.core.exceptions import PfaError
from pfa.services.categories import load_category_names

TELEGRAM_API = "https://api.telegram.org"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
PLACEHOLDER = "replace-me"
REQUEST_TIMEOUT = 15.0
DB_TIMEOUT = 5.0
REPO_ROOT = Path(__file__).resolve().parents[3]

SECRET_HINT = (
    'python -c "import secrets; print(secrets.token_urlsafe(48))" and paste the '
    "result as AUTH_SECRET"
)


@dataclass(frozen=True)
class Check:
    """The result of one check."""

    name: str
    ok: bool
    detail: str
    fix: str = ""


def _ok(name: str, detail: str) -> Check:
    return Check(name, True, detail)


def _fail(name: str, detail: str, fix: str) -> Check:
    return Check(name, False, detail, fix)


# --- settings ---


def load_settings() -> tuple[Settings | None, list[Check]]:
    """Reads the settings, turning a validation failure into readable checks.

    Returns:
        The settings (None if they could not be read) and one failed check per
        missing or invalid value.
    """
    try:
        return Settings(), []  # type: ignore[call-arg]
    except ValidationError as exc:
        checks = []
        for error in exc.errors():
            field = str(error["loc"][0]).upper() if error["loc"] else "settings"
            missing = error["type"] == "missing"
            checks.append(
                _fail(
                    f"Setting {field}",
                    "is missing" if missing else error["msg"],
                    f"Set {field} in your .env file (copy .env.example to .env first)",
                )
            )
        return None, checks


def check_settings(settings: Settings) -> list[Check]:
    """Checks that the values are real, not the placeholders from .env.example."""
    checks = []
    if PLACEHOLDER in settings.telegram_bot_token:
        checks.append(
            _fail(
                "Telegram token",
                "is still the placeholder",
                "Create a bot with @BotFather in Telegram and paste its token as "
                "TELEGRAM_BOT_TOKEN",
            )
        )
    if settings.telegram_chat_id == 0:
        checks.append(
            _fail(
                "Telegram chat id",
                "is still 0",
                "Message your bot once, then run `uv run pfa chat-id` and paste the "
                "id as TELEGRAM_CHAT_ID",
            )
        )
    if PLACEHOLDER in settings.gemini_api_key:
        checks.append(
            _fail(
                "Gemini API key",
                "is still the placeholder",
                "Create a key at https://aistudio.google.com/apikey and paste it as "
                "GEMINI_API_KEY",
            )
        )
    if PLACEHOLDER in settings.auth_secret:
        checks.append(
            _fail("Sign-in secret", "is still the placeholder", f"Run {SECRET_HINT}")
        )
    try:
        zoneinfo.ZoneInfo(settings.timezone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        checks.append(
            _fail(
                "Timezone",
                f"“{settings.timezone}” is not a known timezone",
                "Use an IANA name such as Asia/Jakarta or Europe/London in TIMEZONE",
            )
        )
    try:
        count = len(load_category_names(settings.categories_file))
    except PfaError as exc:
        checks.append(
            _fail(
                "Categories file",
                str(exc),
                "Check CATEGORIES_FILE, or run from the project folder",
            )
        )
    else:
        checks.append(_ok("Categories file", f"{count} categories"))
    return checks


def incomplete_setup_message(settings: Settings) -> str | None:
    """Describes what is still unset, or returns None if the settings are real.

    The app uses this to stop at once with a clear message, instead of a stack trace
    from Telegram rejecting a placeholder token.
    """
    problems = [c for c in check_settings(settings) if not c.ok]
    if not problems:
        return None
    lines = ["pfa is not set up yet:"]
    lines += [f"  - {c.name} {c.detail}. {c.fix}" for c in problems]
    lines.append("Run `uv run --env-file .env pfa doctor` to check everything.")
    return "\n".join(lines)


# --- the database ---


def describe_database(url: str) -> str:
    """Names the database without its password."""
    parsed = make_url(url)
    return f"{parsed.host or 'localhost'}:{parsed.port or 5432}/{parsed.database}"


async def check_database(settings: Settings) -> Check:
    """Checks that Postgres answers."""
    where = describe_database(settings.database_url)
    engine = create_async_engine(settings.database_url)
    try:
        async with asyncio.timeout(DB_TIMEOUT):
            async with engine.connect() as connection:
                await connection.execute(text("select 1"))
    except Exception:
        return _fail(
            "Database",
            f"cannot connect to {where}",
            "Start it with `docker compose up -d db` and wait a few seconds; check "
            "DATABASE_URL if you use your own Postgres",
        )
    finally:
        await engine.dispose()
    return _ok("Database", f"connected to {where}")


def migration_head() -> str | None:
    """Returns the newest migration's id, or None if the scripts cannot be found."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    scripts = REPO_ROOT / "src" / "pfa" / "migrations"
    if not scripts.is_dir():
        return None
    config = Config()
    config.set_main_option("script_location", str(scripts))
    return ScriptDirectory.from_config(config).get_current_head()


async def check_migrations(settings: Settings) -> Check:
    """Checks that the database has every migration applied."""
    head = migration_head()
    if head is None:
        return _ok("Migrations", "skipped (migration scripts not found)")
    engine = create_async_engine(settings.database_url)
    try:
        async with asyncio.timeout(DB_TIMEOUT):
            async with engine.connect() as connection:
                row = (
                    await connection.execute(
                        text("select version_num from alembic_version")
                    )
                ).first()
    except Exception:
        row = None
    finally:
        await engine.dispose()
    fix = "Run `uv run --env-file .env alembic upgrade head`"
    if row is None:
        return _fail("Migrations", "none applied yet", fix)
    if row[0] != head:
        return _fail("Migrations", f"at {row[0]}, latest is {head}", fix)
    return _ok("Migrations", f"up to date ({head})")


# --- Telegram ---


def _telegram_url(token: str, method: str) -> str:
    return f"{TELEGRAM_API}/bot{token}/{method}"


async def _telegram(
    client: httpx.AsyncClient, token: str, method: str, **params: str | int
) -> tuple[int, dict] | None:
    """Calls the Telegram API; returns (status, body), or None if unreachable."""
    try:
        response = await client.get(
            _telegram_url(token, method), params=params, timeout=REQUEST_TIMEOUT
        )
    except httpx.HTTPError:
        return None  # never show the error: its text contains the token's URL
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


async def check_telegram_token(settings: Settings, client: httpx.AsyncClient) -> Check:
    """Checks that Telegram accepts the bot token, and names the bot."""
    reply = await _telegram(client, settings.telegram_bot_token, "getMe")
    if reply is None:
        return _fail(
            "Telegram",
            "could not reach api.telegram.org",
            "Check your internet connection or proxy",
        )
    status, body = reply
    if status == 200 and body.get("ok"):
        username = body.get("result", {}).get("username", "your bot")
        return _ok("Telegram token", f"bot @{username}")
    return _fail(
        "Telegram token",
        "Telegram rejected the token",
        "Copy the token again from @BotFather (send it /token), with no spaces",
    )


async def check_telegram_chat(settings: Settings, client: httpx.AsyncClient) -> Check:
    """Checks that the bot can see the configured chat."""
    reply = await _telegram(
        client,
        settings.telegram_bot_token,
        "getChat",
        chat_id=settings.telegram_chat_id,
    )
    if reply is None:
        return _fail("Telegram chat", "could not reach api.telegram.org", "Retry")
    status, body = reply
    if status == 200 and body.get("ok"):
        return _ok("Telegram chat", f"chat {settings.telegram_chat_id} found")
    return _fail(
        "Telegram chat",
        f"the bot cannot find chat {settings.telegram_chat_id}",
        "Open your bot in Telegram and send it a message (Start), then run "
        "`uv run pfa chat-id` and copy the id it shows",
    )


@dataclass(frozen=True)
class ChatInfo:
    """A chat that has messaged the bot."""

    id: int
    kind: str
    name: str


class ChatDiscoveryError(PfaError):
    """The chats could not be listed; the message says what to do."""


async def discover_chats(token: str, client: httpx.AsyncClient) -> list[ChatInfo]:
    """Lists the chats that have recently messaged the bot, newest first.

    Raises:
        ChatDiscoveryError: If Telegram is unreachable, rejects the token, or is
            already being polled by a running pfa.
    """
    reply = await _telegram(client, token, "getUpdates", limit=100, timeout=0)
    if reply is None:
        raise ChatDiscoveryError(
            "Could not reach api.telegram.org. Check your internet."
        )
    status, body = reply
    if status == 409:
        raise ChatDiscoveryError(
            "pfa (or another program) is already receiving this bot's messages. "
            "Stop it, run this again, then start pfa."
        )
    if status != 200 or not body.get("ok"):
        raise ChatDiscoveryError(
            "Telegram rejected the bot token. Copy it again from @BotFather."
        )
    seen: dict[int, ChatInfo] = {}
    for update in reversed(body.get("result", [])):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if "id" not in chat or chat["id"] in seen:
            continue
        name = (
            chat.get("title")
            or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            or chat.get("username")
            or "unnamed"
        )
        seen[chat["id"]] = ChatInfo(chat["id"], chat.get("type", "chat"), name)
    return list(seen.values())


# --- Gemini ---


async def _gemini(
    client: httpx.AsyncClient, key: str, path: str
) -> tuple[int, dict] | None:
    try:
        response = await client.get(
            f"{GEMINI_API}/{path}",
            headers={"x-goog-api-key": key},  # a header, so it is never in a URL
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.HTTPError:
        return None
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


async def check_gemini_key(settings: Settings, client: httpx.AsyncClient) -> Check:
    """Checks that Google accepts the API key."""
    reply = await _gemini(client, settings.gemini_api_key, "models?pageSize=1")
    if reply is None:
        return _fail(
            "Gemini",
            "could not reach generativelanguage.googleapis.com",
            "Check your internet connection or proxy",
        )
    status, _ = reply
    if status == 200:
        return _ok("Gemini key", "accepted")
    if status == 429:
        return _ok("Gemini key", "accepted, but currently rate limited")
    return _fail(
        "Gemini key",
        "Google rejected the key",
        "Create a new key at https://aistudio.google.com/apikey and paste it as "
        "GEMINI_API_KEY",
    )


async def check_gemini_models(settings: Settings, client: httpx.AsyncClient) -> Check:
    """Checks that both configured model names exist for this key."""
    missing = []
    for label, name in (
        ("GEMINI_CHAT_MODEL", settings.gemini_chat_model),
        ("GEMINI_EXTRACT_MODEL", settings.gemini_extract_model),
    ):
        reply = await _gemini(client, settings.gemini_api_key, f"models/{name}")
        if reply is None:
            return _fail("Gemini models", "could not reach Google", "Retry")
        if reply[0] != 200:
            missing.append(f"{label}={name}")
    if missing:
        return _fail(
            "Gemini models",
            "not available: " + ", ".join(missing),
            "Pick names your key can use (see https://ai.google.dev/gemini-api/docs/"
            "models) and set them in .env",
        )
    return _ok(
        "Gemini models",
        f"{settings.gemini_chat_model} and {settings.gemini_extract_model} available",
    )


# --- everything together ---

AsyncCheck = Callable[[Settings, httpx.AsyncClient], Awaitable[Check]]


async def run_doctor(
    *, network: bool = True, client: httpx.AsyncClient | None = None
) -> list[Check]:
    """Runs every check in order and returns the results.

    Args:
        network: Whether to check Telegram and Gemini (they need the internet).
        client: The HTTP client to use; one is created if omitted.
    """
    settings, problems = load_settings()
    if settings is None:
        return problems
    checks = check_settings(settings)
    checks.append(await check_database(settings))
    if checks[-1].ok:
        checks.append(await check_migrations(settings))
    if not network:
        return checks
    own = client is None
    http = client or httpx.AsyncClient()
    try:
        # Real credentials only: a placeholder would just be rejected, noisily.
        if PLACEHOLDER not in settings.telegram_bot_token:
            checks.append(await check_telegram_token(settings, http))
            if checks[-1].ok and settings.telegram_chat_id != 0:
                checks.append(await check_telegram_chat(settings, http))
        if PLACEHOLDER not in settings.gemini_api_key:
            checks.append(await check_gemini_key(settings, http))
            if checks[-1].ok:
                checks.append(await check_gemini_models(settings, http))
    finally:
        if own:
            await http.aclose()
    return checks
