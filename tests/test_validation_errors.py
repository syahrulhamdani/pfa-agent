"""Boundary: a rejected request says which field is wrong and how to fix it."""

import pytest

from pfa.api.errors import describe_validation_error


async def detail_of(client, method, path, **kwargs) -> dict:
    response = await client.request(method, path, **kwargs)
    assert response.status_code == 422, response.text
    body = response.json()
    assert isinstance(body["detail"], str)  # the page shows this to a person
    return body


@pytest.mark.parametrize("month", ["10/2026", "October", "2026-13", "2026-1", "26-10"])
async def test_a_bad_month_says_the_format_and_gives_an_example(authed_client, month):
    body = await detail_of(
        authed_client, "GET", "/transactions", params={"month": month}
    )
    assert body["detail"] == "Month: use the format YYYY-MM, for example 2026-10"


@pytest.mark.parametrize(("param", "label"), [("date_from", "From"), ("date_to", "To")])
async def test_a_bad_date_says_the_format_and_gives_an_example(
    authed_client, param, label
):
    body = await detail_of(
        authed_client, "GET", "/transactions", params={param: "5 Oct"}
    )
    assert (
        body["detail"] == f"{label}: use the format YYYY-MM-DD, for example 2026-10-05"
    )


@pytest.mark.parametrize(
    ("param", "value", "label"),
    [
        ("min_amount", "lots", "Min amount"),
        ("max_amount", "abc", "Max amount"),
        ("min_amount", "-5", "Min amount"),
    ],
)
async def test_a_bad_amount_explains_what_to_enter(authed_client, param, value, label):
    body = await detail_of(authed_client, "GET", "/transactions", params={param: value})
    assert body["detail"].startswith(f"{label}: enter a number")
    assert "25000" in body["detail"]


async def test_a_bad_date_field_names_the_choices(authed_client):
    body = await detail_of(authed_client, "GET", "/transactions", params={"basis": "x"})
    assert "Receipt date" in body["detail"]
    assert "Confirmed date" in body["detail"]


async def test_several_problems_are_listed_together_once_each(authed_client):
    params = {"month": "bad", "min_amount": "lots", "date_from": "nope"}
    body = await detail_of(authed_client, "GET", "/transactions", params=params)
    parts = body["detail"].split("; ")
    assert len(parts) == 3
    assert {p.split(":")[0] for p in parts} == {"Month", "Min amount", "From"}


async def test_the_structured_errors_are_still_available(authed_client):
    body = await detail_of(authed_client, "GET", "/transactions", params={"month": "x"})
    (error,) = body["errors"]
    assert error["loc"] == ["query", "month"]
    assert set(error) == {"loc", "msg", "type"}  # nothing that echoes input back


async def test_bank_and_card_forms_get_the_same_treatment(authed_client):
    empty = await detail_of(authed_client, "POST", "/banks", json={"name": ""})
    assert empty["detail"].startswith("Name: enter a name")

    bank = (await authed_client.post("/banks", json={"name": "BCA"})).json()
    card = await detail_of(
        authed_client,
        "POST",
        f"/banks/{bank['id']}/cards",
        json={"name": "Visa", "last4": "12"},
    )
    assert (
        card["detail"] == "Last 4 digits: enter exactly four digits, or leave it blank"
    )


async def test_an_empty_sign_in_token_points_to_login(anon_client):
    body = await detail_of(anon_client, "POST", "/auth/exchange", json={"token": ""})
    assert "/login" in body["detail"]


async def test_valid_requests_are_unaffected(authed_client):
    response = await authed_client.get(
        "/transactions", params={"month": "2026-10", "min_amount": "1000"}
    )
    assert response.status_code == 200


def test_unknown_fields_fall_back_to_the_validators_message():
    error = {"loc": ("query", "some_field"), "msg": "Input should be positive"}
    assert describe_validation_error(error) == "Some field: Input should be positive"


def test_an_error_without_a_location_still_reads_sensibly():
    assert describe_validation_error({"loc": (), "msg": "Field required"}) == (
        "Request: Field required"
    )


def test_an_invalid_list_item_is_reported_by_its_field_not_its_position():
    error = {"loc": ("body", "ids", 0), "msg": "Input should be a valid integer"}
    assert describe_validation_error(error) == (
        "Selection: choose between 1 and 500 transactions"
    )


def test_a_location_of_only_numbers_still_reads_sensibly():
    assert describe_validation_error({"loc": (0,), "msg": "Bad"}) == "Request: Bad"
