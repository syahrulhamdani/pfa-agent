"""Boundary: the `pfa` command line sets a newcomer up and fails with clear words.

What is tested: the three commands through Typer's runner, exit codes (0 only on
success), the confirmation prompt, refusing to touch a database that already has data,
and that the database is named without its password. These tests are synchronous
because the commands run their own event loop.
"""

from importlib.metadata import entry_points
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from pfa.cli import app
from pfa.services.diagnostics import ChatDiscoveryError, ChatInfo

ROOT = Path(__file__).resolve().parent.parent
TEST_DSN = "postgresql://pfa:pfa@localhost:5433/pfa_test"
TABLES = (
    "transactions, uploads, cards, banks, categories, login_tokens, auth_state, "
    "nudge_slots, budget_versions, goals, weekly_summaries"
)
ENV = {
    "TELEGRAM_BOT_TOKEN": "123456:REAL-LOOKING-TOKEN",
    "TELEGRAM_CHAT_ID": "4242",
    "GEMINI_API_KEY": "real-looking-key",
    "AUTH_SECRET": "real-secret-" + "x" * 40,
    "TIMEZONE": "Asia/Jakarta",
    "CATEGORIES_FILE": str(ROOT / "config" / "categories.json"),
}
runner = CliRunner()


@pytest.fixture
def env(monkeypatch, test_database_url):
    """A good environment pointing at an emptied test database."""
    for name in (
        "DATABASE_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "GEMINI_API_KEY",
        "AUTH_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in {**ENV, "DATABASE_URL": test_database_url}.items():
        monkeypatch.setenv(name, value)
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        conn.execute(f"truncate {TABLES} restart identity cascade")
    return monkeypatch


def rows(table: str) -> int:
    with psycopg.connect(TEST_DSN) as conn:
        return conn.execute(f"select count(*) from {table}").fetchone()[0]


def test_the_command_is_installed_under_the_name_pfa():
    (script,) = entry_points(group="console_scripts", name="pfa")
    assert script.value == "pfa.cli:app"


def test_help_lists_every_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("doctor", "chat-id", "seed-demo"):
        assert command in result.output


def test_running_it_with_nothing_shows_the_commands():
    result = runner.invoke(app, [])
    assert "Commands" in result.output


# --- doctor ---


def test_doctor_passes_a_good_setup_offline(env):
    result = runner.invoke(app, ["doctor", "--offline"])
    assert result.exit_code == 0, result.output
    assert "Everything looks good" in result.output
    assert "✓ Database" in result.output and "✓ Migrations" in result.output


def test_doctor_fails_with_a_fix_for_a_missing_setting(env):
    env.delenv("TELEGRAM_BOT_TOKEN")
    result = runner.invoke(app, ["doctor", "--offline"])
    assert result.exit_code == 1
    assert "TELEGRAM_BOT_TOKEN: is missing" in result.output
    assert "copy .env.example to .env" in result.output


def test_doctor_names_the_command_that_starts_the_database(env):
    env.setenv("DATABASE_URL", "postgresql+asyncpg://pfa:pfa@localhost:1/none")
    result = runner.invoke(app, ["doctor", "--offline"])
    assert result.exit_code == 1
    assert "docker compose up -d db" in result.output


def test_doctor_never_prints_a_secret(env):
    env.setenv("DATABASE_URL", "postgresql+asyncpg://pfa:topsecretpw@localhost:1/none")
    result = runner.invoke(app, ["doctor", "--offline"])
    for secret in ("topsecretpw", ENV["TELEGRAM_BOT_TOKEN"], ENV["GEMINI_API_KEY"]):
        assert secret not in result.output


# --- chat-id ---


def fake_discovery(monkeypatch, result):
    async def discover(token, client):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("pfa.cli.discover_chats", discover)


def test_chat_id_shows_the_id_to_copy(env):
    fake_discovery(env, [ChatInfo(777, "private", "Ada")])
    result = runner.invoke(app, ["chat-id"])
    assert result.exit_code == 0
    assert "TELEGRAM_CHAT_ID=777" in result.output


def test_chat_id_with_several_chats_asks_which_is_yours(env):
    fake_discovery(env, [ChatInfo(1, "group", "Family"), ChatInfo(2, "private", "Ada")])
    result = runner.invoke(app, ["chat-id"])
    assert result.exit_code == 0
    assert "TELEGRAM_CHAT_ID=2" in result.output  # only one private chat


def test_chat_id_with_no_messages_says_to_message_the_bot(env):
    fake_discovery(env, [])
    result = runner.invoke(app, ["chat-id"])
    assert result.exit_code == 1 and "press Start" in result.output


def test_chat_id_explains_a_running_app(env):
    fake_discovery(env, ChatDiscoveryError("Stop it, run this again, then start pfa."))
    result = runner.invoke(app, ["chat-id"])
    assert result.exit_code == 1 and "Stop it" in result.output


def test_chat_id_refuses_a_placeholder_token(env):
    env.setenv("TELEGRAM_BOT_TOKEN", "replace-me")
    result = runner.invoke(app, ["chat-id"])
    assert result.exit_code == 1 and "BotFather" in result.output


def test_chat_id_needs_settings_to_exist(env):
    env.delenv("GEMINI_API_KEY")
    result = runner.invoke(app, ["chat-id"])
    assert result.exit_code == 1 and "GEMINI_API_KEY" in result.output


# --- seed-demo ---


def test_seed_demo_fills_an_empty_database(env):
    result = runner.invoke(app, ["seed-demo", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Added" in result.output and "/login" in result.output
    assert rows("transactions") > 30 and rows("goals") == 3
    assert rows("weekly_summaries") == 1


def test_seed_demo_refuses_to_run_twice(env):
    assert runner.invoke(app, ["seed-demo", "-y"]).exit_code == 0
    before = rows("transactions")
    result = runner.invoke(app, ["seed-demo", "-y"])
    assert result.exit_code == 1
    assert "already has transactions or goals" in result.output
    assert "docker compose down -v" in result.output
    assert rows("transactions") == before


def test_seed_demo_asks_first_and_names_the_database_without_its_password(env):
    result = runner.invoke(app, ["seed-demo"], input="n\n")
    assert result.exit_code == 1
    assert "Nothing was changed" in result.output
    assert "localhost:5433/pfa_test" in result.output
    assert "postgresql" not in result.output
    assert rows("transactions") == 0


def test_seed_demo_goes_ahead_on_a_yes(env):
    result = runner.invoke(app, ["seed-demo"], input="y\n")
    assert result.exit_code == 0 and rows("transactions") > 30


def test_seed_demo_stops_if_the_database_is_unreachable(env):
    env.setenv("DATABASE_URL", "postgresql+asyncpg://pfa:pfa@localhost:1/none")
    result = runner.invoke(app, ["seed-demo", "-y"])
    assert result.exit_code == 1 and "docker compose up -d db" in result.output


def test_seed_demo_needs_settings_to_exist(env):
    env.delenv("AUTH_SECRET")
    result = runner.invoke(app, ["seed-demo", "-y"])
    assert result.exit_code == 1 and "AUTH_SECRET" in result.output
