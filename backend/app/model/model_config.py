"""User-facing model configuration schema and runtime mapping.

This keeps high-level configuration (validated via pydantic) separate from the
low-level numeric parameter dataclass used by the dynamic state-space model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.model.state_space import CravingModelParameters


class BaselineConfig(BaseModel):
    hr_window_days: int = Field(default=14, ge=3, le=60)
    hrv_window_days: int = Field(default=14, ge=3, le=60)
    bp_window_days: int = Field(default=21, ge=3, le=90)
    tremor_window_days: int = Field(default=14, ge=3, le=60)
    sleep_window_days: int = Field(default=21, ge=3, le=90)
    min_std: float = Field(default=1e-3, gt=0.0)


class FeatureWeights(BaseModel):
    # stress index
    a0: float = 0.0
    a_hr: float = 0.8
    a_hrv: float = 0.9
    a_bp: float = 0.4
    a_tremor: float = 0.6

    # cue index
    b0: float = 0.0
    b_ctx: float = 1.0
    b_time: float = 0.5
    b_social: float = 0.7

    # reward index
    c0: float = 0.0
    c_act: float = 0.6
    c_sleep: float = 0.5
    c_interv: float = 0.8


class DynamicsConfig(BaseModel):
    lambda_nicotine: float = Field(default=0.35, gt=0.0)
    k_dopamine: float = Field(default=0.35, gt=0.0)
    k_habit_decay: float = Field(default=0.006, gt=0.0)
    k_withdrawal: float = Field(default=0.06, ge=0.0)
    decay_withdrawal: float = Field(default=0.03, ge=0.0)
    habit_learning: float = Field(default=0.03, ge=0.0)
    alpha_nicotine: float = 0.75
    alpha_reward: float = 0.25
    beta_stress: float = 0.40
    # Two-timescale dopamine dynamics (new)
    k_dopamine_fast: float = Field(default=1.10, gt=0.0)
    k_dopamine_slow: float = Field(default=0.08, gt=0.0)
    dopamine_fast_weight: float = Field(default=0.45, ge=0.0, le=1.0)
    alpha_nicotine_fast: float = 0.90
    alpha_nicotine_slow: float = 0.30
    alpha_reward_fast: float = 0.22
    alpha_reward_slow: float = 0.10
    beta_stress_fast: float = 0.45
    beta_stress_slow: float = 0.18
    # Reserved for future extended equations; stored now for compatibility.
    k_withdrawal_stress: float = 0.12
    k_withdrawal_tremor: float = 0.10
    habit_withdrawal_coupling: float = 0.08


class ReadoutConfig(BaseModel):
    bias: float = 0.0
    w_D: float = 2.0
    w_W: float = 2.4
    w_H: float = 1.6
    w_stress: float = 0.9
    w_cue: float = 0.9
    # interaction terms (reserved for extended readout)
    w_Ws: float = 0.25
    w_Hq: float = 0.25


class KalmanConfig(BaseModel):
    enabled: bool = True
    process_noise: float = Field(default=0.02, gt=0.0)
    observation_noise_craving: float = Field(default=0.08, gt=0.0)
    observation_noise_physio: float = Field(default=0.10, gt=0.0)
    # Optional physio observation mapping (reserved)
    m0: float = 0.0
    m_W: float = 0.6
    m_D: float = 0.4


class ActionConfig(BaseModel):
    default_dopamine_boost: float = 0.12
    default_withdrawal_relief: float = 0.10


class SimulationConfig(BaseModel):
    dt_seconds: int = Field(default=60, ge=10, le=900)
    clamp_states: bool = True


class PlannerConfig(BaseModel):
    baseline_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    rolling_weight: float = Field(default=0.3, ge=0.0, le=1.0)


class DailyWindowConfig(BaseModel):
    enabled: bool = True
    start: str = "08:00"  # HH:MM local time
    end: str = "22:00"    # HH:MM local time


class SmokingCalendarConfig(BaseModel):
    monday: DailyWindowConfig = Field(default_factory=DailyWindowConfig)
    tuesday: DailyWindowConfig = Field(default_factory=DailyWindowConfig)
    wednesday: DailyWindowConfig = Field(default_factory=DailyWindowConfig)
    thursday: DailyWindowConfig = Field(default_factory=DailyWindowConfig)
    friday: DailyWindowConfig = Field(default_factory=DailyWindowConfig)
    saturday: DailyWindowConfig = Field(default_factory=DailyWindowConfig)
    sunday: DailyWindowConfig = Field(default_factory=DailyWindowConfig)


class CravingModelConfig(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    baseline: BaselineConfig = Field(default_factory=BaselineConfig)
    features: FeatureWeights = Field(default_factory=FeatureWeights)
    dynamics: DynamicsConfig = Field(default_factory=DynamicsConfig)
    readout: ReadoutConfig = Field(default_factory=ReadoutConfig)
    kalman: KalmanConfig = Field(default_factory=KalmanConfig)
    actions: ActionConfig = Field(default_factory=ActionConfig)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    smoking_calendar: SmokingCalendarConfig = Field(default_factory=SmokingCalendarConfig)


def default_model_config() -> CravingModelConfig:
    return CravingModelConfig()


def to_runtime_parameters(
    config: CravingModelConfig,
    *,
    weight_kg: float | None = None,
    height_cm: float | None = None,
    body_fat: float | None = None,
    age_years: int | None = None,
) -> CravingModelParameters:
    """Map validated user config into runtime model parameters."""
    return CravingModelParameters(
        lambda_nicotine=config.dynamics.lambda_nicotine,
        k_dopamine=config.dynamics.k_dopamine,
        k_habit_decay=config.dynamics.k_habit_decay,
        k_withdrawal=config.dynamics.k_withdrawal,
        decay_withdrawal=config.dynamics.decay_withdrawal,
        habit_learning=config.dynamics.habit_learning,
        alpha_nicotine=config.dynamics.alpha_nicotine,
        alpha_reward=config.dynamics.alpha_reward,
        beta_stress=config.dynamics.beta_stress,
        k_dopamine_fast=config.dynamics.k_dopamine_fast,
        k_dopamine_slow=config.dynamics.k_dopamine_slow,
        dopamine_fast_weight=config.dynamics.dopamine_fast_weight,
        alpha_nicotine_fast=config.dynamics.alpha_nicotine_fast,
        alpha_nicotine_slow=config.dynamics.alpha_nicotine_slow,
        alpha_reward_fast=config.dynamics.alpha_reward_fast,
        alpha_reward_slow=config.dynamics.alpha_reward_slow,
        beta_stress_fast=config.dynamics.beta_stress_fast,
        beta_stress_slow=config.dynamics.beta_stress_slow,
        w_D=config.readout.w_D,
        w_W=config.readout.w_W,
        w_H=config.readout.w_H,
        w_stress=config.readout.w_stress,
        w_cue=config.readout.w_cue,
        bias=config.readout.bias,
        enable_kalman=config.kalman.enabled,
        kalman_process_noise=config.kalman.process_noise,
        kalman_observation_noise=config.kalman.observation_noise_craving,
        default_action_dopamine_boost=config.actions.default_dopamine_boost,
        default_action_withdrawal_relief=config.actions.default_withdrawal_relief,
        weight_kg=75.0 if weight_kg is None else float(weight_kg),
        height_cm=175.0 if height_cm is None else float(height_cm),
        body_fat=0.20 if body_fat is None else float(body_fat),
        age_years=30 if age_years is None else int(age_years),
    )
