"""Boundary: budgets are per category and month, versioned, and compared with spending.

What is tested: the service and the API against a real database. An edit adds a
version and never changes an earlier one; the current budget is the highest version;
"spent" is money out only and ignores moves between the user's own accounts.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from pfa.core.exceptions import NotFoundError
from pfa.models import BudgetVersion, Transaction
from pfa.repository.finance import CategoryRepository
from pfa.services.budgets import (
    applicable_month,
    build_budgets,
    month_end,
    parse_month,
    set_budget,
)

OCT = date(2026, 10, 1)
SEP = date(2026, 9, 1)


# --- the pure month helpers ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2026-10", date(2026, 10, 1)), ("1970-01", date(1970, 1, 1))],
)
def test_a_month_text_becomes_its_first_day(text, expected):
    assert parse_month(text) == expected


@pytest.mark.parametrize(
    ("month", "last"),
    [
        (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2028, 2, 1), date(2028, 2, 29)),  # leap year
        (date(2026, 12, 1), date(2026, 12, 31)),
    ],
)
def test_the_last_day_of_a_month(month, last):
    assert month_end(month) == last


def test_a_budget_applies_to_the_month_it_was_set_for():
    assert applicable_month([SEP, OCT], OCT) == OCT


def test_no_budget_for_a_month_by_default():
    """The default rule; update this test if you change `applicable_month`."""
    assert applicable_month([SEP], OCT) is None
    assert applicable_month([], OCT) is None


# --- seeding ---


async def add_spending(session_factory, rows):
    """Adds confirmed (category, amount, day, direction, is_transfer) rows."""
    async with session_factory() as session:
        repo = CategoryRepository(session)
        ids = {}
        for category, *_ in rows:
            if category not in ids:
                ids[category] = await repo.get_id_by_name(category)
        session.add_all(
            Transaction(
                merchant=f"{category} {i}",
                category_id=ids[category],
                amount=Decimal(amount),
                occurred_on=date.fromisoformat(day),
                direction=direction,
                is_transfer=flag,
                status="confirmed",
            )
            for i, (category, amount, day, direction, flag) in enumerate(rows)
        )
        await session.commit()


async def budgets(session_factory, month=OCT):
    async with session_factory() as session:
        return await build_budgets(session, month)


async def set_it(session_factory, category, month, amount):
    async with session_factory() as session:
        return await set_budget(session, category, month, Decimal(amount))


# --- versions ---


async def test_the_first_budget_is_version_one(session_factory):
    saved = await set_it(session_factory, "Dining", OCT, "1000000")
    assert (saved.version, saved.amount, saved.current) == (
        1,
        Decimal("1000000.00"),
        True,
    )


async def test_an_edit_adds_a_version_and_the_highest_is_current(session_factory):
    await set_it(session_factory, "Dining", OCT, "1000000")
    second = await set_it(session_factory, "Dining", OCT, "1500000")
    assert second.version == 2
    (item,) = (await budgets(session_factory)).items
    assert (item.version, item.amount) == (2, Decimal("1500000.00"))


async def test_older_versions_remain_after_an_edit(session_factory, authed_client):
    for amount in ("1000000", "1500000", "900000"):
        await set_it(session_factory, "Dining", OCT, amount)
    response = await authed_client.get(
        "/budgets/history", params={"category": "Dining", "month": "2026-10"}
    )
    assert [(v["version"], v["amount"], v["current"]) for v in response.json()] == [
        (3, "900000.00", True),
        (2, "1500000.00", False),
        (1, "1000000.00", False),
    ]
    async with session_factory() as session:
        stored = await session.scalar(select(func.count()).select_from(BudgetVersion))
    assert stored == 3  # nothing was overwritten


async def test_versions_are_counted_per_category_and_month(session_factory):
    await set_it(session_factory, "Dining", OCT, "100")
    await set_it(session_factory, "Dining", OCT, "200")
    assert (await set_it(session_factory, "Dining", SEP, "100")).version == 1
    assert (await set_it(session_factory, "Groceries", OCT, "100")).version == 1


async def test_a_budget_for_a_missing_category_is_refused(session_factory):
    with pytest.raises(NotFoundError):
        await set_it(session_factory, "Nonexistent", OCT, "100")


async def test_two_edits_at_once_both_get_a_version(session_factory):
    results = await asyncio.gather(
        *(set_it(session_factory, "Dining", OCT, str(100 + i)) for i in range(10))
    )
    assert sorted(r.version for r in results) == list(range(1, 11))


# --- spent and remaining ---


async def test_spent_is_money_out_in_the_month_and_remaining_is_the_rest(
    session_factory,
):
    await set_it(session_factory, "Dining", OCT, "1000")
    await add_spending(
        session_factory,
        [
            ("Dining", "300", "2026-10-02", "out", False),
            ("Dining", "150.50", "2026-10-31", "out", False),
            ("Dining", "999", "2026-09-30", "out", False),  # another month
            ("Dining", "50", "2026-11-01", "out", False),  # another month
        ],
    )
    (item,) = (await budgets(session_factory)).items
    assert item.spent == Decimal("450.50")
    assert item.remaining == Decimal("549.50")
    assert item.used == pytest.approx(0.4505)


async def test_money_in_never_pays_back_a_budget(session_factory):
    await set_it(session_factory, "Dining", OCT, "1000")
    await add_spending(
        session_factory,
        [
            ("Dining", "300", "2026-10-02", "out", False),
            ("Dining", "300", "2026-10-03", "in", False),  # e.g. a refund
        ],
    )
    (item,) = (await budgets(session_factory)).items
    assert item.spent == Decimal("300.00")


async def test_moves_between_own_accounts_do_not_use_up_a_budget(session_factory):
    await set_it(session_factory, "Dining", OCT, "1000")
    await add_spending(
        session_factory,
        [
            ("Dining", "300", "2026-10-02", "out", False),
            ("Dining", "700", "2026-10-03", "out", True),  # a pocket top-up
        ],
    )
    (item,) = (await budgets(session_factory)).items
    assert item.spent == Decimal("300.00")


async def test_money_sent_to_a_person_or_merchant_does_use_it_up(session_factory):
    # Filed under Transfer but not flagged as between own accounts: it is spending.
    await set_it(session_factory, "Transfer", OCT, "1000")
    await add_spending(
        session_factory, [("Transfer", "400", "2026-10-02", "out", False)]
    )
    (item,) = (await budgets(session_factory)).items
    assert item.spent == Decimal("400.00")


async def test_going_over_budget_shows_a_negative_remainder(session_factory):
    await set_it(session_factory, "Dining", OCT, "1000")
    await add_spending(
        session_factory, [("Dining", "1250", "2026-10-02", "out", False)]
    )
    (item,) = (await budgets(session_factory)).items
    assert item.remaining == Decimal("-250.00")
    assert item.used == pytest.approx(1.25)


async def test_unconfirmed_transactions_are_not_spent(session_factory):
    await set_it(session_factory, "Dining", OCT, "1000")
    async with session_factory() as session:
        dining = await CategoryRepository(session).get_id_by_name("Dining")
        session.add(
            Transaction(
                merchant="Pending",
                category_id=dining,
                amount=Decimal("500"),
                occurred_on=date(2026, 10, 2),
                direction="out",
                status="pending",
            )
        )
        await session.commit()
    (item,) = (await budgets(session_factory)).items
    assert item.spent == Decimal("0.00")


async def test_totals_and_unbudgeted_spending(session_factory):
    await set_it(session_factory, "Dining", OCT, "1000")
    await set_it(session_factory, "Groceries", OCT, "2000")
    await add_spending(
        session_factory,
        [
            ("Dining", "400", "2026-10-02", "out", False),
            ("Groceries", "100", "2026-10-03", "out", False),
            ("Other", "75", "2026-10-04", "out", False),  # no budget for Other
        ],
    )
    result = await budgets(session_factory)
    assert [i.category for i in result.items] == ["Dining", "Groceries"]
    assert result.total_budget == Decimal("3000.00")
    assert result.total_spent == Decimal("500.00")
    assert result.total_remaining == Decimal("2500.00")
    assert result.unbudgeted_spent == Decimal("75.00")


async def test_a_month_with_no_budgets_is_empty(session_factory):
    result = await budgets(session_factory)
    assert result.items == []
    assert result.total_budget == Decimal("0.00")


# --- the API ---


async def test_put_then_get_over_the_api(authed_client):
    put = await authed_client.put(
        "/budgets", json={"category": "Dining", "month": "2026-10", "amount": "250000"}
    )
    assert put.status_code == 200
    assert put.json()["version"] == 1
    got = (await authed_client.get("/budgets", params={"month": "2026-10"})).json()
    assert got["month"] == "2026-10-01"
    assert [(i["category"], i["amount"]) for i in got["items"]] == [
        ("Dining", "250000.00")
    ]


async def test_get_defaults_to_the_current_month(authed_client):
    response = await authed_client.get("/budgets")
    assert response.status_code == 200
    assert response.json()["month"].endswith("-01")


@pytest.mark.parametrize(
    ("body", "mentions"),
    [
        ({"category": "Dining", "month": "2026-10", "amount": "0"}, "Amount"),
        ({"category": "Dining", "month": "2026-10", "amount": "-5"}, "Amount"),
        ({"category": "Dining", "month": "2026-10", "amount": "10.999"}, "Amount"),
        ({"category": "Dining", "month": "2026-10", "amount": "NaN"}, "Amount"),
        ({"category": "Dining", "month": "2026-10", "amount": "1e20"}, "Amount"),
        ({"category": "Dining", "month": "2026-13", "amount": "5"}, "Month"),
        ({"category": "Dining", "month": "October", "amount": "5"}, "Month"),
    ],
)
async def test_bad_budgets_are_explained(authed_client, body, mentions):
    response = await authed_client.put("/budgets", json=body)
    assert response.status_code == 422
    assert mentions in response.json()["detail"]


async def test_an_unknown_category_is_a_plain_404(authed_client):
    response = await authed_client.put(
        "/budgets", json={"category": "Nope", "month": "2026-10", "amount": "5"}
    )
    assert response.status_code == 404
    assert "Nope" in response.json()["detail"]
    history = await authed_client.get(
        "/budgets/history", params={"category": "Nope", "month": "2026-10"}
    )
    assert history.status_code == 404


async def test_the_largest_amount_that_fits_is_accepted(authed_client):
    response = await authed_client.put(
        "/budgets",
        json={"category": "Dining", "month": "2026-10", "amount": "999999999999.99"},
    )
    assert response.status_code == 200


async def test_budgets_need_a_session(anon_client):
    assert (await anon_client.get("/budgets")).status_code == 401
    assert (await anon_client.put("/budgets", json={})).status_code == 401
