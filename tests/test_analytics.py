"""Boundary: the dashboard adds up confirmed money in and out, never transfers."""

from datetime import date
from decimal import Decimal

import pytest

from pfa.models import Transaction
from pfa.repository.finance import CategoryRepository
from pfa.schemas.analytics import Period
from pfa.services.analytics import build_analytics

OCT = date(2026, 10, 9)


async def add(
    session_factory,
    rows: list[tuple],
) -> None:
    """Adds (amount, day, category, direction, status[, is_transfer]) rows."""
    async with session_factory() as session:
        repo = CategoryRepository(session)
        ids = {}
        for _, _, category, *_ in rows:
            if category and category not in ids:
                ids[category] = await repo.get_id_by_name(category)
        session.add_all(
            Transaction(
                merchant=f"{category or 'Nothing'} {i}",
                amount=Decimal(amount),
                occurred_on=date.fromisoformat(day),
                category_id=ids.get(category),
                direction=direction,
                status=status,
                is_transfer=bool(flag),
            )
            for i, (amount, day, category, direction, status, *flag) in enumerate(rows)
        )
        await session.commit()


@pytest.fixture
async def seeded(session_factory):
    """October 2026 and the September before it."""
    await add(
        session_factory,
        [
            # October, money out
            ("100.00", "2026-10-01", "Groceries", "out", "confirmed"),
            ("50.00", "2026-10-01", "Groceries", "out", "confirmed"),
            ("200.00", "2026-10-05", "Dining", "out", "confirmed"),
            ("25.00", "2026-10-31", None, "out", "confirmed"),  # no category
            # October, money in
            ("1000.00", "2026-10-02", "Salary", "in", "confirmed"),
            # October, moves between the user's own accounts: never counted
            ("500.00", "2026-10-03", "Transfer", "out", "confirmed", True),
            ("500.00", "2026-10-03", "Transfer", "in", "confirmed", True),
            # October, not confirmed: never counted
            ("999.00", "2026-10-04", "Groceries", "out", "pending"),
            # September, the period before
            ("80.00", "2026-09-30", "Groceries", "out", "confirmed"),
            ("800.00", "2026-09-15", "Salary", "in", "confirmed"),
        ],
    )


async def analytics(session_factory, period=Period.MONTH, anchor=OCT):
    async with session_factory() as session:
        return await build_analytics(session, period, anchor)


async def test_money_out_and_money_in_are_added_up_apart(session_factory, seeded):
    result = await analytics(session_factory)
    assert (result.money_out.total, result.money_out.count) == (Decimal("375.00"), 4)
    assert (result.money_in.total, result.money_in.count) == (Decimal("1000.00"), 1)
    assert result.net == Decimal("625.00")  # money in minus money out


async def test_moves_between_own_accounts_are_counted_on_their_own_only(
    session_factory, seeded
):
    result = await analytics(session_factory)
    assert (result.transfers.total, result.transfers.count) == (Decimal("1000.00"), 2)
    # Neither side of a transfer shows up in spending, income, or any category list.
    assert all(c.category != "Transfer" for c in result.out_by_category)
    assert all(c.category != "Transfer" for c in result.in_by_category)
    assert result.money_out.count == 4 and result.money_in.count == 1


async def test_a_flagged_transaction_keeps_its_category_but_is_not_counted(
    session_factory,
):
    await add(
        session_factory, [("40.00", "2026-10-02", "Savings", "out", "confirmed", True)]
    )
    result = await analytics(session_factory)
    assert result.money_out.total == Decimal("0.00")
    assert result.transfers.total == Decimal("40.00")
    assert result.out_by_category == []  # its category is not listed as spending


async def test_the_transfer_category_alone_does_not_make_it_a_transfer(
    session_factory,
):
    # The flag is the only rule: a transaction labelled Transfer but not flagged is
    # counted like any other, e.g. a payment to a person someone filed there.
    await add(
        session_factory, [("40.00", "2026-10-02", "Transfer", "out", "confirmed")]
    )
    result = await analytics(session_factory)
    assert result.money_out.total == Decimal("40.00")
    assert result.transfers.count == 0


async def test_unconfirmed_transactions_are_ignored(session_factory, seeded):
    result = await analytics(session_factory)
    assert Decimal("999.00") not in {c.total for c in result.out_by_category}
    assert result.money_out.total == Decimal("375.00")


