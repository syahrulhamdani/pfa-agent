"""Boundary: the weekly summary is written from facts, checked, and stored once a week.

What is tested: which week is summarised, that the model is shown only the facts text,
that a reply quoting a figure outside the facts is replaced by the template, that a
week is saved once (Monday never rewrites or resends it, a demo replaces it), and the
API that serves the saved summary.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from pfa.core.exceptions import LLMError
from pfa.graphs.insights import RECOMMEND_PROMPT, advice_lines
from pfa.graphs.recommendations import build_summary_graph
from pfa.models import Goal, Transaction, WeeklySummary
from pfa.repository.finance import CategoryRepository
from pfa.services.budgets import set_budget
from pfa.services.insights import numbers_grounded, render_facts
from pfa.services.summaries import SummaryService, last_full_week

MONDAY = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)  # Mon 08:00 in Jakarta
SUNDAY = datetime(2026, 10, 11, 3, 0, tzinfo=UTC)
TZ = "Asia/Jakarta"


class Writer:
    """A fake model: records what it was shown and replies as told."""

    def __init__(self, reply="Keep Groceries in check.\nSet aside 500 a week."):
        self.reply = reply
        self.calls: list[tuple[str, str, str]] = []

    async def __call__(self, instruction, facts_text, question):
        self.calls.append((instruction, facts_text, question))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def service(session_factory, writer):
    graph = build_summary_graph(session_factory, writer)
    return SummaryService(session_factory, graph, TZ)


async def seed(session_factory):
    """Spending in the week of Oct 5 - 11, a budget and a goal."""
    async with session_factory() as session:
        ids = {
            name: await CategoryRepository(session).get_id_by_name(name)
            for name in ("Dining", "Groceries", "Salary")
        }
        session.add_all(
            Transaction(
                merchant=f"{c} {i}",
                category_id=ids[c],
                amount=Decimal(a),
                occurred_on=date.fromisoformat(d),
                direction=direction,
                status="confirmed",
            )
            for i, (c, a, d, direction) in enumerate(
                [
                    ("Dining", "900", "2026-10-06", "out"),
                    ("Groceries", "200", "2026-10-07", "out"),
                    ("Salary", "5000", "2026-10-09", "in"),
                ]
            )
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


async def rows(session_factory) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(WeeklySummary))


# --- which week ---


@pytest.mark.parametrize(
    ("today", "start", "end"),
    [
        (date(2026, 10, 12), date(2026, 10, 5), date(2026, 10, 11)),  # a Monday
        (date(2026, 10, 11), date(2026, 9, 28), date(2026, 10, 4)),  # a Sunday
        (date(2026, 10, 14), date(2026, 10, 5), date(2026, 10, 11)),  # mid-week
        (date(2027, 1, 4), date(2026, 12, 28), date(2027, 1, 3)),  # across a year
        (date(2028, 3, 6), date(2028, 2, 28), date(2028, 3, 5)),  # across a leap day
    ],
)
def test_the_week_that_just_ended_runs_monday_to_sunday(today, start, end):
    assert last_full_week(today) == (start, end)
    assert start.weekday() == 0 and end.weekday() == 6


def test_advice_lines_drop_bullets_numbers_and_blank_lines():
    text = "- First\n\n* Second\n3. Third\n• Fourth\n# Fifth\nSixth\nSeventh"
    assert advice_lines(text) == ["First", "Second", "Third", "Fourth", "Fifth"]


def test_a_very_long_line_is_cut():
    (line,) = advice_lines("x" * 1000)
    assert len(line) == 320


# --- what the model sees and what it may say ---


async def test_the_model_is_shown_only_the_facts_text(session_factory):
    await seed(session_factory)
    writer = Writer()
    await service(session_factory, writer).monday_summary(MONDAY)
    ((instruction, facts_text, question),) = writer.calls
    assert instruction == RECOMMEND_PROMPT
    assert question == ""
    assert "Week of Oct 5 – Oct 11, 2026" in facts_text
    assert "Money out: 1,100 in 2 transactions" in facts_text
    assert "Groceries is over budget by 100" in facts_text


async def test_advice_that_stays_with_the_facts_is_kept(session_factory):
    await seed(session_factory)
    result = await service(session_factory, Writer()).monday_summary(MONDAY)
    assert result.created
    assert result.summary.source == "model"
    assert result.summary.recommendations == [
        "Keep Groceries in check.",
        "Set aside 500 a week.",
    ]


@pytest.mark.parametrize(
    "reply",
    [
        "You spent 1,234 on food.",  # a figure that is not in the facts
        "Money out was 1,100, so 2,200 over two weeks.",  # a figure it computed
        "Cut dining by 40%.",  # an invented percentage
    ],
)
async def test_advice_with_a_figure_outside_the_facts_is_replaced(
    session_factory, reply
):
    await seed(session_factory)
    result = await service(session_factory, Writer(reply)).monday_summary(MONDAY)
    summary = result.summary
    assert summary.source == "fallback"
    assert reply not in summary.recommendations
    for text in summary.recommendations:
        assert numbers_grounded(text, render_facts(summary.facts)), text


@pytest.mark.parametrize(
    "reply",
    [LLMError("rate limited"), "", "   \n  \n", "- \n* "],
)
async def test_a_failed_or_empty_reply_falls_back_to_the_template(
    session_factory, reply
):
    await seed(session_factory)
    result = await service(session_factory, Writer(reply)).monday_summary(MONDAY)
    assert result.summary.source == "fallback"
    assert result.summary.recommendations  # the summary still goes out


async def test_markdown_in_the_reply_is_tidied(session_factory):
    await seed(session_factory)
    reply = "1. Watch Groceries.\n2. Save 500 a week.\n- Dining was 900."
    result = await service(session_factory, Writer(reply)).monday_summary(MONDAY)
    assert result.summary.recommendations == [
        "Watch Groceries.",
        "Save 500 a week.",
        "Dining was 900.",
    ]


# --- once a week ---


async def test_monday_writes_the_week_that_just_ended(session_factory):
    await seed(session_factory)
    result = await service(session_factory, Writer()).monday_summary(MONDAY)
    assert (result.summary.week_start, result.summary.week_end) == (
        date(2026, 10, 5),
        date(2026, 10, 11),
    )
    assert result.summary.facts.partial is False
    assert await rows(session_factory) == 1


async def test_monday_never_rewrites_or_resends_a_finished_week(session_factory):
    await seed(session_factory)
    writer = Writer()
    svc = service(session_factory, writer)
    first = await svc.monday_summary(MONDAY)
    second = await svc.monday_summary(MONDAY)
    assert first.created and not second.created
    assert len(writer.calls) == 1  # the model was not asked again
    assert second.summary.created_at == first.summary.created_at
    assert await rows(session_factory) == 1


async def test_a_new_week_gets_its_own_summary(session_factory):
    await seed(session_factory)
    svc = service(session_factory, Writer())
    await svc.monday_summary(MONDAY)
    next_monday = datetime(2026, 10, 19, 1, 0, tzinfo=UTC)
    result = await svc.monday_summary(next_monday)
    assert result.created and result.summary.week_start == date(2026, 10, 12)
    assert await rows(session_factory) == 2


async def test_a_demo_always_writes_a_fresh_one_in_the_same_row(session_factory):
    await seed(session_factory)
    writer = Writer()
    svc = service(session_factory, writer)
    first = await svc.demo_summary(MONDAY)
    second = await svc.demo_summary(MONDAY)
    assert first.created and second.created
    assert len(writer.calls) == 2
    assert await rows(session_factory) == 1  # replaced, never duplicated


async def test_a_demo_with_an_empty_last_week_uses_this_week_so_far(session_factory):
    # Nothing was recorded last week, but there is something this week.
    async with session_factory() as session:
        dining = await CategoryRepository(session).get_id_by_name("Dining")
        session.add(
            Transaction(
                merchant="Warung",
                category_id=dining,
                amount=Decimal("80"),
                occurred_on=date(2026, 10, 13),
                direction="out",
                status="confirmed",
            )
        )
        await session.commit()
    wednesday = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)
    result = await service(session_factory, Writer()).demo_summary(wednesday)
    assert result.summary.week_start == date(2026, 10, 12)
    assert result.summary.facts.partial is True
    assert "still running" in render_facts(result.summary.facts)


async def test_a_partial_demo_does_not_stop_the_real_monday_summary(session_factory):
    async with session_factory() as session:
        dining = await CategoryRepository(session).get_id_by_name("Dining")
        session.add(
            Transaction(
                merchant="Warung",
                category_id=dining,
                amount=Decimal("80"),
                occurred_on=date(2026, 10, 13),
                direction="out",
                status="confirmed",
            )
        )
        await session.commit()
    writer = Writer()
    svc = service(session_factory, writer)
    await svc.demo_summary(datetime(2026, 10, 14, 3, 0, tzinfo=UTC))  # partial
    result = await svc.monday_summary(datetime(2026, 10, 19, 1, 0, tzinfo=UTC))
    assert result.created  # it replaced the partial one and will be sent
    assert result.summary.facts.partial is False
    assert result.summary.week_start == date(2026, 10, 12)
    assert await rows(session_factory) == 1


async def test_a_sunday_summarises_the_week_before_not_the_running_one(session_factory):
    await seed(session_factory)
    result = await service(session_factory, Writer()).monday_summary(SUNDAY)
    assert result.summary.week_start == date(2026, 9, 28)


async def test_an_empty_week_still_produces_a_summary(session_factory):
    result = await service(session_factory, Writer("Nothing to add.")).monday_summary(
        MONDAY
    )
    assert result.created
    assert result.summary.facts.has_activity is False
    assert await rows(session_factory) == 1


# --- storage and the API ---


async def test_the_saved_summary_round_trips_exactly(session_factory):
    await seed(session_factory)
    svc = service(session_factory, Writer())
    written = (await svc.monday_summary(MONDAY)).summary
    assert await svc.latest() == written


async def test_latest_is_none_before_any_summary(session_factory):
    assert await service(session_factory, Writer()).latest() is None


async def test_the_latest_week_wins(session_factory):
    await seed(session_factory)
    svc = service(session_factory, Writer())
    await svc.monday_summary(MONDAY)
    await svc.monday_summary(datetime(2026, 10, 19, 1, 0, tzinfo=UTC))
    assert (await svc.latest()).week_start == date(2026, 10, 12)


async def test_the_api_serves_what_was_written(session_factory, authed_client):
    await seed(session_factory)
    written = (await service(session_factory, Writer()).monday_summary(MONDAY)).summary
    response = await authed_client.get("/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["week_start"] == "2026-10-05"
    assert body["recommendations"] == written.recommendations
    assert body["facts"]["money_out"] == "1100.00"
    assert body["source"] == "model"


async def test_the_api_explains_when_there_is_no_summary(authed_client):
    response = await authed_client.get("/summary")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "Monday" in detail
    assert "/" not in detail  # no command names for a person to decode


async def test_the_summary_needs_a_session(anon_client):
    assert (await anon_client.get("/summary")).status_code == 401
