"""The weekly summary as a Telegram message, and the functions that send it."""

from collections.abc import Awaitable, Callable

from loguru import logger
from telegram import Bot, LinkPreviewOptions

from pfa.schemas.insights import WeeklySummaryRead
from pfa.services.insights import budget_status, fmt_money, fmt_percent
from pfa.services.summaries import SummaryService

SUMMARY_FAILED_TEXT = (
    "I couldn't write your summary just now. Please try again in a moment."
)
MAX_FLAGS_SHOWN = 3
MAX_TOP_SHOWN = 3


def summary_text(summary: WeeklySummaryRead, link: str, ttl_minutes: int) -> str:
    """Writes a short summary for Telegram, with a link to the dashboard.

    Every figure here comes from the stored facts; only the advice lines were
    written by a model (and checked against those facts).

    Args:
        summary: The saved summary.
        link: A single-use sign-in link that opens the dashboard.
        ttl_minutes: How long the link stays valid.
    """
    facts = summary.facts
    lines = [
        ("So far this week: " if facts.partial else "") + facts.label,
        "",
        f"Money out: {fmt_money(facts.money_out)} ({facts.out_count} "
        f"{'transaction' if facts.out_count == 1 else 'transactions'})",
        f"Money in: {fmt_money(facts.money_in)}",
        f"Net: {'-' if facts.net < 0 else '+'}{fmt_money(facts.net)}",
    ]
    if facts.transfers.count:
        lines.append(
            f"Between your own accounts (not counted): {facts.transfers.count} "
            f"{'move' if facts.transfers.count == 1 else 'moves'}, "
            f"{fmt_money(facts.transfers.total)}"
        )
    if facts.top_out:
        top = ", ".join(
            f"{c.category} {fmt_money(c.total)} ({fmt_percent(c.share)})"
            for c in facts.top_out[:MAX_TOP_SHOWN]
        )
        lines += ["", f"Top spending: {top}"]
    if facts.flags:
        watch = "; ".join(
            f"{b.category} {budget_status(b)}" for b in facts.flags[:MAX_FLAGS_SHOWN]
        )
        lines += ["", f"Budgets to watch: {watch}"]
    if summary.recommendations:
        lines += ["", "What I'd do:"]
        lines += [f"- {text}" for text in summary.recommendations]
    lines += [
        "",
        f"Full summary (sign-in link, valid for {ttl_minutes} minutes, works once): "
        f"{link}",
    ]
    return "\n".join(lines)


def build_summary_senders(
    *,
    bot: Bot,
    chat_id: int,
    service: SummaryService,
    issue_link: Callable[[], Awaitable[str]],
    ttl_minutes: int,
) -> tuple[Callable[[], Awaitable[None]], Callable[[], Awaitable[None]]]:
    """Returns the Monday job and the demo trigger. Neither ever raises.

    The Monday job writes last week's summary and sends it, but only if it was not
    already written, so a restart or a repeat never sends it twice. The demo always
    writes a fresh one and sends it, and tells the user if that fails.
    """

    async def deliver(summary: WeeklySummaryRead) -> None:
        link = await issue_link()
        await bot.send_message(
            chat_id=chat_id,
            text=summary_text(summary, link, ttl_minutes),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    async def send_monday_summary() -> None:
        try:
            result = await service.monday_summary()
            if not result.created:
                logger.info("Weekly summary already sent; not sending it again")
                return
            await deliver(result.summary)
        except Exception:
            logger.exception("Could not write or send the weekly summary")
        else:
            logger.info("Weekly summary sent")

    async def send_demo_summary() -> None:
        try:
            await deliver((await service.demo_summary()).summary)
        except Exception:
            logger.exception("Could not write or send the demo summary")
            try:
                await bot.send_message(chat_id=chat_id, text=SUMMARY_FAILED_TEXT)
            except Exception:
                logger.exception("Could not even report the failure")

    return send_monday_summary, send_demo_summary
