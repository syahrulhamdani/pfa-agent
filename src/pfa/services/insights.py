"""The facts pfa may quote, and the checks that keep its words to those facts.

All figures come from SQL through the analytics and budget services. A model writes
the sentences from `render_facts`, never from the database, and `numbers_grounded`
rejects any sentence that quotes a figure that is not in the facts. When the model is
unavailable or strays, `fallback_recommendations` says the same things from a
template, so a summary always goes out and is always true.
"""

import math
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from pfa.repository.budgets import GoalRepository
from pfa.schemas.analytics import Period
from pfa.schemas.insights import (
    BudgetLine,
    BudgetState,
    CategoryLine,
    GoalLine,
    InsightFacts,
)
from pfa.services.analytics import build_analytics
from pfa.services.budgets import build_budgets

ZERO = Decimal("0.00")
NEAR_BUDGET = 0.85  # this share of a budget used counts as "nearly used"
MAX_TOP_CATEGORIES = 5
MAX_FALLBACK_LINES = 4


# --- formatting: one place, so the model, the fallback and the checks agree ---


def fmt_money(value: Decimal) -> str:
    """Formats an amount with thousands separators; cents only when there are any."""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{abs(rounded):,.2f}"
    return text[:-3] if text.endswith(".00") else text


def fmt_percent(fraction: float) -> str:
    """Formats 0.9347 as "93%"."""
    return f"{round(abs(fraction) * 100)}%"


def period_label(period: Period, start: date, end: date) -> str:
    """Names a period the way a person would."""
    if period is Period.DAY:
        return f"{start:%b} {start.day}, {start.year}"
    if period is Period.WEEK:
        return f"Week of {start:%b} {start.day} – {end:%b} {end.day}, {end.year}"
    if period is Period.MONTH:
        return f"{start:%B %Y}"
    if period is Period.QUARTER:
        return f"Q{(start.month - 1) // 3 + 1} {start.year}"
    return str(start.year)


def budget_state(used: float) -> BudgetState:
    """Says how much of a budget is used: over, nearly (85% or more), or on track."""
    if used > 1:
        return "over"
    if used >= NEAR_BUDGET:
        return "near"
    return "ok"


# --- the one rule that is the user's call ---


def budget_flags(lines: list[BudgetLine]) -> list[BudgetLine]:
    """Picks the budgets pfa should speak up about, most pressing first.

    Args:
        lines: Every budget this month, each with its `state` ("ok", "near" or
            "over"), `used` (spent over budget, 1.0 meaning all of it) and
            `remaining` (negative once over).

    Returns:
        The lines worth mentioning in a summary or an answer, in the order to
        mention them.
    """
    return sorted(
        (line for line in lines if line.state != "ok"),
        key=lambda line: line.used,
        reverse=True,
    )


# --- gathering ---


def _goal_line(goal, today: date) -> GoalLine:
    remaining = max(goal.target_amount - goal.saved_amount, ZERO)
    days_left = (goal.target_date - today).days
    per_week = None
    if remaining > 0 and days_left > 0:
        weeks = max(math.ceil(days_left / 7), 1)
        per_week = (remaining / weeks).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return GoalLine(
        name=goal.name,
        saved=goal.saved_amount,
        target=goal.target_amount,
        progress=round(float(goal.saved_amount / goal.target_amount), 4),
        remaining=remaining,
        days_left=days_left,
        per_week_needed=per_week,
    )


