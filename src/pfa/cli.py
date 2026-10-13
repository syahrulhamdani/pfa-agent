"""Command line helpers for setting pfa up.

Commands: `pfa doctor`, `pfa chat-id` and `pfa seed-demo`.

Run them with the same env file as the app, for example:

    uv run --env-file .env pfa doctor
"""

import asyncio
from collections.abc import Callable, Sequence

import httpx
import typer

from pfa.core.database import create_engine, create_session_factory
from pfa.services.analytics import today_in
from pfa.services.categories import load_category_names
from pfa.services.demo import DemoError, seed_demo
from pfa.services.diagnostics import (
    PLACEHOLDER,
    ChatDiscoveryError,
    ChatInfo,
    Check,
    check_database,
    describe_database,
    discover_chats,
    load_settings,
    run_doctor,
)

app = typer.Typer(
    help="Set up and check your pfa installation.",
    no_args_is_help=True,
    add_completion=False,
)

START_HINT = "uv run --env-file .env uvicorn pfa.main:app"


def format_report(checks: Sequence[Check]) -> str:
    """Writes the checks as a readable list, with what to do about each failure."""
    lines = []
    for check in checks:
        mark = "✓" if check.ok else "✗"
        lines.append(f"{mark} {check.name}: {check.detail}")
        if not check.ok and check.fix:
            lines.append(f"    → {check.fix}")
    failed = sum(1 for c in checks if not c.ok)
    lines.append("")
    if failed:
        lines.append(
            f"{failed} thing{'s' if failed != 1 else ''} to fix, then run this again."
        )
    else:
        lines.append(f"Everything looks good. Start pfa with: {START_HINT}")
    return "\n".join(lines)


def format_chats(chats: Sequence[ChatInfo]) -> str:
    """Lists chats that messaged the bot, and says which id to copy."""
    if not chats:
        return (
            "No messages found yet. Open your bot in Telegram, press Start (or send "
            "any message), then run this again."
        )
    lines = ["Chats that have messaged your bot (newest first):"]
    lines += [f"  {chat.id}   {chat.kind}   {chat.name}" for chat in chats]
    private = [c for c in chats if c.kind == "private"]
    if len(private) == 1:
        lines += ["", f"Put this in your .env file:  TELEGRAM_CHAT_ID={private[0].id}"]
    else:
        lines += [
            "",
            "Put the id of your own private chat in .env as TELEGRAM_CHAT_ID.",
        ]
    return "\n".join(lines)


async def run_chat_id() -> tuple[str, int]:
    """Finds the chats that messaged the bot; returns the text and an exit code."""
    settings, problems = load_settings()
    if settings is None:
        return format_report(problems), 1
    if PLACEHOLDER in settings.telegram_bot_token:
        return (
            "TELEGRAM_BOT_TOKEN is still the placeholder. Create a bot with "
            "@BotFather, paste its token into .env, then run this again.",
            1,
        )
    async with httpx.AsyncClient() as client:
        try:
            chats = await discover_chats(settings.telegram_bot_token, client)
        except ChatDiscoveryError as exc:
            return str(exc), 1
    return format_chats(chats), 0 if chats else 1


async def run_seed_demo(confirm: Callable[[str], bool]) -> tuple[str, int]:
    """Adds the sample data after `confirm` agrees. Returns the text and exit code."""
    settings, problems = load_settings()
    if settings is None:
        return format_report(problems), 1
    database = await check_database(settings)
    if not database.ok:
        return format_report([database]), 1
    where = describe_database(settings.database_url)
    if not confirm(
        "This adds fictional sample data (a demo bank, transactions, budgets, goals "
        f"and a summary) to {where}. Continue?"
    ):
        return "Nothing was changed.", 1
    engine = create_engine(settings)
    try:
        seeded = await seed_demo(
            create_session_factory(engine),
            load_category_names(settings.categories_file),
            today_in(settings.timezone),
            settings.timezone,
        )
    except DemoError as exc:
        return exc.args[0], 1
    finally:
        await engine.dispose()
    week = seeded.summary_week
    return (
        f"Added {seeded.transactions} transactions, {seeded.budgets} budgets, "
        f"{seeded.goals} goals and the summary for the week of {week:%b} {week.day}.\n"
        "Start pfa, send /login to your bot, and open the link to see it.",
        0,
    )


@app.command()
def doctor(
    offline: bool = typer.Option(
        False, "--offline", help="Skip the checks that need the internet."
    ),
) -> None:
    """Check the settings, database, Telegram and Gemini, and say how to fix them."""
    checks = asyncio.run(run_doctor(network=not offline))
    typer.echo(format_report(checks))
    raise typer.Exit(code=0 if all(c.ok for c in checks) else 1)


@app.command("chat-id")
def chat_id() -> None:
    """Find your Telegram chat id: message your bot first, then run this."""
    text, code = asyncio.run(run_chat_id())
    typer.echo(text)
    raise typer.Exit(code=code)


@app.command("seed-demo")
def seed_demo_command(
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Fill an empty database with fictional sample data, to see the app in full."""
    text, code = asyncio.run(
        run_seed_demo(lambda question: yes or typer.confirm(question, default=False))
    )
    typer.echo(text)
    raise typer.Exit(code=code)


def main() -> None:
    """Runs the command line (used by `python -m pfa.cli`)."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
