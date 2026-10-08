"""Runs the nudges: one daily job per slot, plus a daily refresh of the slots."""

from collections.abc import Awaitable, Callable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from pfa.schemas.nudges import Slot
from pfa.services.nudges import NudgeService

NUDGE_JOB_PREFIX = "nudge-"
REFRESH_JOB_ID = "refresh-slots"
REFRESH_HOUR = 4  # re-learn the slots once a day, before the day's first nudge


class NudgeScheduler:
    """Keeps the scheduler's jobs in step with the stored nudge slots.

    Jobs live in this process's memory, so nudges only fire while the app runs. That
    is the accepted tradeoff of an in-process scheduler; slots are recomputed at
    every start, so nothing is lost by a restart.
    """

    def __init__(
        self,
        *,
        service: NudgeService,
        send_nudge: Callable[[], Awaitable[None]],
        timezone: str,
        scheduler: AsyncIOScheduler | None = None,
    ) -> None:
        """Creates the scheduler wrapper without starting it."""
        self._service = service
        self._send_nudge = send_nudge
        self._tz = ZoneInfo(timezone)
        self._stopping = False
        self._scheduler = scheduler or AsyncIOScheduler(
            timezone=self._tz,
            # A job that fires a little late still runs, once, and is never repeated.
            job_defaults={"misfire_grace_time": 300, "coalesce": True},
        )

    async def start(self) -> None:
        """Schedules the nudges and the daily refresh, then starts the scheduler."""
        await self.reschedule()
        self._scheduler.add_job(
            self.reschedule,
            CronTrigger(hour=REFRESH_HOUR, minute=0, timezone=self._tz),
            id=REFRESH_JOB_ID,
            replace_existing=True,
        )
        self._scheduler.start()

    async def reschedule(self) -> list[Slot]:
        """Recomputes the slots and replaces every nudge job with the new set."""
        slots = await self._service.refresh_slots()
        for job in self._scheduler.get_jobs():
            if job.id.startswith(NUDGE_JOB_PREFIX):
                self._scheduler.remove_job(job.id)
        for slot in slots:
            self._scheduler.add_job(
                self._send_nudge,
                CronTrigger(
                    hour=slot.at.hour, minute=slot.at.minute, timezone=self._tz
                ),
                id=f"{NUDGE_JOB_PREFIX}{slot.at:%H%M}",
                replace_existing=True,
            )
        logger.info(
            "Nudges scheduled at {}",
            ", ".join(f"{s.at:%H:%M} ({s.source.value})" for s in slots),
        )
        return slots

    def shutdown(self) -> None:
        """Stops the scheduler without waiting for running jobs.

        APScheduler stops asynchronously, on the next turn of the event loop, so
        `running` stays true briefly. Remembering the request keeps repeat calls
        harmless.
        """
        if self._scheduler.running and not self._stopping:
            self._stopping = True
            self._scheduler.shutdown(wait=False)