async def test_categories_are_ordered_by_size_with_shares_of_their_own_side(
    session_factory, seeded
):
    result = await analytics(session_factory)
    assert [c.category for c in result.out_by_category] == [
        "Dining",
        "Groceries",
        "Uncategorised",
    ]
    dining, groceries, uncategorised = result.out_by_category
    assert (dining.total, dining.count) == (Decimal("200.00"), 1)
    assert (groceries.total, groceries.count) == (Decimal("150.00"), 2)
    assert uncategorised.total == Decimal("25.00")
    assert dining.share == pytest.approx(200 / 375, abs=1e-4)
    assert sum(c.share for c in result.out_by_category) == pytest.approx(1.0, abs=1e-3)
    (salary,) = result.in_by_category
    assert (salary.category, salary.share) == ("Salary", 1.0)  # shares are per side


async def test_the_chart_has_a_bar_for_every_day_even_empty_ones(
    session_factory, seeded
):
    result = await analytics(session_factory)
    assert result.bucket == "day"
    assert len(result.series) == 31
    by_day = {p.start: p for p in result.series}
    assert by_day[date(2026, 10, 1)].money_out == Decimal("150.00")
    assert by_day[date(2026, 10, 2)].money_in == Decimal("1000.00")
    assert by_day[date(2026, 10, 3)].money_out == Decimal("0.00")  # transfer excluded
    assert by_day[date(2026, 10, 3)].money_in == Decimal("0.00")
    assert by_day[date(2026, 10, 4)].money_out == Decimal("0.00")  # pending excluded
    assert by_day[date(2026, 10, 31)].money_out == Decimal("25.00")
    assert sum(p.money_out for p in result.series) == result.money_out.total


async def test_the_previous_period_and_the_change_against_it(session_factory, seeded):
    previous = (await analytics(session_factory)).previous
    assert (previous.start, previous.end) == (date(2026, 9, 1), date(2026, 9, 30))
    assert (previous.money_out, previous.money_in) == (
        Decimal("80.00"),
        Decimal("800.00"),
    )
    assert previous.money_out_change == pytest.approx((375 - 80) / 80, abs=1e-4)
    assert previous.money_in_change == pytest.approx(0.25)


async def test_a_period_with_nothing_in_it_is_all_zeros_and_has_no_change(
    session_factory,
):
    result = await analytics(session_factory)
    assert result.money_out.total == result.money_in.total == Decimal("0.00")
    assert result.net == Decimal("0.00")
    assert result.out_by_category == [] and result.in_by_category == []
    assert result.transfers.count == 0
    assert result.previous.money_out_change is None
    assert result.previous.money_in_change is None
    assert len(result.series) == 31  # the chart is still drawn, flat


async def test_a_week_runs_monday_to_sunday(session_factory):
    await add(
        session_factory,
        [
            ("10.00", "2026-10-04", "Groceries", "out", "confirmed"),  # Sunday before
            ("20.00", "2026-10-05", "Groceries", "out", "confirmed"),  # Monday
            ("30.00", "2026-10-11", "Groceries", "out", "confirmed"),  # Sunday
            ("40.00", "2026-10-12", "Groceries", "out", "confirmed"),  # Monday after
        ],
    )
    result = await analytics(session_factory, Period.WEEK, date(2026, 10, 8))
    assert (result.start, result.end) == (date(2026, 10, 5), date(2026, 10, 11))
    assert result.money_out.total == Decimal("50.00")  # only the 5th and the 11th
    assert len(result.series) == 7
    assert result.previous.money_out == Decimal("10.00")  # the week of Sep 28 - Oct 4


async def test_a_single_day_has_no_chart(session_factory, seeded):
    result = await analytics(session_factory, Period.DAY, date(2026, 10, 1))
    assert result.bucket is None and result.series == []
    assert result.money_out.total == Decimal("150.00")
    # The day before is 30 September, which has the 80.00 line from the seed data.
    assert (result.previous.start, result.previous.end) == (date(2026, 9, 30),) * 2
    assert result.previous.money_out == Decimal("80.00")
    assert result.previous.money_out_change == pytest.approx((150 - 80) / 80)


