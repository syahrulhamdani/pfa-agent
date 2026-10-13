"""Boundary: the weekly summary as a Telegram message, and how it is sent.

What is tested: the message holds the stored figures and advice and a sign-in link,
leaves out sections with nothing to say, stays within Telegram's limit; the Monday job
sends a week once and never raises; the demo always sends and reports a failure; and
`/demo_summary` is wired to the owner's chat only.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import CommandHandler

from pfa.bot import handlers
from pfa.bot.app import build_application
from pfa.bot.summaries import (
    SUMMARY_FAILED_TEXT,
    build_summary_senders,
    summary_text,
)
from pfa.graphs.recommendations import build_summary_graph
from pfa.models import Goal, Transaction
from pfa.repository.finance import CategoryRepository
from pfa.schemas.analytics import MoneyTotal, Period
from pfa.schemas.insights import (
    BudgetLine,
    CategoryLine,
    GoalLine,
    InsightFacts,
    WeeklySummaryRead,
)
from pfa.services.budgets import set_budget
from pfa.services.summaries import SummaryService

MONDAY = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)
LINK = "http://web/auth?token=T&next=/dashboard"


class Writer:
    def __init__(self, reply="Keep Groceries in check.\nSet aside 500 a week."):
        self.reply = reply

    async def __call__(self, instruction, facts_text, question):
        return self.reply


def facts(**overrides) -> InsightFacts:
    base = dict(
        label="Week of Oct 5 – Oct 11, 2026",
        period=Period.WEEK,
        start=date(2026, 10, 5),
        end=date(2026, 10, 11),
        money_out=Decimal("1100"),
        money_in=Decimal("5000"),
        net=Decimal("3900"),
        out_count=2,
        in_count=1,
        money_out_change=None,
        money_in_change=None,
        transfers=MoneyTotal(total=Decimal("0"), count=0),
        top_out=[],
    )
    return InsightFacts(**{**base, **overrides})


def summary(f=None, lines=("Do this.",)) -> WeeklySummaryRead:
    f = f or facts()
    return WeeklySummaryRead(
        week_start=f.start,
        week_end=f.end,
        facts=f,
        recommendations=list(lines),
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )


# --- the message ---


def test_the_message_has_the_figures_the_advice_and_the_link():
    f = facts(
        money_out_change=1.75,
        transfers=MoneyTotal(total=Decimal("700"), count=2),
        top_out=[
            CategoryLine(category="Dining", total=Decimal("900"), count=1, share=0.82),
            CategoryLine(category="Other", total=Decimal("200"), count=1, share=0.18),
        ],
        flags=[
            BudgetLine(
                category="Groceries",
                amount=Decimal("100"),
                spent=Decimal("200"),
                remaining=Decimal("-100"),
                used=2.0,
                state="over",
            )
        ],
    )
    text = summary_text(summary(f, ("Watch Groceries.", "Save 500 a week.")), LINK, 10)
    for expected in (
        "Week of Oct 5 – Oct 11, 2026",
        "Money out: 1,100 (2 transactions)",
        "Money in: 5,000",
        "Net: +3,900",
        "Between your own accounts (not counted): 2 moves, 700",
        "Top spending: Dining 900 (82%), Other 200 (18%)",
        "Budgets to watch: Groceries over budget by 100",
        "What I'd do:\n- Watch Groceries.\n- Save 500 a week.",
        f"valid for 10 minutes, works once): {LINK}",
    ):
        assert expected in text, expected


def test_sections_with_nothing_to_say_are_left_out():
    text = summary_text(summary(lines=()), LINK, 10)
    for absent in (
        "Between your own",
        "Top spending",
        "Budgets to watch",
        "What I'd do",
    ):
        assert absent not in text
    assert text.endswith(LINK)


def test_a_single_transaction_and_a_single_move_are_singular():
    f = facts(out_count=1, transfers=MoneyTotal(total=Decimal("50"), count=1))
    text = summary_text(summary(f), LINK, 10)
    assert "(1 transaction)" in text and "1 move," in text


def test_a_negative_net_has_a_minus_and_zero_has_a_plus():
    assert "Net: -300" in summary_text(summary(facts(net=Decimal("-300"))), LINK, 10)
    assert "Net: +0" in summary_text(summary(facts(net=Decimal("0"))), LINK, 10)


def test_a_running_week_says_so():
    text = summary_text(summary(facts(partial=True)), LINK, 10)
    assert text.startswith("So far this week: Week of")


def test_a_long_summary_stays_inside_telegrams_limit():
    many_flags = [
        BudgetLine(
            category=f"Category {i}",
            amount=Decimal("100"),
            spent=Decimal("200"),
            remaining=Decimal("-100"),
            used=2.0,
            state="over",
        )
        for i in range(30)
    ]
    many_top = [
        CategoryLine(category=f"Cat {i}", total=Decimal("9"), count=1, share=0.1)
        for i in range(30)
    ]
    goals = [
        GoalLine(
            name="Goal",
            saved=Decimal("1"),
            target=Decimal("2"),
            progress=0.5,
            remaining=Decimal("1"),
            days_left=10,
            per_week_needed=Decimal("1"),
        )
        for _ in range(30)
    ]
    f = facts(flags=many_flags, top_out=many_top, goals=goals)
    text = summary_text(summary(f, ["x" * 320] * 5), LINK, 10)
    assert len(text) < 4096
    assert text.count("Category ") <= 3  # only the first few budgets are named


# --- sending ---


async def seed(session_factory):
    async with session_factory() as session:
        ids = {
            name: await CategoryRepository(session).get_id_by_name(name)
            for name in ("Dining", "Groceries")
        }
        session.add_all(
            Transaction(
                merchant=c,
                category_id=ids[c],
                amount=Decimal(a),
                occurred_on=date.fromisoformat(d),
                direction="out",
                status="confirmed",
            )
            for c, a, d in [
                ("Dining", "900", "2026-10-06"),
                ("Groceries", "200", "2026-10-07"),
            ]
        )
        session.add(
            Goal(
                name="Trip",
                target_amount=Decimal("1500"),
                target_date=date(2026, 10, 26),
                saved_amount=Decimal("500"),
            )
        )
        await session.commit()
        await set_budget(session, "Groceries", date(2026, 10, 1), Decimal("100"))


@pytest.fixture
def bot():
    return SimpleNamespace(send_message=AsyncMock())


def senders(session_factory, bot, *, writer=None, issue_link=None, service=None):
    if service is None:
        graph = build_summary_graph(session_factory, writer or Writer())
        service = SummaryService(session_factory, graph, "Asia/Jakarta")
    return build_summary_senders(
        bot=bot,
        chat_id=42,
        service=service,
        issue_link=issue_link or AsyncMock(return_value=LINK),
        ttl_minutes=10,
    )


class Pinned(SummaryService):
    """A service whose clock is fixed, so the week is known."""

    async def monday_summary(self, now=None):
        return await super().monday_summary(MONDAY)

    async def demo_summary(self, now=None):
        return await super().demo_summary(MONDAY)


def pinned(session_factory, writer=None):
    graph = build_summary_graph(session_factory, writer or Writer())
    return Pinned(session_factory, graph, "Asia/Jakarta")


async def test_the_monday_job_sends_the_week_once(session_factory, bot):
    await seed(session_factory)
    monday, _ = senders(session_factory, bot, service=pinned(session_factory))
    await monday()
    await monday()  # a repeat, or a restart: nothing more is sent
    bot.send_message.assert_awaited_once()
    sent = bot.send_message.await_args.kwargs
    assert sent["chat_id"] == 42
    assert "Money out: 1,100" in sent["text"] and LINK in sent["text"]
    assert sent["link_preview_options"].is_disabled


async def test_the_demo_sends_every_time(session_factory, bot):
    await seed(session_factory)
    _, demo = senders(session_factory, bot, service=pinned(session_factory))
    await demo()
    await demo()
    assert bot.send_message.await_count == 2


async def test_each_message_carries_its_own_fresh_link(session_factory, bot):
    await seed(session_factory)
    links = iter(["http://web/auth?token=ONE", "http://web/auth?token=TWO"])

    async def issue():
        return next(links)

    _, demo = senders(
        session_factory, bot, service=pinned(session_factory), issue_link=issue
    )
    await demo()
    await demo()
    texts = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert "token=ONE" in texts[0] and "token=TWO" in texts[1]


async def test_the_monday_job_survives_any_failure(session_factory, bot):
    service = SimpleNamespace(monday_summary=AsyncMock(side_effect=RuntimeError("db")))
    monday, _ = senders(session_factory, bot, service=service)
    await monday()  # does not raise
    bot.send_message.assert_not_called()


async def test_the_monday_job_survives_telegram_being_down(session_factory, bot):
    await seed(session_factory)
    bot.send_message.side_effect = RuntimeError("telegram down")
    monday, _ = senders(session_factory, bot, service=pinned(session_factory))
    await monday()  # does not raise


async def test_a_failed_demo_tells_the_user(session_factory, bot):
    service = SimpleNamespace(demo_summary=AsyncMock(side_effect=RuntimeError("db")))
    _, demo = senders(session_factory, bot, service=service)
    await demo()
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["text"] == SUMMARY_FAILED_TEXT


async def test_a_failed_demo_report_does_not_raise_either(session_factory, bot):
    service = SimpleNamespace(demo_summary=AsyncMock(side_effect=RuntimeError("db")))
    bot.send_message.side_effect = RuntimeError("telegram down")
    _, demo = senders(session_factory, bot, service=service)
    await demo()  # does not raise


async def test_the_sent_text_matches_the_saved_summary(session_factory, bot):
    await seed(session_factory)
    svc = pinned(session_factory)
    monday, _ = senders(session_factory, bot, service=svc)
    await monday()
    saved = await svc.latest()
    sent = bot.send_message.await_args.kwargs["text"]
    assert sent == summary_text(saved, LINK, 10)


# --- the command ---


def _update(chat_id):
    message = SimpleNamespace(text="/demo_summary", reply_text=AsyncMock())
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id), effective_message=message
    )


async def test_demo_summary_runs_for_the_owner_only():
    send = AsyncMock()
    context = SimpleNamespace(bot_data={"chat_id": 42, "send_demo_summary": send})
    await handlers.handle_demo_summary(_update(42), context)
    send.assert_awaited_once()
    send.reset_mock()
    await handlers.handle_demo_summary(_update(7), context)
    send.assert_not_called()


def test_the_demo_summary_command_is_registered(settings):
    application = build_application(settings, chat_graph=object())
    commands = {
        command
        for group in application.handlers.values()
        for h in group
        if isinstance(h, CommandHandler) and h.callback is handlers.handle_demo_summary
        for command in h.commands
    }
    assert commands == {"demo_summary"}
