"""Boundary: savings goals, with progress as saved amount over target amount.

What is tested: creating, reading, changing and deleting goals through the API, the
progress arithmetic (including a goal that is passed or whose date has gone), and
input that must be refused.
"""

from datetime import date
from decimal import Decimal

import pytest

from pfa.models import Goal
from pfa.services.goals import goal_read

TODAY = date(2026, 10, 9)


def goal(saved="0", target="1000", on=date(2026, 12, 31)):
    return Goal(
        id=1,
        name="Trip",
        target_amount=Decimal(target),
        target_date=on,
        saved_amount=Decimal(saved),
    )


# --- progress arithmetic ---


@pytest.mark.parametrize(
    ("saved", "target", "progress", "remaining"),
    [
        ("0", "1000", 0.0, "1000.00"),
        ("250", "1000", 0.25, "750.00"),
        ("1000", "1000", 1.0, "0.00"),
        ("1500", "1000", 1.5, "0.00"),  # passed the goal: remaining never negative
        ("1", "3", 0.3333, "2.00"),
    ],
)
def test_progress_is_saved_over_target(saved, target, progress, remaining):
    read = goal_read(goal(saved, target), TODAY)
    assert read.progress == pytest.approx(progress)
    assert read.remaining == Decimal(remaining)


@pytest.mark.parametrize(
    ("on", "days"),
    [
        (date(2026, 10, 9), 0),
        (date(2026, 10, 10), 1),
        (date(2027, 10, 9), 365),
        (date(2026, 10, 8), -1),  # the date has passed
    ],
)
def test_days_left_counts_from_today(on, days):
    assert goal_read(goal(on=on), TODAY).days_left == days


# --- the API ---

NEW = {
    "name": "Trip to Japan",
    "target_amount": "25000000",
    "target_date": "2027-06-30",
}


async def test_a_created_goal_starts_with_nothing_saved(authed_client):
    response = await authed_client.post("/goals", json=NEW)
    assert response.status_code == 201
    body = response.json()
    assert body["saved_amount"] == "0.00"
    assert body["progress"] == 0.0
    assert body["target_amount"] == "25000000.00"


async def test_a_goal_can_start_with_an_amount_already_saved(authed_client):
    response = await authed_client.post(
        "/goals", json={**NEW, "saved_amount": "5000000"}
    )
    assert response.json()["progress"] == pytest.approx(0.2)


async def test_goals_are_listed_nearest_date_first(authed_client):
    await authed_client.post("/goals", json={**NEW, "name": "Later"})
    await authed_client.post(
        "/goals", json={**NEW, "name": "Sooner", "target_date": "2026-12-01"}
    )
    names = [g["name"] for g in (await authed_client.get("/goals")).json()]
    assert names == ["Sooner", "Later"]


async def test_the_saved_amount_can_be_updated(authed_client):
    created = (await authed_client.post("/goals", json=NEW)).json()
    response = await authed_client.patch(
        f"/goals/{created['id']}", json={"saved_amount": "10000000"}
    )
    assert response.status_code == 200
    assert response.json()["progress"] == pytest.approx(0.4)
    assert response.json()["name"] == "Trip to Japan"  # untouched


async def test_a_goal_can_be_renamed_and_retargeted(authed_client):
    created = (await authed_client.post("/goals", json=NEW)).json()
    response = await authed_client.patch(
        f"/goals/{created['id']}",
        json={
            "name": "  Japan  ",
            "target_amount": "20000000",
            "target_date": "2027-01-01",
        },
    )
    body = response.json()
    assert (body["name"], body["target_amount"], body["target_date"]) == (
        "Japan",
        "20000000.00",
        "2027-01-01",
    )


async def test_saving_zero_is_allowed_to_reset_progress(authed_client):
    created = (
        await authed_client.post("/goals", json={**NEW, "saved_amount": "5"})
    ).json()
    response = await authed_client.patch(
        f"/goals/{created['id']}", json={"saved_amount": "0"}
    )
    assert response.json()["saved_amount"] == "0.00"


async def test_a_goal_can_be_deleted(authed_client):
    created = (await authed_client.post("/goals", json=NEW)).json()
    assert (await authed_client.delete(f"/goals/{created['id']}")).status_code == 204
    assert (await authed_client.get("/goals")).json() == []


async def test_a_missing_goal_is_a_plain_404(authed_client):
    assert (
        await authed_client.patch("/goals/999", json={"name": "x"})
    ).status_code == 404
    assert (await authed_client.delete("/goals/999")).status_code == 404


@pytest.mark.parametrize(
    ("change", "mentions"),
    [
        ({"name": ""}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "x" * 101}, "name"),
        ({"target_amount": "0"}, "Target amount"),
        ({"target_amount": "-1"}, "Target amount"),
        ({"target_amount": "1.234"}, "Target amount"),
        ({"target_amount": "NaN"}, "Target amount"),
        ({"saved_amount": "-1"}, "Saved amount"),
        ({"saved_amount": "1.234"}, "Saved amount"),
        ({"target_date": "30/06/2027"}, "Target date"),
        ({"target_date": "2027-02-30"}, "Target date"),
        ({"target_date": "2101-01-01"}, "Target date"),
        ({"target_date": "1969-12-31"}, "Target date"),
    ],
)
async def test_bad_goals_are_explained(authed_client, change, mentions):
    response = await authed_client.post("/goals", json={**NEW, **change})
    assert response.status_code == 422
    assert mentions in response.json()["detail"]


async def test_an_update_that_changes_nothing_is_refused(authed_client):
    created = (await authed_client.post("/goals", json=NEW)).json()
    response = await authed_client.patch(f"/goals/{created['id']}", json={})
    assert response.status_code == 422


async def test_a_bad_update_leaves_the_goal_as_it_was(authed_client):
    created = (await authed_client.post("/goals", json=NEW)).json()
    bad = await authed_client.patch(
        f"/goals/{created['id']}", json={"name": "Fine", "saved_amount": "-5"}
    )
    assert bad.status_code == 422
    (still,) = (await authed_client.get("/goals")).json()
    assert still["name"] == "Trip to Japan"


async def test_goals_need_a_session(anon_client):
    assert (await anon_client.get("/goals")).status_code == 401
    assert (await anon_client.post("/goals", json=NEW)).status_code == 401
    assert (await anon_client.patch("/goals/1", json={"name": "x"})).status_code == 401
    assert (await anon_client.delete("/goals/1")).status_code == 401
