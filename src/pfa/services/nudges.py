"""Nudge slots: when pfa asks the user to upload receipts.

With little history pfa uses six fixed times through the day. Once there are enough
confirmed transactions it learns the times the user actually uploads, by grouping
them into six clusters and nudging at each cluster's centre.
"""

from datetime import time
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pfa.repository.finance import NudgeSlotRepository, TransactionRepository
from pfa.schemas.nudges import Slot, SlotSource

SLOT_COUNT = 6
MIN_TRANSACTIONS_TO_LEARN = 20
MINUTES_PER_DAY = 24 * 60
# Clustering treats the day as starting at 04:00, so that late-night uploads (23:50
# and 00:10) sit next to each other instead of at opposite ends of the clock.
DAY_START_MINUTE = 4 * 60
# A default slot is only used to fill a gap if no learned slot is this close to it.
MIN_GAP_MINUTES = 60

DEFAULT_SLOT_TIMES: tuple[time, ...] = (
    time(7, 30),
    time(10, 0),
    time(13, 30),
    time(15, 30),
    time(19, 0),
    time(22, 30),
)


def to_minute(at: time) -> int:
    """Converts a time of day to minutes since midnight."""
    return at.hour * 60 + at.minute


def to_time(minute: int) -> time:
    """Converts minutes since midnight back to a time of day."""
    minute %= MINUTES_PER_DAY
    return time(minute // 60, minute % 60)


def circular_gap(a: int, b: int) -> int:
    """Returns the shortest distance in minutes between two times on the clock."""
    gap = abs(a - b) % MINUTES_PER_DAY
    return min(gap, MINUTES_PER_DAY - gap)


def default_slots() -> list[Slot]:
    """Returns the six starting slots."""
    return [Slot(at=at, source=SlotSource.DEFAULT) for at in DEFAULT_SLOT_TIMES]


def learn_slots(minutes: list[int], k: int = SLOT_COUNT) -> list[int]:
    """Groups upload times into up to `k` clusters and returns their centres.

    This is k-means in one dimension (Lloyd's algorithm) with a deterministic start,
    so the same history always gives the same slots.

    Args:
        minutes: Minutes since midnight at which transactions were confirmed.
        k: How many clusters to find.

    Returns:
        Up to `k` distinct minutes of the day, earliest first. Fewer than `k` if the
        history has fewer distinct times than that.
    """
    if not minutes:
        return []
    shifted = sorted((m - DAY_START_MINUTE) % MINUTES_PER_DAY for m in minutes)
    distinct = sorted(set(shifted))
    n = min(k, len(distinct))
    if n == 1:
        centres = [float(distinct[0])]
    else:
        centres = [
            float(distinct[round(i * (len(distinct) - 1) / (n - 1))]) for i in range(n)
        ]

    assignment: list[int] = []
    for _ in range(100):
        new_assignment = [
            min(range(n), key=lambda c: (abs(x - centres[c]), c)) for x in shifted
        ]
        if new_assignment == assignment:
            break
        assignment = new_assignment
        for c in range(n):
            members = [x for x, a in zip(shifted, assignment, strict=True) if a == c]
            if members:  # an empty cluster keeps its previous centre
                centres[c] = sum(members) / len(members)

    learned = {(round(c) + DAY_START_MINUTE) % MINUTES_PER_DAY for c in centres}
    return sorted(learned)


def pad_with_defaults(learned: list[int]) -> list[Slot]:
    """Fills a short learned list up to six slots using the default times.

    Defaults that sit within an hour of a learned slot are skipped first, so the
    padding lands in genuine gaps. If that is not enough, the rest are added anyway.
    """
    slots = [Slot(at=to_time(m), source=SlotSource.LEARNED) for m in learned]
    taken = {to_minute(s.at) for s in slots}
    for gap_required in (MIN_GAP_MINUTES, 0):
        for at in DEFAULT_SLOT_TIMES:
            if len(slots) >= SLOT_COUNT:
                break
            minute = to_minute(at)
            if minute in taken:
                continue
            if all(circular_gap(minute, t) >= gap_required for t in taken):
                slots.append(Slot(at=at, source=SlotSource.DEFAULT))
                taken.add(minute)
    return sorted(slots, key=lambda s: s.at)


def choose_slots(confirmed_minutes: list[int]) -> list[Slot]:
    """Picks the nudge slots for a history of confirmation times.

    Args:
        confirmed_minutes: Local minutes since midnight of each confirmed transaction.

    Returns:
        Six slots: the defaults while there are fewer than
        `MIN_TRANSACTIONS_TO_LEARN` transactions, learned ones afterwards.
    """
    if len(confirmed_minutes) < MIN_TRANSACTIONS_TO_LEARN:
        return default_slots()
    return pad_with_defaults(learn_slots(confirmed_minutes))


class NudgeService:
    """Decides the current slots from the transaction history and stores them."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], timezone: str
    ) -> None:
        """Binds the service to the database and the user's timezone."""
        self._session_factory = session_factory
        self._tz = ZoneInfo(timezone)

    async def refresh_slots(self) -> list[Slot]:
        """Recomputes the slots from history, saves them, and returns them.

        Learning uses the time of confirmation (the user's upload time), not the
        date printed on the receipt, because receipts rarely show a time of day.
        """
        async with self._session_factory() as session:
            confirmed = await TransactionRepository(session).confirmed_times()
            local = [t.astimezone(self._tz) for t in confirmed]
            slots = choose_slots([t.hour * 60 + t.minute for t in local])
            await NudgeSlotRepository(session).replace_all(
                [(s.at, s.source.value) for s in slots]
            )
        return slots
