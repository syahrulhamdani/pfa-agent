"""Shared fixtures."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pfa.core.config import Settings, get_settings
from pfa.main import app
from pfa.schemas.auth import TokenType
from pfa.services.auth import SESSION_COOKIE, create_token
from pfa.services.categories import seed_categories

TEST_AUTH_SECRET = "test-secret-" + "x" * 40


@pytest.fixture
def settings() -> Settings:
    """Settings with dummy secrets, never read from the real environment."""
    return Settings(
        telegram_bot_token="123:abc",
        telegram_chat_id=42,
        gemini_api_key="fake-key",
        auth_secret=TEST_AUTH_SECRET,
    )


@pytest.fixture
def fake_model_factory():
    """Builds a fake chat model that replays the given reply texts in order."""

    def _build(*replies: str) -> GenericFakeChatModel:
        return GenericFakeChatModel(
            messages=iter(AIMessage(content=r) for r in replies)
        )

    return _build


# --- Database fixtures: a separate `pfa_test` database on the compose Postgres. ---

ROOT = Path(__file__).resolve().parent.parent
ADMIN_CONN = "postgresql://pfa:pfa@localhost:5433/postgres"
TEST_DB = "pfa_test"
TEST_DB_URL = f"postgresql+asyncpg://pfa:pfa@localhost:5433/{TEST_DB}"
TEST_CATEGORIES = [
    "Groceries",
    "Dining",
    "Transport",
    "Other",
    "Salary",
    "Refund",
    "Transfer",
    "Interest",
]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Creates and migrates the test database; skips if Postgres is not running."""
    try:
        admin = psycopg.connect(ADMIN_CONN, autocommit=True, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running (docker compose up -d db)")
    with admin:
        exists = admin.execute(
            "select 1 from pg_database where datname = %s", (TEST_DB,)
        ).fetchone()
        if not exists:
            admin.execute(f"create database {TEST_DB}")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": TEST_DB_URL},
        check=True,
        capture_output=True,
    )
    return TEST_DB_URL


@pytest.fixture
async def session_factory(test_database_url):
    """A session factory over an emptied test database with categories seeded."""
    engine = create_async_engine(test_database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE transactions, uploads, cards, banks, categories, "
                "login_tokens, auth_state, nudge_slots "
                "RESTART IDENTITY CASCADE"
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await seed_categories(factory, TEST_CATEGORIES)
    yield factory
    await engine.dispose()


# --- API clients: anonymous, and signed in with a valid session cookie. ---


@pytest.fixture
def api_settings() -> Settings:
    """Settings for API tests: UTC timezone and the test signing secret."""
    return Settings(
        telegram_bot_token="t",
        telegram_chat_id=1,
        gemini_api_key="k",
        auth_secret=TEST_AUTH_SECRET,
        timezone="UTC",
    )


@pytest.fixture
async def anon_client(session_factory, api_settings):
    """An API client with no session cookie."""
    app.state.session_factory = session_factory
    app.dependency_overrides[get_settings] = lambda: api_settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def authed_client(anon_client, api_settings):
    """An API client signed in with a valid session cookie."""
    token, _, _ = create_token(
        api_settings.auth_secret, TokenType.SESSION, timedelta(days=1)
    )
    anon_client.cookies.set(SESSION_COOKIE, token)
    return anon_client
