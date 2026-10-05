"""Boundary: filters narrow confirmed transactions; bad filter combinations are 422."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from pfa.models import Transaction
from pfa.repository.finance import CategoryRepository


def at(day: int, hour: int, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


@pytest.fixture
async def client(session_factory, authed_client):
    """API client over a database holding four transactions (UTC timezone).

    A Indomaret  Groceries 45000  receipt Oct 4   confirmed Oct 5 10:00
    B Warung     Dining    25000  receipt Sep 30  confirmed Oct 5 11:00
    C Gojek      Transport 15000  receipt Oct 1   confirmed Oct 2 09:00
    D Hidden     Dining    99999  pending, never listed
    """
    async with session_factory() as session:
        ids = {
            name: await CategoryRepository(session).get_id_by_name(name)
            for name in ("Groceries", "Dining", "Transport")
        }

        def make(merchant, category, amount, occurred, confirmed, status="confirmed"):
            return Transaction(
                merchant=merchant,
                category_id=ids[category],
                amount=Decimal(amount),
                occurred_on=occurred,
                status=status,
                confirmed_at=confirmed,
            )

        session.add_all(
            [
                make("Indomaret", "Groceries", "45000", date(2026, 10, 4), at(5, 10)),
                make("Warung", "Dining", "25000", date(2026, 9, 30), at(5, 11)),
                make("Gojek", "Transport", "15000", date(2026, 10, 1), at(2, 9)),
                make("Hidden", "Dining", "99999", date(2026, 10, 4), None, "pending"),
            ]
        )
        await session.commit()
    yield authed_client


async def merchants(client, **params) -> list[str]:
    response = await client.get("/transactions", params=params)
    assert response.status_code == 200, response.text
    return [row["merchant"] for row in response.json()]


async def test_no_filters_lists_all_confirmed_newest_first(client):
    assert await merchants(client) == ["Warung", "Indomaret", "Gojek"]


async def test_receipt_date_range(client):
    result = await merchants(client, date_from="2026-10-01", date_to="2026-10-03")
    assert result == ["Gojek"]  # receipt dates Oct 1 to 3


async def test_confirmed_date_range(client):
    result = await merchants(
        client, basis="confirmed", date_from="2026-10-05", date_to="2026-10-05"
    )
    assert result == ["Warung", "Indomaret"]  # confirmed on Oct 5


async def test_same_dates_differ_by_basis(client):
    by_receipt = await merchants(client, date_from="2026-10-05", date_to="2026-10-05")
    by_confirmed = await merchants(
        client, basis="confirmed", date_from="2026-10-05", date_to="2026-10-05"
    )
    assert by_receipt == []
    assert len(by_confirmed) == 2


async def test_range_ends_are_inclusive(client):
    result = await merchants(
        client, basis="confirmed", date_from="2026-10-02", date_to="2026-10-02"
    )
    assert result == ["Gojek"]


async def test_open_ended_ranges(client):
    assert await merchants(client, date_from="2026-10-01") == ["Indomaret", "Gojek"]
    assert await merchants(client, date_to="2026-09-30") == ["Warung"]


async def test_month_filter_by_receipt_date(client):
    assert await merchants(client, month="2026-10") == ["Indomaret", "Gojek"]
    assert await merchants(client, month="2026-09") == ["Warung"]


async def test_month_filter_by_confirmed_date(client):
    result = await merchants(client, basis="confirmed", month="2026-10")
    assert result == ["Warung", "Indomaret", "Gojek"]


async def test_amount_range_is_inclusive(client):
    assert await merchants(client, min_amount=25000) == ["Warung", "Indomaret"]
    assert await merchants(client, max_amount=25000) == ["Warung", "Gojek"]
    assert await merchants(client, min_amount=15000, max_amount=25000) == [
        "Warung",
        "Gojek",
    ]


async def test_one_or_several_categories(client):
    assert await merchants(client, category="Dining") == ["Warung"]
    result = await merchants(client, category=["Dining", "Transport"])
    assert result == ["Warung", "Gojek"]


async def test_filters_combine(client):
    result = await merchants(
        client, month="2026-10", min_amount=20000, category=["Groceries", "Dining"]
    )
    assert result == ["Indomaret"]


async def test_no_match_gives_empty_list(client):
    assert await merchants(client, category="Dining", min_amount=99999) == []


async def test_pending_is_never_listed(client):
    assert "Hidden" not in await merchants(client, category="Dining")


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-10-05", "date_to": "2026-10-01"},
        {"min_amount": 10, "max_amount": 5},
        {"min_amount": -1},
        {"month": "2026-13"},
        {"month": "October"},
        {"month": "2026-10", "date_from": "2026-10-01"},
        {"basis": "nonsense"},
        {"date_from": "not-a-date"},
    ],
)
async def test_invalid_filters_are_rejected(client, params):
    response = await client.get("/transactions", params=params)
    assert response.status_code == 422


async def test_categories_endpoint_lists_names(client):
    response = await client.get("/categories")
    assert response.status_code == 200
    assert {"Groceries", "Dining", "Transport", "Other"} <= set(response.json())
