"""Boundary: each transaction says which way money moved; lists can filter on it."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from pfa.models import Transaction
from pfa.repository.finance import CategoryRepository


def at(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, 0, tzinfo=UTC)


@pytest.fixture
async def client(session_factory, authed_client):
    """Two expenses and two incomes, all confirmed.

    Indomaret  out  45000     Salary  in  9000000
    Warung     out  25000     Refund  in  150000
    """
    async with session_factory() as session:
        ids = {
            name: await CategoryRepository(session).get_id_by_name(name)
            for name in ("Groceries", "Dining", "Salary", "Refund")
        }

        def make(merchant, category, amount, direction, hour):
            return Transaction(
                merchant=merchant,
                category_id=ids[category],
                amount=Decimal(amount),
                occurred_on=date(2026, 10, 3),
                direction=direction,
                status="confirmed",
                confirmed_at=at(5, hour),
            )

        session.add_all(
            [
                make("Indomaret", "Groceries", "45000", "out", 9),
                make("Warung", "Dining", "25000", "out", 10),
                make("Salary", "Salary", "9000000", "in", 11),
                make("Refund", "Refund", "150000", "in", 12),
            ]
        )
        await session.commit()
    yield authed_client


async def merchants(client, **params) -> list[str]:
    response = await client.get("/transactions", params=params)
    assert response.status_code == 200, response.text
    return [row["merchant"] for row in response.json()]


async def test_every_transaction_reports_its_direction(client):
    rows = (await client.get("/transactions")).json()
    assert {r["merchant"]: r["direction"] for r in rows} == {
        "Indomaret": "out",
        "Warung": "out",
        "Salary": "in",
        "Refund": "in",
    }


async def test_without_a_direction_both_come_back_newest_first(client):
    assert await merchants(client) == ["Refund", "Salary", "Warung", "Indomaret"]


async def test_money_out_only(client):
    assert await merchants(client, direction="out") == ["Warung", "Indomaret"]


async def test_money_in_only(client):
    assert await merchants(client, direction="in") == ["Refund", "Salary"]


async def test_direction_combines_with_the_other_filters(client):
    assert await merchants(client, direction="in", min_amount=1_000_000) == ["Salary"]
    assert await merchants(client, direction="in", category="Refund") == ["Refund"]
    assert await merchants(client, direction="out", category="Refund") == []
    assert await merchants(client, direction="out", max_amount=30000) == ["Warung"]


async def test_the_amount_is_always_positive_whichever_way_the_money_went(client):
    rows = (await client.get("/transactions")).json()
    assert all(Decimal(r["amount"]) > 0 for r in rows)


async def test_an_unknown_direction_is_explained_in_plain_words(client):
    response = await client.get("/transactions", params={"direction": "sideways"})
    assert response.status_code == 422
    assert response.json()["detail"] == "Type: choose Money out or Money in"


async def test_todays_list_includes_both_directions(session_factory, authed_client):
    async with session_factory() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                Transaction(
                    merchant="Spent",
                    amount=Decimal("10"),
                    direction="out",
                    status="confirmed",
                    confirmed_at=now,
                ),
                Transaction(
                    merchant="Received",
                    amount=Decimal("20"),
                    direction="in",
                    status="confirmed",
                    confirmed_at=now,
                ),
            ]
        )
        await session.commit()
    rows = (await authed_client.get("/transactions/today")).json()
    assert {r["merchant"]: r["direction"] for r in rows} == {
        "Spent": "out",
        "Received": "in",
    }


async def test_existing_transactions_without_a_direction_default_to_money_out(
    session_factory, authed_client
):
    async with session_factory() as session:
        session.add(
            Transaction(
                merchant="Old receipt",
                amount=Decimal("10"),
                status="confirmed",
                confirmed_at=at(5, 9),
            )
        )
        await session.commit()
    (row,) = (await authed_client.get("/transactions")).json()
    assert row["direction"] == "out"


async def test_the_database_itself_refuses_any_other_direction(session_factory):
    from sqlalchemy.exc import IntegrityError

    # Three characters fit the column, so only the check constraint can refuse it.
    async with session_factory() as session:
        session.add(Transaction(merchant="Odd", amount=Decimal("1"), direction="xyz"))
        with pytest.raises(IntegrityError):
            await session.commit()
