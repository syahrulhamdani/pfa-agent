"""Fictional sample data, so a fresh install can show a full dashboard straight away.

Everything here is invented: a made-up bank, made-up spending in Jakarta-style merchants
across last month and this month (up to today), a pocket top-up that is not counted,
budgets (some close to their limit, some over), savings goals, and a weekly summary
written from a template. The dates move with today, so the charts always look current.
It refuses to touch a database that already holds transactions or goals.
"""

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pfa.core.exceptions import PfaError
from pfa.models import Goal, Transaction, TransactionStatus
from pfa.repository.budgets import BudgetRepository
from pfa.repository.finance import (
    BankRepository,
    CardRepository,
    CategoryRepository,
)
from pfa.repository.summaries import SummaryRepository
from pfa.schemas.analytics import Period
from pfa.services.categories import seed_categories
from pfa.services.insights import fallback_recommendations, gather_facts
from pfa.services.summaries import last_full_week, this_week_start

BANK_NAME = "Demo Bank"
CARDS = {"debit": ("Everyday Debit", "4242"), "credit": ("Travel Credit", "1881")}

# (day of month, merchant, category, direction, amount, card, is_transfer)
MONTHLY: list[tuple[int, str, str, str, int, str, bool]] = [
    (1, "Salary", "Salary", "in", 12_000_000, "debit", False),
    (3, "Kost Mawar Residence", "Housing", "out", 2_000_000, "debit", False),
    (5, "Indomaret", "Groceries", "out", 380_000, "debit", False),
    (8, "Move to savings pocket", "Transfer", "out", 1_000_000, "debit", True),
    (8, "From main pocket", "Transfer", "in", 1_000_000, "debit", True),
    (10, "PLN Prepaid", "Utilities", "out", 650_000, "debit", False),
    (12, "Alfamart", "Groceries", "out", 455_000, "debit", False),
    (15, "Telkomsel", "Utilities", "out", 150_000, "debit", False),
    (17, "Kimia Farma", "Health", "out", 285_000, "debit", False),
    (19, "Superindo", "Groceries", "out", 410_000, "debit", False),
    (20, "XXI Cinema", "Entertainment", "out", 150_000, "credit", False),
    (22, "Tokopedia", "Shopping", "out", 349_000, "credit", False),
    (24, "Refund Tokopedia", "Refund", "in", 120_000, "credit", False),
    (26, "Alfamart", "Groceries", "out", 520_000, "debit", False),
    (28, "Bank interest", "Interest", "in", 18_500, "debit", False),
]
LUNCH_DAYS = (2, 9, 16, 23)  # Warung Makan Sederhana
COFFEE_EVERY = 3  # Kopi Kenangan on days divisible by this
RIDE_EVERY = 4  # Grab on days where day % RIDE_EVERY == 1

LAST_MONTH_BUDGETS = {
    "Groceries": 1_500_000,
    "Dining": 600_000,
    "Transport": 350_000,
    "Shopping": 400_000,
    "Entertainment": 100_000,
}
# This month's budgets. A number is a fixed amount. A ("spent", factor) pair is set
# from what the sample data has spent so far this month, so the dashboard always has
# a budget that is nearly used (a factor just above 1) and one that is over (below
# 1), whatever day of the month it is. Amounts are rounded up to the nearest thousand.
THIS_MONTH_BUDGETS: dict[str, int | tuple[str, float]] = {
    "Groceries": ("spent", 0.9),  # over budget
    "Dining": ("spent", 1.12),  # nearly used
    "Transport": ("spent", 1.8),  # comfortable
    "Shopping": 400_000,
    "Entertainment": 100_000,
}
BUDGET_ROUNDING = 1_000
GOALS = [  # name, target, months until the date, saved so far
    ("Trip to Japan", 25_000_000, 8, 8_500_000),
    ("Emergency fund", 10_000_000, 2, 10_000_000),
    ("New laptop", 18_000_000, 5, 4_000_000),
]


class DemoError(PfaError):
    """The sample data was not added; the message says why and what to do."""


@dataclass(frozen=True)
class DemoSeeded:
    """What was added."""

    transactions: int
    budgets: int
    goals: int
    summary_week: date


