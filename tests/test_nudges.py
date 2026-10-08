"""Boundary: how the nudge slots are chosen, stored, scheduled and sent."""

import asyncio
import random
from datetime import UTC, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger

from pfa.bot.formatting import NUDGE_TEXT
from pfa.bot.nudges import build_nudge_sender
from pfa.models import Transaction
from pfa.repository.finance import NudgeSlotRepository
from pfa.schemas.nudges import Slot, SlotSource
from pfa.services.nudges import (
    DEFAULT_SLOT_TIMES,
    MIN_TRANSACTIONS_TO_LEARN,
    SLOT_COUNT,
    NudgeService,
    choose_slots,
    circular_gap,
    default_slots,
    learn_slots,
    pad_with_defaults,
    to_minute,
    to_time,
)
from pfa.services.scheduler import (
    NUDGE_JOB_PREFIX,
    REFRESH_JOB_ID,
    NudgeScheduler,
)


def hm(hour: int, minute: int = 0) -> int:
    return hour * 60 + minute


# --- the default slots ---


def test_there_are_six_distinct_default_slots_in_time_order():
    slots = default_slots()
    assert len(slots) == SLOT_COUNT == len(DEFAULT_SLOT_TIMES)
    assert len({s.at for s in slots}) == SLOT_COUNT
    assert [s.at for s in slots] == sorted(s.at for s in slots)
    assert {s.source for s in slots} == {SlotSource.DEFAULT}


# --- clock helpers ---


def test_minute_and_time_round_trip():
    assert to_time(to_minute(time(7, 45))) == time(7, 45)
    assert to_time(24 * 60 + 5) == time(0, 5)  # wraps past midnight


def test_circular_gap_goes_the_short_way_round_midnight():
    assert circular_gap(hm(23, 50), hm(0, 10)) == 20
    assert circular_gap(hm(8), hm(12)) == 240
    assert circular_gap(hm(8), hm(8)) == 0


# --- learning slots from history ---

SIX_HABITS = [hm(8), hm(10, 30), hm(12, 45), hm(16), hm(19, 15), hm(21, 45)]


def history_around(habits: list[int], per_habit: int = 5, jitter: int = 10):
    rng = random.Random(7)
    return [h + rng.randint(-jitter, jitter) for h in habits for _ in range(per_habit)]


def test_learned_slots_land_on_the_users_habits():
    learned = learn_slots(history_around(SIX_HABITS))
    assert len(learned) == SLOT_COUNT
    for habit, slot in zip(SIX_HABITS, learned, strict=True):
        assert circular_gap(habit, slot) <= 10


def test_learning_is_deterministic_and_ignores_input_order():
    history = history_around(SIX_HABITS)
    shuffled = history[:]
    random.Random(1).shuffle(shuffled)
    assert learn_slots(history) == learn_slots(history) == learn_slots(shuffled)


def test_nothing_to_learn_from_gives_no_slots():
    assert learn_slots([]) == []


def test_fewer_distinct_times_than_clusters_gives_fewer_slots():
    assert learn_slots([hm(8)] * 25) == [hm(8)]
    assert learn_slots([hm(8)] * 10 + [hm(20)] * 10) == [hm(8), hm(20)]


def test_late_night_uploads_either_side_of_midnight_form_one_cluster():
    # 23:50 and 00:10 are 20 minutes apart; a naive average would say noon.
    history = [hm(23, 50)] * 10 + [hm(0, 10)] * 10
    assert learn_slots(history, k=1) == [0]


def test_slots_are_valid_sorted_unique_minutes_of_the_day():
    rng = random.Random(3)
    history = [rng.randint(0, 24 * 60 - 1) for _ in range(200)]
    learned = learn_slots(history)
    assert learned == sorted(set(learned))
    assert all(0 <= m < 24 * 60 for m in learned)
    assert len(learned) == SLOT_COUNT


# --- padding a short learned list ---


