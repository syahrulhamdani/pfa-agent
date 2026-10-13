"""Boundary: the sample data fills an empty database with a believable, current picture.

What is tested: what is added (and that all of it is confirmed and fictional), that
nothing is dated in the future whatever today is (month ends, a leap day, a year
change), that the moves between pockets are flagged so they stay out of the totals,
that budgets, goals and a summary exist, that Today's transactions has something, and
that it refuses to mix into a database that already has data.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from pfa.models import Bank, BudgetVersion, Card, Goal, Transaction
from pfa.repository.summaries import SummaryRepository
from pfa.schemas.analytics import Period
from pfa.services.analytics import build_analytics
from pfa.services.budgets import build_budgets
from pfa.services.categories import load_category_names
from pfa.services.demo import DemoError, plan_transactions, seed_demo
from pfa.services.summaries import read_summary
from pfa.services.transactions import todays_transactions

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = load_category_names(ROOT / "config" / "categories.json")
TZ = "Asia/Jakarta"
TODAY = date(2026, 10, 14)  # a Wednesday
NOW = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)  # 10:00 in Jakarta


async def seed(session_factory, today=TODAY, now=NOW):
    return await seed_demo(session_factory, CATEGORIES, today, TZ, now)


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


# --- the plan ---


def test_the_plan_is_the_same_every_time():
    assert plan_transactions(TODAY) == plan_transactions(TODAY)


@pytest.mark.parametrize(
    "today",
    [
        date(2026, 10, 1),  # the first of the month
        date(2026, 10, 14),
        date(2026, 10, 31),
        date(2026, 3, 1),  # last month was February
        date(2028, 3, 1),  # last month had a leap day
        date(2027, 1, 3),  # last month was in the year before
        date(2026, 12, 31),
    ],
)
def test_nothing_is_dated_in_the_future_and_amounts_are_positive(today):
    rows = plan_transactions(today)
    assert rows
    assert all(row["occurred_on"] <= today for row in rows)
    assert all(row["amount"] > 0 for row in rows)
    assert {row["direction"] for row in rows} <= {"in", "out"}


def test_both_months_are_covered():
    months = {
        (r["occurred_on"].year, r["occurred_on"].month)
        for r in plan_transactions(TODAY)
    }
    assert months == {(2026, 9), (2026, 10)}


def test_a_day_that_does_not_exist_in_a_short_month_is_skipped():
    rows = plan_transactions(date(2026, 3, 31))  # February has no 29th
    assert all(r["occurred_on"].month in (2, 3) for r in rows)
    assert all((r["occurred_on"].month, r["occurred_on"].day) != (2, 29) for r in rows)


# --- what is added ---


async def test_the_database_is_filled(session_factory):
    seeded = await seed(session_factory)
    assert seeded.transactions == await count(session_factory, Transaction) > 30
    assert seeded.goals == await count(session_factory, Goal) == 3
    assert seeded.budgets == await count(session_factory, BudgetVersion) == 10
    assert await count(session_factory, Bank) == 1
    assert await count(session_factory, Card) == 2


async def test_everything_is_confirmed_and_dated_when_it_happened(session_factory):
    await seed(session_factory)
    async with session_factory() as session:
        rows = (await session.scalars(select(Transaction))).all()
    assert {t.status for t in rows} == {"confirmed"}
    assert all(t.confirmed_at is not None and t.card_id for t in rows)
    old = [t for t in rows if t.occurred_on < date(2026, 10, 13)]
    assert all(t.confirmed_at.date() <= NOW.date() for t in old)


async def test_every_configured_category_exists_afterwards(session_factory):
    await seed(session_factory)
    from pfa.repository.finance import CategoryRepository

    async with session_factory() as session:
        names = {c.name for c in await CategoryRepository(session).list_all()}
    assert set(CATEGORIES) <= names


async def test_moves_between_pockets_are_flagged_and_balance(session_factory):
    await seed(session_factory)
    async with session_factory() as session:
        moves = (
            await session.scalars(select(Transaction).where(Transaction.is_transfer))
        ).all()
    out = sum(t.amount for t in moves if t.direction == "out")
    into = sum(t.amount for t in moves if t.direction == "in")
    assert moves and out == into


async def test_the_dashboard_leaves_the_moves_out_of_both_totals(session_factory):
    await seed(session_factory)
    async with session_factory() as session:
        month = await build_analytics(session, Period.MONTH, TODAY)
    assert month.transfers.count == 2 and month.transfers.total == Decimal("2000000")
    assert month.money_in.total < Decimal("15000000")  # not inflated by the move
    assert month.money_out.count > 0 and month.money_in.count > 0


async def test_this_months_budgets_show_what_is_left(session_factory):
    await seed(session_factory)
    async with session_factory() as session:
        budgets = await build_budgets(session, date(2026, 10, 1))
    assert {i.category for i in budgets.items} == {
        "Groceries",
        "Dining",
        "Transport",
        "Shopping",
        "Entertainment",
    }
    assert all(i.version == 1 for i in budgets.items)
    assert budgets.total_spent > 0


async def test_last_months_budgets_exist_too_so_copying_has_something(session_factory):
    await seed(session_factory)
    async with session_factory() as session:
        budgets = await build_budgets(session, date(2026, 9, 1))
    assert len(budgets.items) == 5


async def test_one_goal_is_reached_and_others_are_not(session_factory):
    await seed(session_factory)
    async with session_factory() as session:
        goals = (await session.scalars(select(Goal))).all()
    assert sorted(g.saved_amount >= g.target_amount for g in goals) == [
        False,
        False,
        True,
    ]
    assert all(g.target_date > TODAY for g in goals)


async def test_todays_transactions_has_something_to_show(session_factory):
    await seed(session_factory)
    async with session_factory() as session:
        today = await todays_transactions(session, TZ, NOW)
    assert len(today) >= 3
    assert {"Kopi Kenangan", "Gojek", "Indomaret"} <= {t.merchant for t in today}


async def test_a_weekly_summary_is_saved_from_the_template(session_factory):
    seeded = await seed(session_factory)
    async with session_factory() as session:
        row = await SummaryRepository(session).latest()
    summary = read_summary(row)
    assert summary.source == "fallback"
    assert summary.facts.has_activity and summary.recommendations
    assert (
        summary.week_start == seeded.summary_week and seeded.summary_week.weekday() == 0
    )


@pytest.mark.parametrize(
    "today",
    [
        date(2026, 10, 1),
        date(2026, 10, 12),
        date(2026, 10, 31),
        date(2027, 1, 3),
        date(2028, 3, 1),
    ],
)
async def test_it_works_whatever_day_it_is(session_factory, today):
    now = datetime.combine(today, datetime.min.time(), tzinfo=UTC).replace(hour=3)
    seeded = await seed(session_factory, today, now)
    assert seeded.transactions > 0
    async with session_factory() as session:
        latest = await SummaryRepository(session).latest()
    assert read_summary(latest).facts.has_activity


# --- refusing to mix with real data ---


async def test_it_refuses_a_database_that_already_has_transactions(session_factory):
    await seed(session_factory)
    before = await count(session_factory, Transaction)
    with pytest.raises(DemoError, match="docker compose down -v"):
        await seed(session_factory)
    assert await count(session_factory, Transaction) == before  # nothing was added


async def test_it_refuses_a_database_that_has_goals(session_factory):
    async with session_factory() as session:
        session.add(
            Goal(
                name="Mine",
                target_amount=Decimal("100"),
                target_date=date(2027, 1, 1),
                saved_amount=Decimal("0"),
            )
        )
        await session.commit()
    with pytest.raises(DemoError):
        await seed(session_factory)
    assert await count(session_factory, Transaction) == 0
    assert await count(session_factory, Bank) == 0
