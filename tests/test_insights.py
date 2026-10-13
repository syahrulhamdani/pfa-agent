"""Boundary: the facts pfa may quote, and the checks that keep its words to them.

What is tested: formatting, the figures gathered from a real database (money in and
out apart, transfers excluded, budgets, goals), the text a model is shown, the
template that stands in for a model, and the check that rejects invented figures.
"""

from datetime import date
from decimal import Decimal

import pytest

from pfa.models import Goal, Transaction
from pfa.repository.finance import CategoryRepository
from pfa.schemas.analytics import Period
from pfa.schemas.insights import BudgetLine
from pfa.services.budgets import set_budget
from pfa.services.insights import (
    budget_flags,
    budget_state,
    fallback_recommendations,
    fmt_money,
    fmt_percent,
    gather_facts,
    numbers_grounded,
    period_label,
    render_facts,
    ungrounded_numbers,
)

OCT = date(2026, 10, 1)
WED = date(2026, 10, 7)  # inside the week of Oct 5 - Oct 11
TODAY = date(2026, 10, 12)  # the Monday after


# --- formatting ---


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("1000"), "1,000"),
        (Decimal("1234.50"), "1,234.50"),
        (Decimal("0"), "0"),
        (Decimal("-46800.00"), "46,800"),  # the sign is said in words, not here
        (Decimal("0.005"), "0.01"),  # half up
        (Decimal("9000000"), "9,000,000"),
        (Decimal("999999999999.99"), "999,999,999,999.99"),
    ],
)
def test_amounts_are_formatted_for_reading(value, text):
    assert fmt_money(value) == text


@pytest.mark.parametrize(
    ("fraction", "text"), [(0.9347, "93%"), (-0.5, "50%"), (1.234, "123%"), (0, "0%")]
)
def test_percentages_are_whole_numbers(fraction, text):
    assert fmt_percent(fraction) == text


@pytest.mark.parametrize(
    ("period", "start", "end", "label"),
    [
        (
            Period.WEEK,
            date(2026, 10, 5),
            date(2026, 10, 11),
            "Week of Oct 5 – Oct 11, 2026",
        ),
        (
            Period.WEEK,
            date(2026, 12, 28),
            date(2027, 1, 3),
            "Week of Dec 28 – Jan 3, 2027",
        ),
        (Period.MONTH, date(2026, 10, 1), date(2026, 10, 31), "October 2026"),
        (Period.QUARTER, date(2026, 10, 1), date(2026, 12, 31), "Q4 2026"),
        (Period.YEAR, date(2026, 1, 1), date(2026, 12, 31), "2026"),
        (Period.DAY, date(2026, 10, 5), date(2026, 10, 5), "Oct 5, 2026"),
    ],
)
def test_periods_are_named_like_a_person_would(period, start, end, label):
    assert period_label(period, start, end) == label


@pytest.mark.parametrize(
    ("used", "state"),
    [(0, "ok"), (0.849, "ok"), (0.85, "near"), (1.0, "near"), (1.0001, "over")],
)
def test_budget_state_boundaries(used, state):
    assert budget_state(used) == state


def line(category, used, state=None, amount="1000"):
    amount = Decimal(amount)
    spent = amount * Decimal(str(used))
    return BudgetLine(
        category=category,
        amount=amount,
        spent=spent,
        remaining=amount - spent,
        used=used,
        state=state or budget_state(used),
    )


def test_by_default_nearly_used_and_over_budgets_are_flagged_most_used_first():
    flagged = budget_flags(
        [line("A", 0.5), line("B", 0.9), line("C", 1.4), line("D", 1.1), line("E", 0.2)]
    )
    assert [b.category for b in flagged] == ["C", "D", "B"]


def test_nothing_is_flagged_when_everything_is_on_track():
    assert budget_flags([line("A", 0.1), line("B", 0.84)]) == []
    assert budget_flags([]) == []


# --- gathering from a real database ---


async def seed(session_factory):
    async with session_factory() as session:
        ids = {
            name: await CategoryRepository(session).get_id_by_name(name)
            for name in ("Dining", "Groceries", "Salary", "Transfer", "Other")
        }
        rows = [
            # this week (Oct 5 - 11)
            ("Dining", "900", "2026-10-06", "out", False),
            ("Groceries", "150", "2026-10-07", "out", False),
            ("Groceries", "50", "2026-10-08", "out", False),
            ("Salary", "5000", "2026-10-09", "in", False),
            ("Transfer", "700", "2026-10-09", "out", True),  # a pocket top-up
            # the week before (Sep 28 - Oct 4)
            ("Dining", "400", "2026-09-30", "out", False),
        ]
        session.add_all(
            Transaction(
                merchant=f"{c} {i}",
                category_id=ids[c],
                amount=Decimal(a),
                occurred_on=date.fromisoformat(d),
                direction=direction,
                is_transfer=flag,
                status="confirmed",
            )
            for i, (c, a, d, direction, flag) in enumerate(rows)
        )
        session.add(
            Goal(
                name="Trip",
                target_amount=Decimal("1500"),
                target_date=date(2026, 10, 26),  # 14 days from the Monday
                saved_amount=Decimal("500"),
            )
        )
        await session.commit()
        await set_budget(session, "Dining", OCT, Decimal("1000"))
        await set_budget(session, "Groceries", OCT, Decimal("100"))
        await set_budget(session, "Other", OCT, Decimal("5000"))