@pytest.mark.parametrize(
    "learned",
    [
        [],
        [hm(12, 30)],
        [hm(8), hm(20)],
        [hm(9), hm(11), hm(13)],
        [hm(7, 30), hm(10), hm(12, 30), hm(15, 30), hm(19)],
        [hm(1), hm(2), hm(3), hm(4), hm(5)],
        SIX_HABITS,
    ],
)
def test_padding_always_gives_six_distinct_slots_and_keeps_learned_ones(learned):
    slots = pad_with_defaults(learned)
    times = [to_minute(s.at) for s in slots]
    assert len(slots) == SLOT_COUNT
    assert len(set(times)) == SLOT_COUNT
    assert times == sorted(times)
    for minute in learned:
        match = next(s for s in slots if to_minute(s.at) == minute)
        assert match.source is SlotSource.LEARNED


def test_padding_prefers_defaults_that_are_not_next_to_a_learned_slot():
    learned_minute = hm(12, 30)
    slots = pad_with_defaults([learned_minute])
    for slot in slots:
        if slot.source is SlotSource.DEFAULT:
            assert circular_gap(to_minute(slot.at), learned_minute) >= 60


# --- when to switch from defaults to learned ---


def test_just_under_the_threshold_uses_defaults():
    slots = choose_slots([hm(8)] * (MIN_TRANSACTIONS_TO_LEARN - 1))
    assert slots == default_slots()


def test_at_the_threshold_slots_are_learned():
    slots = choose_slots([hm(8, 5)] * MIN_TRANSACTIONS_TO_LEARN)
    assert Slot(at=time(8, 5), source=SlotSource.LEARNED) in slots
    assert len(slots) == SLOT_COUNT


def test_no_history_uses_defaults():
    assert choose_slots([]) == default_slots()


# --- the service: history in, stored slots out (real Postgres) ---

JAKARTA = ZoneInfo("Asia/Jakarta")


async def add_transactions(session_factory, count, at: datetime, status="confirmed"):
    async with session_factory() as session:
        session.add_all(
            Transaction(
                merchant=f"Shop {i}",
                amount=Decimal("10"),
                status=status,
                confirmed_at=at if status == "confirmed" else None,
            )
            for i in range(count)
        )
        await session.commit()


async def stored(session_factory):
    async with session_factory() as session:
        rows = await NudgeSlotRepository(session).list_all()
    return [(r.time_of_day, r.source) for r in rows]


async def test_no_history_stores_the_six_defaults(session_factory):
    slots = await NudgeService(session_factory, "Asia/Jakarta").refresh_slots()
    assert slots == default_slots()
    rows = await stored(session_factory)
    assert [t for t, _ in rows] == [s.at for s in default_slots()]
    assert {src for _, src in rows} == {"default"}


async def test_enough_history_stores_learned_slots_in_the_users_timezone(
    session_factory,
):
    # 01:00 UTC is 08:00 in Jakarta: the slot must follow the user's clock.
    await add_transactions(
        session_factory,
        MIN_TRANSACTIONS_TO_LEARN,
        datetime(2026, 10, 1, 1, 0, tzinfo=UTC),
    )
    await NudgeService(session_factory, "Asia/Jakarta").refresh_slots()
    rows = await stored(session_factory)
    assert (time(8, 0), "learned") in rows
    assert len(rows) == SLOT_COUNT


async def test_pending_transactions_do_not_count_towards_learning(session_factory):
    await add_transactions(
        session_factory, 30, datetime(2026, 10, 1, 1, 0, tzinfo=UTC), status="pending"
    )
    slots = await NudgeService(session_factory, "UTC").refresh_slots()
    assert slots == default_slots()


async def test_refreshing_replaces_rather_than_accumulates(session_factory):
    service = NudgeService(session_factory, "UTC")
    await service.refresh_slots()
    await service.refresh_slots()
    assert len(await stored(session_factory)) == SLOT_COUNT


# --- the scheduler: slots become daily jobs ---