def _month_start(today: date, months_back: int) -> date:
    index = today.year * 12 + today.month - 1 - months_back
    return date(index // 12, index % 12 + 1, 1)


def _day_in(month: date, day: int) -> date | None:
    last = calendar.monthrange(month.year, month.month)[1]
    return month.replace(day=day) if day <= last else None


def plan_transactions(today: date) -> list[dict]:
    """Lays out the sample transactions for last month and this month so far."""
    rows: list[dict] = []

    def add(day, merchant, category, direction, amount, card, flag=False):
        rows.append(
            {
                "occurred_on": day,
                "merchant": merchant,
                "category": category,
                "direction": direction,
                "amount": amount,
                "card": card,
                "is_transfer": flag,
            }
        )

    for months_back in (1, 0):
        start = _month_start(today, months_back)
        days = [d for n in range(1, 32) if (d := _day_in(start, n)) and d <= today]
        for day, merchant, category, direction, amount, card, flag in MONTHLY:
            on = _day_in(start, day)
            if on and on <= today:
                add(on, merchant, category, direction, amount, card, flag)
        for on in days:
            if on.day in LUNCH_DAYS:
                add(
                    on,
                    "Warung Makan Sederhana",
                    "Dining",
                    "out",
                    48_000 + on.day * 1_000,
                    "debit",
                )
            if on.day % COFFEE_EVERY == 0:
                add(
                    on, "Kopi Kenangan", "Dining", "out", 28_000 + on.day * 500, "debit"
                )
            if on.day % RIDE_EVERY == 1:
                add(on, "Grab", "Transport", "out", 24_000 + on.day * 700, "debit")
    # A few from the last two days, so Today's transactions has something to show.
    add(today, "Kopi Kenangan", "Dining", "out", 32_000, "debit")
    add(today, "Gojek", "Transport", "out", 28_500, "debit")
    add(today - timedelta(days=1), "Indomaret", "Groceries", "out", 76_300, "debit")
    return rows


def _spent_this_month(planned: list[dict], today: date) -> dict[str, int]:
    """Adds up what the sample data spends so far this month, by category."""
    start = today.replace(day=1)
    totals: dict[str, int] = {}
    for row in planned:
        if (
            row["occurred_on"] >= start
            and row["direction"] == "out"
            and not row["is_transfer"]
        ):
            totals[row["category"]] = totals.get(row["category"], 0) + row["amount"]
    return totals


def _this_month_budget(category: str, spent: dict[str, int], fallback: int) -> int:
    """Returns this month's budget for a category (see THIS_MONTH_BUDGETS)."""
    rule = THIS_MONTH_BUDGETS[category]
    if isinstance(rule, int):
        return rule
    so_far = spent.get(category, 0)
    if so_far == 0:
        return fallback  # nothing spent yet, so there is nothing to scale from
    scaled = so_far * rule[1]
    return int(-(-scaled // BUDGET_ROUNDING) * BUDGET_ROUNDING)  # rounded up


async def _already_has_data(session: AsyncSession) -> bool:
    for model in (Transaction, Goal):
        if await session.scalar(select(func.count()).select_from(model)):
            return True
    return False


async def seed_demo(
    session_factory: async_sessionmaker[AsyncSession],
    category_names: list[str],
    today: date,
    timezone: str,
    now: datetime | None = None,
) -> DemoSeeded:
    """Adds the sample data.

    Args:
        session_factory: Where to add it.
        category_names: The configured categories (added if missing).
        today: Today's date in the user's timezone.
        timezone: IANA timezone name, used for when things were confirmed.
        now: The current moment; injectable for tests.

    Returns:
        Counts of what was added.

    Raises:
        DemoError: If the database already holds transactions or goals.
    """
    tz = ZoneInfo(timezone)
    now = now or datetime.now(UTC)
    await seed_categories(session_factory, category_names)
    async with session_factory() as session:
        if await _already_has_data(session):
            raise DemoError(
                "This database already has transactions or goals, and sample data "
                "would mix in with them. Use an empty database: "
                "`docker compose down -v`, then `docker compose up -d --wait db` and "
                "`uv run --env-file .env alembic upgrade head`."
            )
        categories = CategoryRepository(session)
        ids = {name: await categories.get_id_by_name(name) for name in category_names}
        bank = await BankRepository(session).get_by_name(BANK_NAME) or (
            await BankRepository(session).add(BANK_NAME)
        )
        cards = {
            key: await CardRepository(session).add(bank.id, name, last4)
            for key, (name, last4) in CARDS.items()
        }
        planned = plan_transactions(today)
        for index, row in enumerate(planned):
            recent = row["occurred_on"] >= today - timedelta(days=1)
            confirmed = (
                now - timedelta(minutes=index)
                if recent
                else datetime.combine(row["occurred_on"], time(12, 0), tzinfo=tz)
            )
            session.add(
                Transaction(
                    card_id=cards[row["card"]].id,
                    merchant=row["merchant"],
                    amount=Decimal(row["amount"]),
                    occurred_on=row["occurred_on"],
                    category_id=ids[row["category"]],
                    direction=row["direction"],
                    is_transfer=row["is_transfer"],
                    status=TransactionStatus.CONFIRMED.value,
                    confirmed_at=confirmed.astimezone(UTC),
                )
            )
        for name, target, months, saved in GOALS:
            month_index = today.year * 12 + today.month - 1 + months
            session.add(
                Goal(
                    name=name,
                    target_amount=Decimal(target),
                    target_date=date(month_index // 12, month_index % 12 + 1, 15),
                    saved_amount=Decimal(saved),
                )
            )
        await session.commit()

        budgets = BudgetRepository(session)
        spent = _spent_this_month(planned, today)
        added = 0
        for category, last_month in LAST_MONTH_BUDGETS.items():
            this_month = _this_month_budget(category, spent, last_month)
            for months_back, amount in ((1, last_month), (0, this_month)):
                await budgets.add_version(
                    ids[category], _month_start(today, months_back), Decimal(amount)
                )
                added += 1

    week = await _write_summary(session_factory, today)
    return DemoSeeded(len(planned), added, len(GOALS), week)


async def _write_summary(
    session_factory: async_sessionmaker[AsyncSession], today: date
) -> date:
    """Saves a weekly summary written from the template (no model needed)."""
    start, _ = last_full_week(today)
    partial = False
    async with session_factory() as session:
        facts = await gather_facts(
            session,
            Period.WEEK,
            start,
            today,
            budget_month=today.replace(day=1),
        )
        if not facts.has_activity:
            start, partial = this_week_start(today), True
            facts = await gather_facts(
                session,
                Period.WEEK,
                start,
                today,
                budget_month=today.replace(day=1),
                partial=True,
            )
        await SummaryRepository(session).save(
            facts.start,
            {"facts": facts.model_dump(mode="json"), "source": "fallback"},
            "\n".join(fallback_recommendations(facts)),
        )
    return start if not partial else this_week_start(today)
