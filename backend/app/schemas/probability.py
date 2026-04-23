from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TriggerOut(BaseModel):
    label: str
    bucket_key: str
    mean: float
    samples: int


class ProbabilityOut(BaseModel):
    as_of: datetime
    p_now: float
    p_low: float
    p_high: float
    uncertainty_width: float
    confidence_level: str
    p_next_hour: float
    next_peak_at: datetime | None
    bucket_key: str
    dopamine: float
    withdrawal: float
    habit: float
    rule_reasons: list[str]
    top_triggers: list[TriggerOut]


class NudgeOut(BaseModel):
    id: str
    title: str
    body: str
    duration_seconds: int
    kind: str


class WeaningOut(BaseModel):
    target_today: int
    smoked_today: int
    remaining: int
    rolling_avg_7d: float
    state: str
    streak_days_on_target: int


class RecommendationOut(BaseModel):
    as_of: datetime
    probability: ProbabilityOut
    weaning: WeaningOut
    nudge: NudgeOut | None
