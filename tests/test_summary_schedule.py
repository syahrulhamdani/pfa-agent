"""Boundary: the weekly summary is scheduled for Monday morning, local time.

What is tested: the job exists only when a sender is given, runs on Mondays at the
configured hour in the user's timezone, is not duplicated by rescheduling nudges, and
the hour setting rejects nonsense.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from apscheduler.triggers.cron import CronTrigger
from pydantic import ValidationError

from pfa.core.config import Settings
from pfa.services.nudges import NudgeService
from pfa.services.scheduler import SUMMARY_HOUR, SUMMARY_JOB_ID, NudgeScheduler


@pytest.fixture
def make_scheduler(session_factory):
    created = []

    def _make(timezone="Asia/Jakarta", **kwargs):
        scheduler = NudgeScheduler(
            service=NudgeService(session_factory, timezone),
            send_nudge=AsyncMock(),
            timezone=timezone,
            **kwargs,
        )
        created.append(scheduler)
        return scheduler

    yield _make
    for scheduler in created:
        scheduler.shutdown()


def fields(job) -> dict[str, str]:
    assert isinstance(job.trigger, CronTrigger)
    return {f.name: str(f) for f in job.trigger.fields}


async def test_the_summary_runs_on_mondays_in_the_users_timezone(make_scheduler):
    send = AsyncMock()
    scheduler = make_scheduler("Asia/Jakarta", send_summary=send)
    await scheduler.start()
    job = scheduler._scheduler.get_job(SUMMARY_JOB_ID)
    assert job is not None
    assert fields(job)["day_of_week"] == "mon"
    assert (fields(job)["hour"], fields(job)["minute"]) == (str(SUMMARY_HOUR), "0")
    assert str(job.trigger.timezone) == "Asia/Jakarta"
    assert job.func is send


async def test_the_hour_can_be_configured(make_scheduler):
    scheduler = make_scheduler("UTC", send_summary=AsyncMock(), summary_hour=19)
    await scheduler.start()
    assert fields(scheduler._scheduler.get_job(SUMMARY_JOB_ID))["hour"] == "19"


async def test_without_a_sender_there_is_no_summary_job(make_scheduler):
    scheduler = make_scheduler("UTC")
    await scheduler.start()
    assert scheduler._scheduler.get_job(SUMMARY_JOB_ID) is None


async def test_rescheduling_nudges_leaves_the_summary_job_alone(make_scheduler):
    scheduler = make_scheduler("UTC", send_summary=AsyncMock())
    await scheduler.start()
    before = scheduler._scheduler.get_job(SUMMARY_JOB_ID)
    await scheduler.reschedule()
    await scheduler.reschedule()
    after = scheduler._scheduler.get_job(SUMMARY_JOB_ID)
    assert after is not None and after.id == before.id
    jobs = [j for j in scheduler._scheduler.get_jobs() if j.id == SUMMARY_JOB_ID]
    assert len(jobs) == 1


async def test_the_summary_job_stops_with_the_scheduler(make_scheduler):
    scheduler = make_scheduler("UTC", send_summary=AsyncMock())
    await scheduler.start()
    scheduler.shutdown()
    await asyncio.sleep(0)
    assert not scheduler._scheduler.running


@pytest.mark.parametrize("hour", [-1, 24, 99])
def test_a_summary_hour_outside_the_day_is_rejected(hour, monkeypatch):
    monkeypatch.setenv("SUMMARY_HOUR", str(hour))
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize("hour", [0, 8, 23])
def test_a_summary_hour_inside_the_day_is_accepted(hour, monkeypatch):
    monkeypatch.setenv("SUMMARY_HOUR", str(hour))
    assert Settings().summary_hour == hour  # type: ignore[call-arg]
