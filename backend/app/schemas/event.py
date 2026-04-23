from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventKind(StrEnum):
    cigarette = "cigarette"
    craving = "craving"
    context = "context"
    nudge = "nudge"


class EventIn(BaseModel):
    client_uuid: str = Field(min_length=8, max_length=64)
    kind: EventKind
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class EventBatchIn(BaseModel):
    events: list[EventIn] = Field(default_factory=list, max_length=500)


class EventBatchOut(BaseModel):
    accepted: int
    duplicates: int
