"""Sending a nudge to Telegram."""

from collections.abc import Awaitable, Callable

from loguru import logger
from telegram import Bot

from pfa.bot.formatting import NUDGE_TEXT


def build_nudge_sender(bot: Bot, chat_id: int) -> Callable[[], Awaitable[None]]:
    """Returns a function that sends one nudge and never raises.

    The scheduler and `/demo_nudge` share it. A nudge is never followed up: an
    ignored nudge is simply ignored, so there is no state to track here.
    """

    async def send_nudge() -> None:
        try:
            await bot.send_message(chat_id=chat_id, text=NUDGE_TEXT)
        except Exception:
            logger.exception("Could not send the nudge")
        else:
            logger.info("Nudge sent")

    return send_nudge