async def facts(session_factory, **kwargs):
    async with session_factory() as session:
        return await gather_facts(session, Period.WEEK, WED, TODAY, **kwargs)


async def test_money_in_and_out_are_apart_and_transfers_are_left_out(session_factory):
    await seed(session_factory)
    f = await facts(session_factory)
    assert (f.money_out, f.out_count) == (Decimal("1100.00"), 3)
    assert (f.money_in, f.in_count) == (Decimal("5000.00"), 1)
    assert f.net == Decimal("3900.00")
    assert (f.transfers.total, f.transfers.count) == (Decimal("700.00"), 1)
    assert f.label == "Week of Oct 5 – Oct 11, 2026"


async def test_the_change_is_against_the_week_before(session_factory):
    await seed(session_factory)
    f = await facts(session_factory)
    assert f.money_out_change == pytest.approx((1100 - 400) / 400)
    assert f.money_in_change is None  # nothing came in the week before


async def test_top_categories_are_biggest_first_with_their_share(session_factory):
    await seed(session_factory)
    f = await facts(session_factory)
    assert [(c.category, c.total) for c in f.top_out] == [
        ("Dining", Decimal("900.00")),
        ("Groceries", Decimal("200.00")),
    ]
    assert f.top_out[0].share == pytest.approx(900 / 1100, abs=1e-3)
    assert "Transfer" not in [c.category for c in f.top_out]


async def test_a_category_asked_about_is_found_in_any_letter_case(session_factory):
    await seed(session_factory)
    f = await facts(session_factory, category="dINING")
    assert f.focus is not None and f.focus.total == Decimal("900.00")


async def test_a_category_with_no_spending_is_reported_as_such(session_factory):
    await seed(session_factory)
    f = await facts(session_factory, category="Transport")
    assert f.focus is None and f.focus_name == "Transport"
    assert "nothing spent" in render_facts(f)


async def test_budgets_are_for_the_month_of_the_period_end_by_default(session_factory):
    await seed(session_factory)
    f = await facts(session_factory)
    assert f.budget_month == OCT
    by_name = {b.category: b for b in f.budgets}
    assert by_name["Dining"].state == "near"  # 900 of 1000, with the 900 above
    assert by_name["Groceries"].state == "over"  # 200 of 100
    assert by_name["Other"].state == "ok"
    assert [b.category for b in f.flags] == ["Groceries", "Dining"]


async def test_a_goal_has_the_pace_it_needs(session_factory):
    await seed(session_factory)
    (goal,) = (await facts(session_factory)).goals
    assert goal.progress == pytest.approx(500 / 1500, abs=1e-3)
    assert goal.remaining == Decimal("1000.00")
    assert goal.days_left == 14
    assert goal.per_week_needed == Decimal("500.00")  # 1000 over two weeks


async def test_a_reached_or_late_goal_needs_no_pace(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                Goal(
                    name="Done",
                    target_amount=Decimal("100"),
                    target_date=date(2027, 1, 1),
                    saved_amount=Decimal("150"),
                ),
                Goal(
                    name="Late",
                    target_amount=Decimal("100"),
                    target_date=date(2026, 10, 1),
                    saved_amount=Decimal("10"),
                ),
            ]
        )
        await session.commit()
    goals = {g.name: g for g in (await facts(session_factory)).goals}
    assert goals["Done"].per_week_needed is None and goals["Done"].progress > 1
    assert goals["Late"].per_week_needed is None and goals["Late"].days_left < 0


async def test_an_empty_week_has_no_activity(session_factory):
    f = await facts(session_factory)
    assert not f.has_activity
    assert f.money_out == Decimal("0.00") and f.top_out == []


# --- the text a model is shown ---


async def test_the_rendered_facts_hold_every_figure(session_factory):
    await seed(session_factory)
    text = render_facts(await facts(session_factory))
    for expected in (
        "Week of Oct 5 – Oct 11, 2026",
        "Money out: 1,100 in 3 transactions",
        "Money in: 5,000 in 1 transactions",
        "Net (money in minus money out): 3,900",
        "not counted as spending or income: 1 totalling 700",
        "Dining 900",
        "Groceries is over budget by 100",
        "Trip saved 500 of 1,500 (33%), 14 days left, needs about 500 per week",
    ):
        assert expected in text, expected


async def test_an_empty_facts_text_says_so_without_inventing_lines(session_factory):
    text = render_facts(await facts(session_factory))
    assert "Moves between" not in text and "Top spending" not in text
    assert "No budgets are set for October 2026" in text
    assert "No savings goals are set" in text