async def gather_facts(
    session: AsyncSession,
    period: Period,
    anchor: date,
    today: date,
    *,
    category: str | None = None,
    budget_month: date | None = None,
    partial: bool = False,
) -> InsightFacts:
    """Computes the facts for the period containing `anchor`.

    Args:
        session: Database session.
        period: How wide a view.
        anchor: Any date inside the period.
        today: The current date in the user's timezone.
        category: A category a question asked about; its figures are added.
        budget_month: The month whose budgets to report. Defaults to the month of
            the earlier of the period's end and today.
        partial: Whether the period was still running when this was written.

    Returns:
        Totals, comparison with the period before, top categories, budgets and the
        ones worth flagging, and goals.
    """
    analytics = await build_analytics(session, period, anchor)
    month = (budget_month or min(analytics.end, today)).replace(day=1)
    budgets = await build_budgets(session, month)
    lines = [
        BudgetLine(
            category=item.category,
            amount=item.amount,
            spent=item.spent,
            remaining=item.remaining,
            used=item.used,
            state=budget_state(item.used),
        )
        for item in budgets.items
    ]
    top = [
        CategoryLine(
            category=row.category, total=row.total, count=row.count, share=row.share
        )
        for row in analytics.out_by_category
    ]
    focus = None
    if category:
        focus = next(
            (c for c in top if c.category.casefold() == category.casefold()), None
        )
    goals = await GoalRepository(session).list_all()
    return InsightFacts(
        label=period_label(period, analytics.start, analytics.end),
        period=period,
        start=analytics.start,
        end=analytics.end,
        partial=partial,
        money_out=analytics.money_out.total,
        money_in=analytics.money_in.total,
        net=analytics.net,
        out_count=analytics.money_out.count,
        in_count=analytics.money_in.count,
        money_out_change=analytics.previous.money_out_change,
        money_in_change=analytics.previous.money_in_change,
        transfers=analytics.transfers,
        top_out=top[:MAX_TOP_CATEGORIES],
        focus=focus,
        focus_name=category,
        budget_month=month,
        budgets=lines,
        flags=budget_flags(lines),
        unbudgeted_spent=budgets.unbudgeted_spent,
        goals=[_goal_line(g, today) for g in goals],
    )


# --- rendering ---


def _change_text(change: float | None, noun: str) -> str:
    if change is None:
        return f"nothing was recorded in the previous {noun} to compare with"
    if round(change * 100) == 0:
        return f"the same as the previous {noun}"
    word = "more" if change > 0 else "less"
    return f"{fmt_percent(change)} {word} than the previous {noun}"


def budget_status(line: BudgetLine) -> str:
    """Says what is left of a budget, or how far over it is, in words."""
    if line.remaining < 0:
        return f"over budget by {fmt_money(-line.remaining)}"
    return f"{fmt_money(line.remaining)} left"


def render_facts(facts: InsightFacts) -> str:
    """Writes the facts as plain lines. This is all a model is ever shown."""
    noun = facts.period.value
    lines = [
        f"Period: {facts.label}"
        + (" (still running, so far)" if facts.partial else ""),
        f"Money out: {fmt_money(facts.money_out)} in {facts.out_count} "
        f"transactions; {_change_text(facts.money_out_change, noun)}",
        f"Money in: {fmt_money(facts.money_in)} in {facts.in_count} transactions; "
        f"{_change_text(facts.money_in_change, noun)}",
        f"Net (money in minus money out): "
        f"{'-' if facts.net < 0 else ''}{fmt_money(facts.net)}",
    ]
    if facts.transfers.count:
        moved = fmt_money(facts.transfers.total)
        lines.append(
            "Moves between the user's own accounts, not counted as spending or "
            f"income: {facts.transfers.count} totalling {moved}"
        )
    if facts.top_out:
        lines.append(
            "Top spending categories: "
            + "; ".join(
                f"{c.category} {fmt_money(c.total)} ({fmt_percent(c.share)} of money "
                f"out, {c.count} transactions)"
                for c in facts.top_out
            )
        )
    if facts.focus_name:
        if facts.focus:
            lines.append(
                f"Asked about {facts.focus.category}: {fmt_money(facts.focus.total)} "
                f"spent, {fmt_percent(facts.focus.share)} of money out, "
                f"{facts.focus.count} transactions"
            )
        else:
            lines.append(
                f"Asked about {facts.focus_name}: nothing spent in this period"
            )
    if facts.budget_month:
        if facts.budgets:
            lines.append(
                f"Budgets for {facts.budget_month:%B %Y}: "
                + "; ".join(
                    f"{b.category} budget {fmt_money(b.amount)}, spent "
                    f"{fmt_money(b.spent)}, {budget_status(b)} "
                    f"({fmt_percent(b.used)} used)"
                    for b in facts.budgets
                )
            )
        else:
            lines.append(f"No budgets are set for {facts.budget_month:%B %Y}")
        if facts.unbudgeted_spent > 0:
            lines.append(
                "Spent this month in categories without a budget: "
                f"{fmt_money(facts.unbudgeted_spent)}"
            )
    if facts.flags:
        lines.append(
            "Needs attention: "
            + "; ".join(
                f"{b.category} is {budget_status(b)} ({fmt_percent(b.used)} used)"
                for b in facts.flags
            )
        )
    if facts.goals:
        lines.append("Savings goals: " + "; ".join(_goal_text(g) for g in facts.goals))
    else:
        lines.append("No savings goals are set")
    return "\n".join(lines)


