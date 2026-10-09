"""Boundary: moves between the user's own accounts can be listed on their own."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from pfa.models import Transaction
from pfa.repository.finance import CategoryRepository


@pytest.fixture
async def client(session_factory, authed_client):
    """Two counted rows and two flagged as moves between the user's own accounts.

    Indomaret (counted, Groceries)   Pay card (flagged, Transfer)
    Warung (counted, Dining)         Top up (flagged, Groceries: category kept)
    """
    async with session_factory() as session:
        ids = {
            name: await CategoryRepository(session).get_id_by_name(name)
            for name in ("Groceries", "Dining", "Transfer")
        }

        def make(merchant, category, flagged, hour):
            return Transaction(
                merchant=merchant,
                category_id=ids[category],
                amount=Decimal("1000"),
                occurred_on=date(2026, 10, 3),
                direction="out",
                is_transfer=flagged,
                status="confirmed",
                confirmed_at=datetime(2026, 10, 5, hour, tzinfo=UTC),
            )

        session.add_all(
            [
                make("Indomaret", "Groceries", False, 9),
                make("Warung", "Dining", False, 10),
                make("Pay card", "Transfer", True, 11),
                make("Top up", "Groceries", True, 12),
            ]
        )
        await session.commit()
    yield authed_client


async def merchants(client, **params) -> list[str]:
    response = await client.get("/transactions", params=params)
    assert response.status_code == 200, response.text
    return [row["merchant"] for row in response.json()]


async def test_without_the_filter_everything_is_listed(client):
    assert len(await merchants(client)) == 4


async def test_only_moves_between_own_accounts_can_be_listed(client):
    assert await merchants(client, is_transfer="true") == ["Top up", "Pay card"]


async def test_only_what_is_counted_can_be_listed(client):
    assert await merchants(client, is_transfer="false") == ["Warung", "Indomaret"]


async def test_the_filter_follows_the_flag_not_the_category(client):
    rows = await merchants(client, is_transfer="true", category="Groceries")
    assert rows == ["Top up"]  # flagged with a real category, and found by it


async def test_the_filter_combines_with_the_others(client):
    assert await merchants(client, is_transfer="true", min_amount="5000") == []


async def test_a_value_that_is_not_yes_or_no_is_refused(client):
    response = await client.get("/transactions", params={"is_transfer": "maybe"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Counting")
