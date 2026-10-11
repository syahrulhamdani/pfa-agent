"""Budgets: which budget applies to a month, and how much of it has been spent.

"Spent" is money out only, in the month by receipt date. Moves between the user's own
accounts or pockets (the transfer flag) are not spending, so they never use up a
budget; payments to people or merchants are, and do.
"""

import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from pfa.core.exceptions import NotFoundError
from pfa.models import Direction
from pfa.repository.analytics import AnalyticsRepository
from pfa.repository.budgets import BudgetRepository
from pfa.repository.finance import CategoryRepository
from pfa.schemas.budgets import (
    BudgetRead,
    BudgetsCopied,
    BudgetsRead,
    BudgetVersionRead,
)

ZERO = Decimal("0.00")


def parse_month(text: str) -> date:
    """Turns "2026-10" into the first day of that month."""
    year, month = text.split("-")
    return date(int(year), int(month), 1)


def month_end(month: date) -> date:
    """Returns the last day of the month containing `month`."""
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def applicable_month(months: list[date], month: date) -> date | None:
    """Picks which month's budget applies to `month` for one category.

    Args:
        months: The first days of every month this category has a budget for,
            oldest first, none later than `month`.
        month: The first day of the month being looked at.

    Returns:
        One of `months` whose budget applies, or None when the category has no
        budget for `month`.
    """
    return month if month in months else None


async def build_budgets(session: AsyncSession, month: date) -> BudgetsRead:
    """Assembles every budget that applies to a month, with what has been spent.

    Args:
        session: Database session.
        month: The first day of the month.

    Returns:
        One row per budgeted category (alphabetical) and the totals. Spending in
        categories without a budget is reported apart as `unbudgeted_spent`.
    """
    by_category: dict[str, dict[date, tuple[Decimal, int]]] = {}
    for version, name in await BudgetRepository(session).current_through(month):
        by_category.setdefault(name, {})[version.month] = (
            version.amount,
            version.version,
        )

    rows = await AnalyticsRepository(session).by_category(month, month_end(month))
    spent_by_name = {
        name: total for direction, name, _, total in rows if direction is Direction.OUT
    }

    items: list[BudgetRead] = []
    for name, budgets in sorted(by_category.items()):
        source = applicable_month(sorted(budgets), month)
        if source is None or source not in budgets:
            continue
        amount, version = budgets[source]
        spent = spent_by_name.pop(name, ZERO)
        items.append(
            BudgetRead(
                category=name,
                month=month,
                set_for=source,
                amount=amount,
                version=version,
                spent=spent,
                remaining=amount - spent,
                used=round(float(spent / amount), 4),
            )
        )
    # Whatever is left was spent in a category that has no budget this month.
    budgeted = {item.category for item in items}
    unbudgeted = sum(
        (total for name, total in spent_by_name.items() if name not in budgeted), ZERO
    )
    total_budget = sum((i.amount for i in items), ZERO)
    total_spent = sum((i.spent for i in items), ZERO)
    return BudgetsRead(
        month=month,
        items=items,
        total_budget=total_budget,
        total_spent=total_spent,
        total_remaining=total_budget - total_spent,
        unbudgeted_spent=unbudgeted,
    )


async def set_budget(
    session: AsyncSession, category_name: str, month: date, amount: Decimal
) -> BudgetVersionRead:
    """Saves a new version of a category's budget for a month.

    Raises:
        NotFoundError: If the category does not exist.
    """
    category_id = await CategoryRepository(session).get_id_by_name(category_name)
    if category_id is None:
        raise NotFoundError(f"There is no category called “{category_name}”.")
    saved = await BudgetRepository(session).add_version(category_id, month, amount)
    return BudgetVersionRead(
        version=saved.version,
        amount=saved.amount,
        created_at=saved.created_at,
        current=True,
    )


async def copy_budgets(
    session: AsyncSession, source: date, target: date
) -> BudgetsCopied:
    """Copies the current budgets of one month into another.

    Only the current (highest) version of each source budget is copied, as version 1
    of the target. A category that already has a budget in the target month is left
    exactly as it is, so copying twice, or after editing, never overwrites anything.

    Args:
        session: Database session.
        source: The first day of the month to copy from.
        target: The first day of the month to copy into.

    Returns:
        How many budgets were created and how many categories were skipped.
    """
    repo = BudgetRepository(session)
    rows = [v for v, _ in await repo.current_through(source) if v.month == source]
    # Read everything before writing: each write commits and expires loaded rows.
    wanted = [(v.category_id, v.amount) for v in rows]
    copied = 0
    for category_id, amount in wanted:
        if await repo.add_first_version(category_id, target, amount):
            copied += 1
    return BudgetsCopied(copied=copied, skipped=len(wanted) - copied)


async def budget_history(
    session: AsyncSession, category_name: str, month: date
) -> list[BudgetVersionRead]:
    """Lists every saved version of a budget, newest (the current one) first.

    Raises:
        NotFoundError: If the category does not exist.
    """
    category_id = await CategoryRepository(session).get_id_by_name(category_name)
    if category_id is None:
        raise NotFoundError(f"There is no category called “{category_name}”.")
    versions = await BudgetRepository(session).history(category_id, month)
    return [
        BudgetVersionRead(
            version=v.version,
            amount=v.amount,
            created_at=v.created_at,
            current=index == 0,
        )
        for index, v in enumerate(versions)
    ]