def _goal_text(goal: GoalLine) -> str:
    base = (
        f"{goal.name} saved {fmt_money(goal.saved)} of {fmt_money(goal.target)} "
        f"({fmt_percent(goal.progress)})"
    )
    if goal.progress >= 1:
        return f"{base}, reached"
    if goal.days_left < 0:
        return f"{base}, target date passed {-goal.days_left} days ago"
    pace = (
        f", needs about {fmt_money(goal.per_week_needed)} per week"
        if goal.per_week_needed
        else ""
    )
    return f"{base}, {goal.days_left} days left{pace}"


# --- the figures, laid out to be read ---

MAX_STATS_TOP = 3
MAX_STATS_BUDGETS = 6
MAX_STATS_GOALS = 5


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _goal_stats(goal: GoalLine) -> str:
    base = (
        f"{goal.name}: {fmt_money(goal.saved)} of {fmt_money(goal.target)} "
        f"({fmt_percent(goal.progress)})"
    )
    if goal.progress >= 1:
        return f"{base}, reached"
    if goal.days_left < 0:
        return f"{base}, target date passed {-goal.days_left} days ago"
    pace = (
        f", about {fmt_money(goal.per_week_needed)} a week to get there"
        if goal.per_week_needed
        else ""
    )
    return f"{base}, {goal.days_left} days left{pace}"


def render_stats(facts: InsightFacts) -> str:
    """Lays the figures out for a chat message: one labelled figure per line.

    Built from the same facts as everything else, so every number here is one pfa
    computed. A question about one category shows that category first, with its own
    budget, and leaves out the long lists.
    """
    noun = facts.period.value
    lines = [facts.label + (" (so far)" if facts.partial else ""), ""]
    if facts.focus_name:
        if facts.focus:
            lines.append(
                f"{facts.focus.category}: {fmt_money(facts.focus.total)} spent "
                f"({fmt_percent(facts.focus.share)} of your money out, "
                f"{_plural(facts.focus.count, 'transaction', 'transactions')})"
            )
        else:
            lines.append(f"{facts.focus_name}: nothing spent in this period")
        budget = next(
            (
                b
                for b in facts.budgets
                if b.category.casefold() == facts.focus_name.casefold()
            ),
            None,
        )
        if budget and facts.budget_month:
            lines.append(
                f"Budget for {facts.budget_month:%B %Y}: {fmt_money(budget.spent)} of "
                f"{fmt_money(budget.amount)} used ({fmt_percent(budget.used)}), "
                f"{budget_status(budget)}"
            )
        lines.append("")
    out_line = (
        f"Money out: {fmt_money(facts.money_out)} "
        f"({_plural(facts.out_count, 'transaction', 'transactions')})"
    )
    if facts.money_out_change is not None:
        out_line += f" – {_change_text(facts.money_out_change, noun)}"
    lines += [
        out_line,
        f"Money in: {fmt_money(facts.money_in)} "
        f"({_plural(facts.in_count, 'transaction', 'transactions')})",
        f"Net: {'-' if facts.net < 0 else '+'}{fmt_money(facts.net)}",
    ]
    if facts.transfers.count:
        lines.append(
            "Between your own accounts (not counted): "
            f"{_plural(facts.transfers.count, 'move', 'moves')}, "
            f"{fmt_money(facts.transfers.total)}"
        )
    if facts.focus_name:
        return "\n".join(lines)
    if facts.top_out:
        lines += ["", "Top spending:"]
        lines += [
            f"• {c.category}: {fmt_money(c.total)} ({fmt_percent(c.share)})"
            for c in facts.top_out[:MAX_STATS_TOP]
        ]
    if facts.budgets and facts.budget_month:
        lines += ["", f"Budgets for {facts.budget_month:%B %Y}:"]
        lines += [
            f"• {b.category}: {fmt_money(b.spent)} of {fmt_money(b.amount)} "
            f"({fmt_percent(b.used)}), {budget_status(b)}"
            for b in facts.budgets[:MAX_STATS_BUDGETS]
        ]
    if facts.goals:
        lines += ["", "Goals:"]
        lines += [f"• {_goal_stats(g)}" for g in facts.goals[:MAX_STATS_GOALS]]
    return "\n".join(lines)