async def test_a_running_period_is_marked(session_factory):
    f = await facts(session_factory, partial=True)
    assert "still running" in render_facts(f)


async def test_a_negative_net_is_written_with_a_minus(session_factory):
    async with session_factory() as session:
        dining = await CategoryRepository(session).get_id_by_name("Dining")
        session.add(
            Transaction(
                merchant="x",
                category_id=dining,
                amount=Decimal("300"),
                occurred_on=WED,
                direction="out",
                status="confirmed",
            )
        )
        await session.commit()
    assert "Net (money in minus money out): -300" in render_facts(
        await facts(session_factory)
    )


# --- keeping a model to the facts ---

FACTS = "Money out: 1,100 in 3 transactions; 175% more than the previous week"


@pytest.mark.parametrize(
    "text",
    [
        "You spent 1,100 this week.",
        "You spent 1100 this week.",  # no separator
        "You spent 1,100.00 this week.",  # with cents
        "That was 175% more than the week before.",
        "Across 3 transactions.",
        "No figures at all, just advice.",
        "1. Watch dining.\n2. Save more.",  # list numbering is not a figure
        "- Spent 1,100\n- Across 3 transactions",
    ],
)
def test_figures_that_are_in_the_facts_pass(text):
    assert numbers_grounded(text, FACTS)


@pytest.mark.parametrize(
    ("text", "invented"),
    [
        ("You spent 1,200 this week.", {Decimal("1200")}),
        ("That is 5 transactions a day.", {Decimal("5")}),
        ("Up 80% on last week.", {Decimal("80")}),
        ("You spent 1,100 over 7 days.", {Decimal("7")}),
        ("Total of 2,200 (1,100 twice).", {Decimal("2200")}),  # a figure it computed
        ("Save 0.5 more.", {Decimal("0.5")}),
    ],
)
def test_a_figure_that_is_not_in_the_facts_is_caught(text, invented):
    assert not numbers_grounded(text, FACTS)
    assert ungrounded_numbers(text, FACTS) == invented


# --- the same advice without a model ---


async def test_the_fallback_names_overspending_first(session_factory):
    await seed(session_factory)
    f = await facts(session_factory)
    lines = fallback_recommendations(f)
    assert lines[0].startswith("Groceries is over its budget by 100")
    assert len(lines) <= 4


async def test_every_fallback_line_only_quotes_the_facts(session_factory):
    await seed(session_factory)
    f = await facts(session_factory)
    for text in fallback_recommendations(f):
        assert numbers_grounded(text, render_facts(f)), text


async def test_the_fallback_for_an_empty_week_invites_a_receipt(session_factory):
    (only,) = fallback_recommendations(await facts(session_factory))
    assert "Nothing was recorded" in only


async def test_the_fallback_mentions_the_goal_pace(session_factory):
    await seed(session_factory)
    lines = fallback_recommendations(await facts(session_factory))
    assert any("Trip" in text and "500 a week" in text for text in lines)


# --- an empty period never gets an invented trend ---


async def test_an_empty_week_with_budgets_and_goals_still_says_nothing_was_recorded(
    session_factory,
):
    async with session_factory() as session:
        session.add(
            Goal(
                name="Trip",
                target_amount=Decimal("1500"),
                target_date=date(2026, 10, 26),
                saved_amount=Decimal("500"),
            )
        )
        await session.commit()
        await set_budget(session, "Dining", OCT, Decimal("1000"))
    f = await facts(session_factory)
    assert not f.has_activity and f.budgets and f.goals
    lines = fallback_recommendations(f)
    assert lines[0].startswith("Nothing was recorded in this period")
    assert any("Trip" in text for text in lines)  # the goal pace still helps


async def test_nothing_notable_is_not_called_steady(session_factory):
    async with session_factory() as session:
        salary = await CategoryRepository(session).get_id_by_name("Salary")
        session.add(
            Transaction(
                merchant="Employer",
                category_id=salary,
                amount=Decimal("5000"),
                occurred_on=WED,
                direction="in",
                status="confirmed",
            )
        )
        await session.commit()
    f = await facts(session_factory)
    assert f.has_activity and not f.flags and not f.top_out and not f.goals
    (only,) = fallback_recommendations(f)
    assert only.startswith("Nothing stands out")


async def test_no_fallback_line_claims_a_trend_the_facts_do_not_compare(
    session_factory,
):
    scenarios = []
    scenarios.append(await facts(session_factory))  # an empty week
    await seed(session_factory)
    scenarios.append(await facts(session_factory))  # a busy week
    for f in scenarios:
        for text in fallback_recommendations(f):
            assert "steady" not in text.lower()


def test_both_prompts_forbid_trend_claims_the_facts_do_not_support():
    from pfa.graphs.insights import ANSWER_PROMPT, RECOMMEND_PROMPT

    for prompt in (RECOMMEND_PROMPT, ANSWER_PROMPT):
        assert "Never describe spending as steady" in prompt
        assert "nothing was recorded" in prompt.lower()
