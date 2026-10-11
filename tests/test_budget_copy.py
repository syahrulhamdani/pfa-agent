"""Boundary: copying one month's budgets into another.

What is tested: only the current version of each budget is copied, as version 1; a
budget already set in the target month is never overwritten; copying twice (or twice
at once) creates nothing new; and the source month is left alone.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from pfa.models import Transaction
from pfa.repository.finance import CategoryRepository
from pfa.services.budgets import build_budgets, copy_budgets, set_budget

SEP = date(2026, 9, 1)
OCT = date(2026, 10, 1)
NOV = date(2026, 11, 1)


async def set_it(session_factory, category, month, amount):
    async with session_factory() as session:
        return await set_budget(session, category, month, Decimal(amount))


async def copy(session_factory, source, target):
    async with session_factory() as session:
        return await copy_budgets(session, source, target)


async def budgets(session_factory, month):
    async with session_factory() as session:
        return await build_budgets(session, month)


async def test_copying_duplicates_every_budget_into_the_next_month(session_factory):
    await set_it(session_factory, "Dining", OCT, "800000")
    await set_it(session_factory, "Groceries", OCT, "400000")
    result = await copy(session_factory, OCT, NOV)
    assert (result.copied, result.skipped) == (2, 0)
    nov = await budgets(session_factory, NOV)
    assert [(i.category, i.amount, i.version) for i in nov.items] == [
        ("Dining", Decimal("800000.00"), 1),
        ("Groceries", Decimal("400000.00"), 1),
    ]


async def test_only_the_current_version_is_copied(session_factory):
    for amount in ("100", "200", "300"):
        await set_it(session_factory, "Dining", OCT, amount)
    await copy(session_factory, OCT, NOV)
    (item,) = (await budgets(session_factory, NOV)).items
    assert (item.amount, item.version) == (Decimal("300.00"), 1)


async def test_the_source_month_is_left_untouched(session_factory):
    await set_it(session_factory, "Dining", OCT, "800")
    await set_it(session_factory, "Dining", OCT, "900")
    await copy(session_factory, OCT, NOV)
    (item,) = (await budgets(session_factory, OCT)).items
    assert (item.amount, item.version) == (Decimal("900.00"), 2)


async def test_a_budget_already_set_in_the_target_month_is_never_overwritten(
    session_factory,
):
    await set_it(session_factory, "Dining", OCT, "800")
    await set_it(session_factory, "Groceries", OCT, "400")
    await set_it(session_factory, "Dining", NOV, "123")  # already chosen for November
    result = await copy(session_factory, OCT, NOV)
    assert (result.copied, result.skipped) == (1, 1)
    nov = await budgets(session_factory, NOV)
    assert {i.category: (i.amount, i.version) for i in nov.items} == {
        "Dining": (Decimal("123.00"), 1),  # unchanged
        "Groceries": (Decimal("400.00"), 1),
    }


async def test_copying_twice_does_nothing_the_second_time(session_factory):
    await set_it(session_factory, "Dining", OCT, "800")
    await copy(session_factory, OCT, NOV)
    again = await copy(session_factory, OCT, NOV)
    assert (again.copied, again.skipped) == (0, 1)
    (item,) = (await budgets(session_factory, NOV)).items
    assert item.version == 1  # no second version was created


async def test_copying_from_a_month_with_no_budgets_copies_nothing(session_factory):
    result = await copy(session_factory, OCT, NOV)
    assert (result.copied, result.skipped) == (0, 0)
    assert (await budgets(session_factory, NOV)).items == []


async def test_only_the_named_source_month_is_copied(session_factory):
    await set_it(session_factory, "Dining", SEP, "500")  # an older month
    await set_it(session_factory, "Groceries", OCT, "400")
    await copy(session_factory, OCT, NOV)
    nov = await budgets(session_factory, NOV)
    assert [i.category for i in nov.items] == ["Groceries"]


async def test_copying_across_a_year_end(session_factory):
    await set_it(session_factory, "Dining", date(2026, 12, 1), "800")
    await copy(session_factory, date(2026, 12, 1), date(2027, 1, 1))
    (item,) = (await budgets(session_factory, date(2027, 1, 1))).items
    assert item.amount == Decimal("800.00")


async def test_copies_at_once_create_each_budget_only_once(session_factory):
    await set_it(session_factory, "Dining", OCT, "800")
    await set_it(session_factory, "Groceries", OCT, "400")
    results = await asyncio.gather(*(copy(session_factory, OCT, NOV) for _ in range(6)))
    assert sum(r.copied for r in results) == 2  # created once, however many raced
    nov = await budgets(session_factory, NOV)
    assert [i.version for i in nov.items] == [1, 1]


async def test_a_copy_does_not_carry_the_spending(session_factory):
    await set_it(session_factory, "Dining", OCT, "1000")
    async with session_factory() as session:
        dining = await CategoryRepository(session).get_id_by_name("Dining")
        session.add(
            Transaction(
                merchant="Warung",
                category_id=dining,
                amount=Decimal("400"),
                occurred_on=date(2026, 10, 2),
                direction="out",
                status="confirmed",
            )
        )
        await session.commit()
    await copy(session_factory, OCT, NOV)
    (item,) = (await budgets(session_factory, NOV)).items
    assert item.spent == Decimal("0.00")


async def test_copy_over_the_api(authed_client):
    await authed_client.put(
        "/budgets", json={"category": "Dining", "month": "2026-10", "amount": "800"}
    )
    response = await authed_client.post(
        "/budgets/copy", json={"from_month": "2026-10", "to_month": "2026-11"}
    )
    assert response.status_code == 200
    assert response.json() == {"copied": 1, "skipped": 0}
    got = (await authed_client.get("/budgets", params={"month": "2026-11"})).json()
    assert [i["category"] for i in got["items"]] == ["Dining"]


@pytest.mark.parametrize(
    ("body", "mentions"),
    [
        ({"from_month": "2026-10", "to_month": "2026-10"}, "two different months"),
        ({"from_month": "2026-13", "to_month": "2026-11"}, "YYYY-MM"),
        ({"from_month": "October", "to_month": "2026-11"}, "YYYY-MM"),
        ({"from_month": "2026-10"}, "To month"),
        ({}, "From month"),
    ],
)
async def test_a_bad_copy_is_explained(authed_client, body, mentions):
    response = await authed_client.post("/budgets/copy", json=body)
    assert response.status_code == 422
    assert mentions in response.json()["detail"]


async def test_copying_needs_a_session(anon_client):
    response = await anon_client.post(
        "/budgets/copy", json={"from_month": "2026-10", "to_month": "2026-11"}
    )
    assert response.status_code == 401