# --- the same advice without a model ---


def fallback_recommendations(facts: InsightFacts) -> list[str]:
    """Says the most useful things from the facts alone, with no model involved."""
    lines: list[str] = []
    if not facts.has_activity:
        # Say so first, whatever else is set up: with nothing recorded there is no
        # pattern to describe, only budgets and goals that still need attention.
        lines.append(
            "Nothing was recorded in this period. Send receipts or a statement and "
            "I can start comparing your spending with your budgets."
        )
    for flag in facts.flags[:2]:
        if flag.state == "over":
            lines.append(
                f"{flag.category} is over its budget by {fmt_money(-flag.remaining)}. "
                "Consider holding off on more spending there this month."
            )
        else:
            lines.append(
                f"{flag.category} is {fmt_percent(flag.used)} used, with "
                f"{fmt_money(flag.remaining)} left. Watch it for the rest of the month."
            )
    if facts.top_out:
        top = facts.top_out[0]
        lines.append(
            f"Most of your money out went to {top.category}: {fmt_money(top.total)}, "
            f"{fmt_percent(top.share)} of the total."
        )
    for goal in facts.goals:
        if goal.per_week_needed:
            lines.append(
                f"To reach {goal.name} by its date, set aside about "
                f"{fmt_money(goal.per_week_needed)} a week."
            )
            break
    if facts.money_out_change is not None and round(facts.money_out_change * 100):
        direction = "up" if facts.money_out_change > 0 else "down"
        lines.append(
            f"Money out was {direction} {fmt_percent(facts.money_out_change)} on the "
            f"previous {facts.period.value}."
        )
    return lines[:MAX_FALLBACK_LINES] or [
        "Nothing stands out in this period. Keep sending receipts so the picture "
        "stays accurate."
    ]


# --- keeping the model to the facts ---

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+", re.MULTILINE)


def _numbers(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for token in _NUMBER.findall(text):
        try:
            found.add(Decimal(token.replace(",", "").rstrip(".")))
        except ArithmeticError:  # pragma: no cover - the pattern only matches digits
            continue
    return found


def ungrounded_numbers(text: str, facts_text: str) -> set[Decimal]:
    """Returns the figures in `text` that do not appear in the facts."""
    allowed = _numbers(facts_text)
    return _numbers(_LIST_MARKER.sub("", text)) - allowed


def numbers_grounded(text: str, facts_text: str) -> bool:
    """True if every figure in `text` is one of the facts, however it is formatted."""
    return not ungrounded_numbers(text, facts_text)
