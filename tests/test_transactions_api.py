"""Boundary: Today's transactions are the confirmed ones from today, newest first."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from pfa.models import Transaction, TransactionStatus
from pfa.repository.finance import (
    BankRepository,
    CardRepository,
    CategoryRepository,
)
from pfa.services.transactions import local_day_bounds, todays_transactions

JAKARTA = ZoneInfo("Asia/Jakarta")


def test_local_day_bounds_use_the_local_midnight():
    start, end = local_day_bounds(date(2026, 10, 5), JAKARTA)
    assert start == datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 5, 17, 0, tzinfo=UTC)


@pytest.fixture
async def seeded(session_factory):
    """One card plus transactions: today x2, yesterday, and a pending one."""
    now = datetime.now(UTC)
    async with session_factory() as session:
        bank = await BankRepository(session).add("BCA")
        card = await CardRepository(session).add(bank.id, "Visa", "1234")
        groceries = await CategoryRepository(session).get_id_by_name("Groceries")

        def make(merchant, status, confirmed_at, amount="10.00"):
            return Transaction(
                merchant=merchant,
                amount=Decimal(amount),
                occurred_on=date(2026, 1, 1),
                category_id=groceries,
                card_id=card.id,
                status=status.value,
                confirmed_at=confirmed_at,
            )

        confirmed, pending = TransactionStatus.CONFIRMED, TransactionStatus.PENDING
        session.add_all(
            [
                make("Older today", confirmed, now - timedelta(seconds=30)),
                make("Newest today", confirmed, now),
                make("Yesterday", confirmed, now - timedelta(days=2)),
                make("Not confirmed", pending, None),
            ]
        )
        await session.commit()
    return now


async def test_service_returns_only_todays_confirmed_newest_first(
    session_factory, seeded
):
    async with session_factory() as session:
        rows = await todays_transactions(session, "Asia/Jakarta", now=seeded)
    assert [r.merchant for r in rows] == ["Newest today", "Older today"]
    assert rows[0].card == "BCA Visa 1234"
    assert rows[0].category == "Groceries"


async def test_the_day_follows_the_users_timezone(session_factory, seeded):
    # The rows were confirmed "now". Thirty minutes into the NEXT local day they
    # are no longer today's, whatever today's date is when the test runs.
    local_today = seeded.astimezone(JAKARTA).date()
    next_midnight_utc = local_day_bounds(local_today, JAKARTA)[1]
    async with session_factory() as session:
        tomorrow = next_midnight_utc + timedelta(minutes=30)
        assert await todays_transactions(session, "Asia/Jakarta", now=tomorrow) == []
        today = await todays_transactions(session, "Asia/Jakarta", now=seeded)
    assert [r.merchant for r in today] == ["Newest today", "Older today"]


async def test_endpoint_returns_json(authed_client, seeded):
    response = await authed_client.get("/transactions/today")
    assert response.status_code == 200
    body = response.json()
    assert {row["merchant"] for row in body} <= {"Newest today", "Older today"}
    assert all(row["card"] == "BCA Visa 1234" for row in body)


async def test_no_transactions_gives_empty_list(session_factory):
    async with session_factory() as session:
        assert await todays_transactions(session, "UTC") == []
