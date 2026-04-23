from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    baseline_cigarettes_per_day: int | None = Field(default=None, ge=0, le=80)
    weaning_rate_pct: int = Field(default=5, ge=0, le=50)
    weight_kg: float = Field(default=75.0, ge=35.0, le=250.0)
    height_cm: float = Field(default=175.0, ge=120.0, le=230.0)
    body_fat: float = Field(default=0.20, ge=0.05, le=0.60)
    age_years: int = Field(default=30, ge=14, le=110)
    weekly_weight_loss_kg: float = Field(default=0.40, ge=0.0, le=2.0)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
