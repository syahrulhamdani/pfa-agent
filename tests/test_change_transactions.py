"""Boundary: saved transactions can change category and direction, all or nothing."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from pfa.models import Transaction
from pfa.repository.finance import CategoryRepository

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@pytest.fixture
async def seeded(session_factory):
    """Three saved transactions and one still pending, all in Groceries."""
    async with session_factory() as session:
        groceries = await CategoryRepository(session).get_id_by_name("Groceries")

        def make(merchant, status="confirmed", direction="out"):
            return Transaction(
                merchant=merchant,
                category_id=groceries,
                amount=Decimal("100"),
                occurred_on=date(2026, 10, 1),
                direction=direction,
                status=status,
                confirmed_at=NOW if status == "confirmed" else None,
            )

        rows = [
            make("A"),
            make("B"),
            make("C", direction="in"),
            make("Pending", "pending"),
        ]
        session.add_all(rows)
        await session.commit()
        return {r.merchant: r.id for r in rows}


async def categories_of(client) -> dict[str, tuple[str, bool, str]]:
    rows = (await client.get("/transactions")).json()
    return {
        r["merchant"]: (r["category"], r["is_transfer"], r["direction"]) for r in rows
    }


async def patch(client, ids, category=None, direction=None):
    body = {"ids": ids}
    if category is not None:
        body["category"] = category
    if direction is not None:
        body["direction"] = direction
    return await client.patch("/transactions", json=body)


async def test_one_transaction_can_be_moved_to_another_category(authed_client, seeded):
    response = await patch(authed_client, [seeded["A"]], "Dining")
    assert response.status_code == 200
    assert response.json() == {"updated": 1}
    now = await categories_of(authed_client)
    assert now["A"][0] == "Dining"
    assert now["B"][0] == "Groceries"  # the others are untouched


async def test_several_transactions_move_together_and_duplicates_count_once(
    authed_client, seeded
):
    ids = [seeded["A"], seeded["B"], seeded["A"]]
    response = await patch(authed_client, ids, "Transport")
    assert response.json() == {"updated": 2}
    now = await categories_of(authed_client)
    assert now["A"][0] == now["B"][0] == "Transport"
    assert now["C"][0] == "Groceries"


async def test_the_category_name_is_matched_ignoring_case(authed_client, seeded):
    await patch(authed_client, [seeded["A"]], "  dINing ")
    assert (await categories_of(authed_client))["A"][0] == "Dining"


async def test_the_direction_is_never_changed_by_a_category_change(
    authed_client, seeded
):
    await patch(authed_client, [seeded["A"], seeded["C"]], "Refund")
    now = await categories_of(authed_client)
    assert (now["A"][2], now["C"][2]) == ("out", "in")


async def test_an_unknown_category_changes_nothing(authed_client, seeded):
    response = await patch(authed_client, [seeded["A"]], "Yachts")
    assert response.status_code == 404
    assert response.json()["detail"] == "There is no category called “Yachts”."
    assert (await categories_of(authed_client))["A"][0] == "Groceries"


async def test_one_unknown_id_means_nothing_is_changed(authed_client, seeded):
    response = await patch(authed_client, [seeded["A"], 987654], "Dining")
    assert response.status_code == 404
    assert "987654" in response.json()["detail"]
    assert (await categories_of(authed_client))["A"][0] == "Groceries"  # all or nothing


async def test_a_transaction_that_is_not_saved_yet_cannot_be_changed(
    authed_client, seeded, session_factory
):
    response = await patch(authed_client, [seeded["Pending"]], "Dining")
    assert response.status_code == 404
    async with session_factory() as session:
        pending = await session.get(Transaction, seeded["Pending"])
    assert pending.category_id == (await _category_id(session_factory, "Groceries"))


async def _category_id(session_factory, name):
    async with session_factory() as session:
        return await CategoryRepository(session).get_id_by_name(name)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"ids": [], "category": "Dining"}, "Selection: choose between 1 and 500"),
        (
            {"ids": list(range(1, 502)), "category": "Dining"},
            "Selection: choose between",
        ),
        ({"ids": [1]}, "Choose a category, a direction, or both"),
        ({"ids": [1], "category": ""}, "Category: choose a category from the list"),
        ({"ids": ["x"], "category": "Dining"}, "Selection:"),
    ],
)
async def test_a_malformed_request_is_explained(authed_client, body, expected):
    response = await authed_client.patch("/transactions", json=body)
    assert response.status_code == 422
    assert expected in response.json()["detail"]


async def test_changing_a_category_needs_a_session(anon_client):
    response = await anon_client.patch(
        "/transactions", json={"ids": [1], "category": "Dining"}
    )
    assert response.status_code == 401


# --- transfers: moving a transaction into or out of Transfer changes how it counts ---


async def test_a_transaction_in_transfer_is_flagged_as_a_move_between_own_accounts(
    authed_client, seeded
):
    assert (await categories_of(authed_client))["A"][1] is False
    await patch(authed_client, [seeded["A"]], "Transfer")
    now = await categories_of(authed_client)
    assert now["A"][1] is True
    assert now["B"][1] is False  # only the one that was moved


async def test_moving_it_back_out_of_transfer_counts_it_again(authed_client, seeded):
    await patch(authed_client, [seeded["A"]], "Transfer")
    await patch(authed_client, [seeded["A"]], "Dining")
    assert (await categories_of(authed_client))["A"][1] is False


async def test_the_transfer_flag_ignores_case_in_the_category_name(
    authed_client, seeded, session_factory
):
    from pfa.services.transactions import _to_read

    class Row:
        id, merchant, amount, description = 1, "X", Decimal("1"), None
        occurred_on, direction, confirmed_at = None, "out", None

    for name in ("Transfer", "transfer", "TRANSFER"):
        (read,) = _to_read([(Row, name, None)])
        assert read.is_transfer is True
    (other,) = _to_read([(Row, "Dining", None)])
    assert other.is_transfer is False
    (nothing,) = _to_read([(Row, None, None)])
    assert nothing.is_transfer is False


# --- changing the direction: money in or out, e.g. a move between pockets ---


async def amounts_of(client) -> dict[str, str]:
    return {
        r["merchant"]: r["amount"] for r in (await client.get("/transactions")).json()
    }


async def test_the_direction_alone_can_be_changed(authed_client, seeded):
    before = await amounts_of(authed_client)
    response = await patch(authed_client, [seeded["A"]], direction="in")
    assert response.status_code == 200
    assert response.json() == {"updated": 1}
    now = await categories_of(authed_client)
    assert now["A"] == ("Groceries", False, "in")  # the category is left alone
    assert (
        await amounts_of(authed_client) == before
    )  # amounts stay positive and as were


async def test_direction_and_category_can_change_together(authed_client, seeded):
    await patch(authed_client, [seeded["A"], seeded["B"]], "Transfer", "in")
    now = await categories_of(authed_client)
    assert now["A"] == ("Transfer", True, "in")
    assert now["B"] == ("Transfer", True, "in")
    assert now["C"] == ("Groceries", False, "in")  # untouched


async def test_several_directions_change_together(authed_client, seeded):
    response = await patch(
        authed_client, [seeded["A"], seeded["B"], seeded["A"]], direction="in"
    )
    assert response.json() == {"updated": 2}
    assert [d for _, _, d in (await categories_of(authed_client)).values()].count(
        "in"
    ) == 3


async def test_flipping_the_direction_of_a_transfer_keeps_it_a_transfer(
    authed_client, seeded
):
    await patch(authed_client, [seeded["A"]], "Transfer", "out")
    await patch(authed_client, [seeded["A"]], direction="in")
    assert (await categories_of(authed_client))["A"] == ("Transfer", True, "in")


async def test_the_direction_filter_follows_the_change(authed_client, seeded):
    await patch(authed_client, [seeded["A"]], direction="in")
    rows = (await authed_client.get("/transactions", params={"direction": "in"})).json()
    assert {r["merchant"] for r in rows} == {"A", "C"}


async def test_nothing_to_change_is_explained_in_plain_words(authed_client, seeded):
    response = await authed_client.patch("/transactions", json={"ids": [seeded["A"]]})
    assert response.status_code == 422
    assert response.json()["detail"] == "Choose a category, a direction, or both"


async def test_a_bad_direction_is_explained(authed_client, seeded):
    response = await patch(authed_client, [seeded["A"]], direction="sideways")
    assert response.status_code == 422
    assert response.json()["detail"] == "Type: choose Money out or Money in"


async def test_a_bad_category_stops_the_direction_change_too(authed_client, seeded):
    response = await patch(authed_client, [seeded["A"]], "Yachts", "in")
    assert response.status_code == 404
    assert (await categories_of(authed_client))["A"] == ("Groceries", False, "out")


async def test_an_unknown_id_stops_a_direction_change_for_all(authed_client, seeded):
    response = await patch(authed_client, [seeded["A"], 987654], direction="in")
    assert response.status_code == 404
    assert (await categories_of(authed_client))["A"][2] == "out"


async def test_a_transaction_not_saved_yet_cannot_change_direction(
    authed_client, seeded
):
    assert (
        await patch(authed_client, [seeded["Pending"]], direction="in")
    ).status_code == 404
