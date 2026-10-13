"""Boundary: the sample budgets always show the features worth showing.

What is tested: on ordinary days of the month the sample data has one budget that is
over and one that is nearly used (so warnings and "budgets to watch" appear), the
amounts are rounded up to whole thousands, and a category with nothing spent yet falls
back to last month's amount instead of a zero budget.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from pfa.services.budgets import build_budgets
from pfa.services.categories import load_category_names
from pfa.services.demo import (
    LAST_MONTH_BUDGETS,
    _spent_this_month,
    _this_month_budget,
    plan_transactions,
    seed_demo,
)
from pfa.services.insights import budget_state

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = load_category_names(ROOT / "config" / "categories.json")


async def budgets_on(session_factory, today: date):
    now = datetime.combine(today, datetime.min.time(), tzinfo=UTC).replace(hour=3)
    await seed_demo(session_factory, CATEGORIES, today, "Asia/Jakarta", now)
    async with session_factory() as session:
        return await build_budgets(session, today.replace(day=1))


@pytest.mark.parametrize(
    "today",
    [date(2026, 10, 14), date(2026, 10, 21), date(2026, 10, 28), date(2026, 11, 20)],
)
async def test_one_budget_is_over_and_one_is_nearly_used(session_factory, today):
    result = await budgets_on(session_factory, today)
    states = {i.category: budget_state(i.used) for i in result.items}
    assert states["Groceries"] == "over"
    assert states["Dining"] == "near"
    assert states["Transport"] == "ok"


async def test_a_budget_that_is_over_says_by_how_much(session_factory):
    result = await budgets_on(session_factory, date(2026, 10, 14))
    groceries = next(i for i in result.items if i.category == "Groceries")
    assert groceries.remaining < 0 and groceries.used > 1


def test_scaled_budgets_are_rounded_up_to_whole_thousands():
    today = date(2026, 10, 14)
    spent = _spent_this_month(plan_transactions(today), today)
    for category in ("Groceries", "Dining", "Transport"):
        amount = _this_month_budget(category, spent, LAST_MONTH_BUDGETS[category])
        assert amount % 1000 == 0
        assert amount >= spent[category] * 0.9  # rounded up, never down


def test_a_category_with_nothing_spent_falls_back_to_last_months_amount():
    assert _this_month_budget("Dining", {}, 600_000) == 600_000
    assert _this_month_budget("Groceries", {}, 1_500_000) == 1_500_000


def test_fixed_budgets_ignore_what_was_spent():
    assert _this_month_budget("Shopping", {"Shopping": 999_999}, 1) == 400_000
    assert _this_month_budget("Entertainment", {}, 1) == 100_000


def test_only_real_spending_this_month_counts():
    today = date(2026, 10, 14)
    spent = _spent_this_month(plan_transactions(today), today)
    assert "Transfer" not in spent  # moves between pockets are not spending
    assert "Salary" not in spent and "Refund" not in spent  # money in is not spending
    assert spent["Groceries"] == 380_000 + 455_000 + 76_300  # this month, not last
