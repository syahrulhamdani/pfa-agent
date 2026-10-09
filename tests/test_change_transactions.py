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


async def patch(client, ids, category=None, direction=None, is_transfer=None):
    body = {"ids": ids}
    if is_transfer is not None:
        body["is_transfer"] = is_transfer
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
        ({"ids": [1]}, "Choose a category, a direction or a transfer flag"),
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


# --- transfers: a flag of its own, separate from the category ---


async def test_a_transaction_can_be_flagged_as_a_move_between_own_accounts(
    authed_client, seeded
):
    assert (await categories_of(authed_client))["A"][1] is False
    response = await patch(authed_client, [seeded["A"]], is_transfer=True)
    assert response.json() == {"updated": 1}
    now = await categories_of(authed_client)
    assert now["A"] == ("Groceries", True, "out")  # the category is kept
    assert now["B"][1] is False  # only the one that was flagged


async def test_unflagging_counts_it_again_and_keeps_the_category(authed_client, seeded):
    await patch(authed_client, [seeded["A"]], is_transfer=True)
    await patch(authed_client, [seeded["A"]], is_transfer=False)
    assert (await categories_of(authed_client))["A"] == ("Groceries", False, "out")


async def test_choosing_the_transfer_category_does_not_flag_anything(
    authed_client, seeded
):
    await patch(authed_client, [seeded["A"]], "Transfer")
    assert (await categories_of(authed_client))["A"] == ("Transfer", False, "out")


async def test_flag_and_category_can_change_in_one_request(authed_client, seeded):
    await patch(authed_client, [seeded["A"], seeded["B"]], "Dining", is_transfer=True)
    now = await categories_of(authed_client)
    assert now["A"] == ("Dining", True, "out")
    assert now["B"] == ("Dining", True, "out")
    assert now["C"] == ("Groceries", False, "in")  # untouched


async def test_a_flag_on_an_unsaved_transaction_is_refused(authed_client, seeded):
    response = await patch(authed_client, [seeded["Pending"]], is_transfer=True)
    assert response.status_code == 404


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
    await patch(authed_client, [seeded["A"], seeded["B"]], "Dining", "in")
    now = await categories_of(authed_client)
    assert now["A"] == ("Dining", False, "in")
    assert now["B"] == ("Dining", False, "in")
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
    await patch(authed_client, [seeded["A"]], direction="out", is_transfer=True)
    await patch(authed_client, [seeded["A"]], direction="in")
    assert (await categories_of(authed_client))["A"] == ("Groceries", True, "in")


async def test_the_direction_filter_follows_the_change(authed_client, seeded):
    await patch(authed_client, [seeded["A"]], direction="in")
    rows = (await authed_client.get("/transactions", params={"direction": "in"})).json()
    assert {r["merchant"] for r in rows} == {"A", "C"}


async def test_nothing_to_change_is_explained_in_plain_words(authed_client, seeded):
    response = await authed_client.patch("/transactions", json={"ids": [seeded["A"]]})
    assert response.status_code == 422
    assert (
        response.json()["detail"] == "Choose a category, a direction or a transfer flag"
    )


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