async def test_a_quarter_is_charted_by_week_and_compared_with_the_last_quarter(
    session_factory, seeded
):
    result = await analytics(session_factory, Period.QUARTER, OCT)
    assert (result.start, result.end) == (date(2026, 10, 1), date(2026, 12, 31))
    assert result.bucket == "week"
    assert result.money_out.total == Decimal("375.00")
    assert result.series[0].start == date(2026, 9, 28)  # Monday of the first week
    assert sum(p.money_out for p in result.series) == Decimal("375.00")
    assert result.previous.money_out == Decimal("80.00")  # Q3: the 30 Sep line
    assert result.previous.money_in == Decimal("800.00")


async def test_a_year_is_charted_by_month(session_factory, seeded):
    result = await analytics(session_factory, Period.YEAR, OCT)
    assert result.bucket == "month"
    assert [p.start for p in result.series] == [date(2026, m, 1) for m in range(1, 13)]
    by_month = {p.start.month: p for p in result.series}
    assert by_month[10].money_out == Decimal("375.00")
    assert by_month[9].money_out == Decimal("80.00")
    assert by_month[9].money_in == Decimal("800.00")
    assert result.money_out.total == Decimal("455.00")  # September and October


async def test_amounts_are_added_exactly(session_factory):
    await add(
        session_factory,
        [
            ("0.10", "2026-10-02", "Groceries", "out", "confirmed"),
            ("0.20", "2026-10-02", "Groceries", "out", "confirmed"),
        ],
    )
    result = await analytics(session_factory)
    assert result.money_out.total == Decimal(
        "0.30"
    )  # floats would give 0.30000000000000004


async def test_flagging_a_transaction_moves_it_out_of_spending(session_factory, seeded):
    from sqlalchemy import select

    async with session_factory() as session:
        dining = await session.scalar(
            select(Transaction.id).where(Transaction.merchant.like("Dining%"))
        )
    from pfa.services.transactions import change_transactions

    async with session_factory() as session:
        await change_transactions(session, [dining], is_transfer=True)
    result = await analytics(session_factory)
    assert result.money_out.total == Decimal("175.00")  # 375 minus the 200
    assert result.transfers.total == Decimal("1200.00")
    assert result.transfers.count == 3


# --- the API ---


async def test_the_endpoint_returns_the_dashboard(authed_client, seeded):
    response = await authed_client.get(
        "/analytics", params={"period": "month", "date": "2026-10-09"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "month"
    assert (body["start"], body["end"]) == ("2026-10-01", "2026-10-31")
    assert Decimal(body["money_out"]["total"]) == Decimal("375.00")
    assert Decimal(body["money_in"]["total"]) == Decimal("1000.00")
    assert Decimal(body["net"]) == Decimal("625.00")
    assert Decimal(body["transfers"]["total"]) == Decimal("1000.00")
    assert body["out_by_category"][0]["category"] == "Dining"
    assert body["previous"]["money_in_change"] == pytest.approx(0.25)


async def test_the_endpoint_defaults_to_this_month(authed_client):
    response = await authed_client.get("/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "month"
    start = date.fromisoformat(body["start"])
    end = date.fromisoformat(body["end"])
    assert start.day == 1 and (end - start).days in (27, 28, 29, 30)


@pytest.mark.parametrize("period", ["day", "week", "month", "quarter", "year"])
async def test_every_period_is_accepted(authed_client, period):
    assert (
        await authed_client.get("/analytics", params={"period": period})
    ).status_code == 200


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"period": "decade"}, "Period: choose day, week, month, quarter or year"),
        ({"date": "5 Oct"}, "Date: use the format YYYY-MM-DD"),
        ({"date": "1960-01-01"}, "Date: use the format YYYY-MM-DD"),
        ({"date": "2101-01-01"}, "Date: use the format YYYY-MM-DD"),
        ({"date": "2026-02-30"}, "Date: use the format YYYY-MM-DD"),
    ],
)
async def test_bad_requests_are_explained_in_plain_words(
    authed_client, params, expected
):
    response = await authed_client.get("/analytics", params=params)
    assert response.status_code == 422
    assert expected in response.json()["detail"]


@pytest.mark.parametrize("anchor", ["1970-01-01", "2100-12-31"])
async def test_the_edges_of_the_allowed_dates_work_for_every_period(
    authed_client, anchor
):
    for period in ("day", "week", "month", "quarter", "year"):
        response = await authed_client.get(
            "/analytics", params={"period": period, "date": anchor}
        )
        assert response.status_code == 200, (period, anchor, response.text)


async def test_the_dashboard_needs_a_session(anon_client):
    assert (await anon_client.get("/analytics")).status_code == 401
