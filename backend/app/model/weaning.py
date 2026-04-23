"""Weaning-planner: turn historic consumption + user settings into a daily target."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BudgetState(StrEnum):
    on_track = "on_track"
    close_to_limit = "close_to_limit"
    over_budget = "over_budget"


@dataclass(slots=True)
class WeaningStatus:
    target_today: int
    smoked_today: int
    remaining: int
    rolling_avg_7d: float
    state: BudgetState
    streak_days_on_target: int


class WeaningPlanner:
    def __init__(
        self,
        min_target: int = 0,
        baseline_weight: float = 0.7,
        rolling_weight: float = 0.3,
    ) -> None:
        self.min_target = min_target
        total = max(1e-6, float(baseline_weight) + float(rolling_weight))
        self.baseline_weight = float(baseline_weight) / total
        self.rolling_weight = float(rolling_weight) / total

    def target_for_today(
        self,
        rolling_avg_7d: float,
        weaning_rate_pct: int,
        baseline: int | None,
    ) -> int:
        """Compute today's maximum cigarette budget.

        We smooth between user baseline and rolling history so short-term
        outliers don't collapse the target too aggressively.
        """
        rate = max(0, min(50, weaning_rate_pct)) / 100.0
        if baseline is not None and rolling_avg_7d > 0:
            blended = (
                self.baseline_weight * float(baseline)
                + self.rolling_weight * float(rolling_avg_7d)
            )
            target = blended * (1.0 - rate)
        elif baseline is not None:
            target = float(baseline) * (1.0 - rate)
        else:
            target = rolling_avg_7d * (1.0 - rate)
        return max(self.min_target, int(round(target)))

    def status(
        self,
        rolling_avg_7d: float,
        smoked_today: int,
        weaning_rate_pct: int,
        baseline: int | None,
        streak_days_on_target: int = 0,
    ) -> WeaningStatus:
        target = self.target_for_today(rolling_avg_7d, weaning_rate_pct, baseline)
        remaining = max(0, target - smoked_today)
        if target == 0:
            state = BudgetState.over_budget if smoked_today > 0 else BudgetState.on_track
        elif smoked_today >= target:
            state = BudgetState.over_budget
        elif smoked_today >= 0.8 * target:
            state = BudgetState.close_to_limit
        else:
            state = BudgetState.on_track
        return WeaningStatus(
            target_today=target,
            smoked_today=smoked_today,
            remaining=remaining,
            rolling_avg_7d=round(rolling_avg_7d, 2),
            state=state,
            streak_days_on_target=streak_days_on_target,
        )