@pytest.fixture
def make_scheduler(session_factory):
    created = []

    def _make(timezone="Asia/Jakarta", send=None):
        scheduler = NudgeScheduler(
            service=NudgeService(session_factory, timezone),
            send_nudge=send or AsyncMock(),
            timezone=timezone,
        )
        created.append(scheduler)
        return scheduler

    yield _make
    for scheduler in created:
        scheduler.shutdown()


def nudge_jobs(scheduler):
    return [
        j for j in scheduler._scheduler.get_jobs() if j.id.startswith(NUDGE_JOB_PREFIX)
    ]


def fields(job) -> dict[str, str]:
    assert isinstance(job.trigger, CronTrigger)
    return {f.name: str(f) for f in job.trigger.fields}


async def test_each_slot_becomes_a_daily_job_in_the_users_timezone(make_scheduler):
    scheduler = make_scheduler("Asia/Jakarta")
    await scheduler.reschedule()
    jobs = nudge_jobs(scheduler)
    assert len(jobs) == SLOT_COUNT
    scheduled = sorted((int(fields(j)["hour"]), int(fields(j)["minute"])) for j in jobs)
    assert scheduled == sorted((t.hour, t.minute) for t in DEFAULT_SLOT_TIMES)
    assert all(str(j.trigger.timezone) == "Asia/Jakarta" for j in jobs)
    assert all(fields(j)["day"] == "*" for j in jobs)  # every day


async def test_rescheduling_replaces_jobs_instead_of_duplicating(
    make_scheduler, session_factory
):
    scheduler = make_scheduler("UTC")
    await scheduler.reschedule()
    before = {j.id for j in nudge_jobs(scheduler)}
    await scheduler.reschedule()
    assert {j.id for j in nudge_jobs(scheduler)} == before

    # Once there is history, the old default jobs are swapped for the learned set.
    await add_transactions(
        session_factory,
        MIN_TRANSACTIONS_TO_LEARN,
        datetime(2026, 10, 1, 8, 5, tzinfo=UTC),
    )
    await scheduler.reschedule()
    after = {j.id for j in nudge_jobs(scheduler)}
    assert len(after) == SLOT_COUNT
    assert f"{NUDGE_JOB_PREFIX}0805" in after
    assert after != before


async def test_starting_adds_a_daily_refresh_and_shutdown_stops_it(make_scheduler):
    scheduler = make_scheduler("UTC")
    await scheduler.start()
    refresh = scheduler._scheduler.get_job(REFRESH_JOB_ID)
    assert refresh is not None
    assert fields(refresh)["hour"] == "4"
    assert scheduler._scheduler.running
    scheduler.shutdown()
    scheduler.shutdown()  # repeat calls are harmless
    await asyncio.sleep(0)  # APScheduler stops on the next turn of the event loop
    assert not scheduler._scheduler.running


async def test_firing_a_nudge_sends_one_message_and_schedules_nothing_more(
    make_scheduler,
):
    send = AsyncMock()
    scheduler = make_scheduler("UTC", send=send)
    await scheduler.reschedule()
    jobs_before = {j.id for j in scheduler._scheduler.get_jobs()}

    await nudge_jobs(scheduler)[0].func()  # the slot fires, the user ignores it

    send.assert_awaited_once()
    assert {
        j.id for j in scheduler._scheduler.get_jobs()
    } == jobs_before  # no follow-up


# --- sending to Telegram ---


async def test_sender_posts_the_nudge_text_to_the_configured_chat():
    bot = SimpleNamespace(send_message=AsyncMock())
    await build_nudge_sender(bot, 42)()
    bot.send_message.assert_awaited_once_with(chat_id=42, text=NUDGE_TEXT)


async def test_sender_survives_a_telegram_failure():
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("down")))
    await build_nudge_sender(bot, 42)()  # must not raise into the scheduler


def test_the_nudge_does_not_pressure_or_chase():
    assert "?" in NUDGE_TEXT
    assert len(NUDGE_TEXT) < 100
