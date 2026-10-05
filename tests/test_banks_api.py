"""Boundary: banks and cards can be created and listed through the API."""

import pytest


@pytest.fixture
def client(authed_client):
    return authed_client


async def test_create_and_list_bank_with_card(client):
    bank = (await client.post("/banks", json={"name": "BCA"})).json()
    card = await client.post(
        f"/banks/{bank['id']}/cards", json={"name": "Visa", "last4": "1234"}
    )
    assert card.status_code == 201
    assert card.json()["last4"] == "1234"
    assert [b["name"] for b in (await client.get("/banks")).json()] == ["BCA"]
    assert len((await client.get("/cards")).json()) == 1


async def test_duplicate_bank_is_conflict(client):
    await client.post("/banks", json={"name": "BCA"})
    again = await client.post("/banks", json={"name": "BCA"})
    assert again.status_code == 409


async def test_card_for_unknown_bank_is_404(client):
    response = await client.post("/banks/999/cards", json={"name": "Visa"})
    assert response.status_code == 404


@pytest.mark.parametrize("last4", ["12", "12345", "abcd"])
async def test_bad_last4_is_rejected(client, last4):
    bank = (await client.post("/banks", json={"name": "BCA"})).json()
    response = await client.post(
        f"/banks/{bank['id']}/cards", json={"name": "Visa", "last4": last4}
    )
    assert response.status_code == 422


async def test_empty_bank_name_is_rejected(client):
    assert (await client.post("/banks", json={"name": ""})).status_code == 422
