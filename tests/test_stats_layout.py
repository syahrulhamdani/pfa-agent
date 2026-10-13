"""Boundary: the figures in a chat answer are laid out to be read.

What is tested: one labelled figure per line, a category question leading with that
category, no empty sections, a minus on a negative net, a size that always fits one
Telegram message, and that every figure shown is one the facts hold.
"""

from datetime import date
from decimal import Decimal

from pfa.models import Goal, Transaction
from pfa.repository.finance import CategoryRepository
from pfa.schemas.analytics import Period
from pfa.services.budgets import set_budget
from pfa.services.insights import (
    gather_facts,
    numbers_grounded,
    render_facts,
    render_stats,
)

OCT = date(2026, 10, 1)
WED = date(2026, 10, 7)  # inside the week of Oct 5 - Oct 11
TODAY = date(2026, 10, 12)


async def seed(session_factory):
    async with session_factory() as session:
        ids = {
            name: await CategoryRepository(session).get_id_by_name(name)
            for name in ("Dining", "Groceries", "Salary", "Transfer", "Other")
        }
        rows = [
            ("Dining", "900", "2026-10-06", "out", False),
            ("Groceries", "150", "2026-10-07", "out", False),
            ("Groceries", "50", "2026-10-08", "out", False),
            ("Salary", "5000", "2026-10-09", "in", False),
            ("Transfer", "700", "2026-10-09", "out", True),
            ("Dining", "400", "2026-09-30", "out", False),  # the week before
        ]
        session.add_all(
            Transaction(
                merchant=f"{c} {i}",
                category_id=ids[c],
                amount=Decimal(a),
                occurred_on=date.fromisoformat(d),
                direction=direction,
                is_transfer=flag,
                status="confirmed",
            )
            for i, (c, a, d, direction, flag) in enumerate(rows)
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
        await set_budget(session, "Dining", OCT, Decimal("1000"))
        await set_budget(session, "Groceries", OCT, Decimal("100"))


async def facts(session_factory, **kwargs):
    async with session_factory() as session:
        return await gather_facts(session, Period.WEEK, WED, TODAY, **kwargs)


async def test_the_figures_are_laid_out_one_per_line(session_factory):
    await seed(session_factory)
    lines = render_stats(await facts(session_factory)).splitlines()
    assert lines[0] == "Week of Oct 5 – Oct 11, 2026"
    for expected in (
        "Money out: 1,100 (3 transactions) – 175% more than the previous week",
        "Money in: 5,000 (1 transaction)",
        "Net: +3,900",
        "Between your own accounts (not counted): 1 move, 700",
        "• Dining: 900 (82%)",
        "• Groceries: 200 (18%)",
        "• Groceries: 200 of 100 (200%), over budget by 100",
        "• Dining: 900 of 1,000 (90%), 100 left",
        "• Trip: 500 of 1,500 (33%), 14 days left, about 500 a week to get there",
        "Top spending:",
        "Budgets for October 2026:",
        "Goals:",
    ):
        assert expected in lines, expected


async def test_a_question_about_one_category_leads_with_it_and_skips_the_lists(
    session_factory,
):
    await seed(session_factory)
    lines = render_stats(await facts(session_factory, category="dining")).splitlines()
    assert lines[2] == "Dining: 900 spent (82% of your money out, 1 transaction)"
    assert lines[3] == "Budget for October 2026: 900 of 1,000 used (90%), 100 left"
    assert "Top spending:" not in lines and "Goals:" not in lines
    assert (
        "Money out: 1,100 (3 transactions) – 175% more than the previous week" in lines
    )


async def test_a_category_with_nothing_spent_says_so(session_factory):
    await seed(session_factory)
    text = render_stats(await facts(session_factory, category="Transport"))
    assert "Transport: nothing spent in this period" in text.splitlines()


async def test_an_empty_period_has_no_empty_sections(session_factory):
    text = render_stats(await facts(session_factory))
    assert "Money out: 0 (0 transactions)" in text
    for absent in ("Top spending", "Budgets for", "Goals:", "Between your own"):
        assert absent not in text


async def test_a_running_period_is_marked(session_factory):
    text = render_stats(await facts(session_factory, partial=True))
    assert text.splitlines()[0].endswith("(so far)")


async def test_every_figure_laid_out_is_one_the_facts_hold(session_factory):
    await seed(session_factory)
    for kwargs in (
        {},
        {"category": "Dining"},
        {"category": "Transport"},
        {"partial": True},
    ):
        f = await facts(session_factory, **kwargs)
        assert numbers_grounded(render_stats(f), render_facts(f)), kwargs


async def test_the_figures_fit_in_a_telegram_message_however_much_there_is(
    session_factory,
):
    async with session_factory() as session:
        session.add_all(
            Goal(
                name=f"Goal {i}",
                target_amount=Decimal("1000"),
                target_date=date(2027, 1, 1),
                saved_amount=Decimal("10"),
            )
            for i in range(40)
        )
        await session.commit()
    text = render_stats(await facts(session_factory))
    assert len(text) < 4096
    assert text.count("• Goal ") == 5  # only the first few goals are listed


async def test_a_negative_net_has_a_minus(session_factory):
    async with session_factory() as session:
        dining = await CategoryRepository(session).get_id_by_name("Dining")
        session.add(
            Transaction(
                merchant="x",
                category_id=dining,
                amount=Decimal("300"),
                occurred_on=WED,
                direction="out",
                status="confirmed",
            )
        )
        await session.commit()
    assert "Net: -300" in render_stats(await facts(session_factory))
