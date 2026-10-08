"""Pydantic models for nudge slots."""

import enum
from datetime import time

from pydantic import BaseModel, ConfigDict


class SlotSource(enum.StrEnum):
    """Where a slot's time came from."""

    DEFAULT = "default"
    LEARNED = "learned"


class Slot(BaseModel):
    """One nudge time of day and where it came from."""

    model_config = ConfigDict(frozen=True)

    at: time
    source: SlotSource
