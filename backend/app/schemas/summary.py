from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class DailySummary(BaseModel):
    day: date
    cigarettes: int
    cravings: int
    cravings_resisted: int


class SummaryOut(BaseModel):
    today: DailySummary
    last_7_days: list[DailySummary]
    rolling_avg_7d: float
