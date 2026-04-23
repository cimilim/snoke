"""Short-term, rule-based multipliers applied on top of the bucket posterior.

These capture fast-moving effects (just had coffee, currently exercising)
that the coarse buckets cannot express.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable


@dataclass(slots=True)
class RuleAdjustment:
    factor: float
    reasons: list[str]


# (tag, within_minutes, multiplier, reason)
_TRIGGER_RULES: list[tuple[str, int, float, str]] = [
    ("coffee",   45, 1.30, "Kaffee in letzten 45 Min"),
    ("alcohol",  90, 1.50, "Alkohol in letzten 90 Min"),
    ("meal",     45, 1.20, "Mahlzeit in letzten 45 Min"),
    ("stress",   30, 1.25, "Stress-Tag in letzten 30 Min"),
    ("break",    10, 1.15, "Pause gerade begonnen"),
    ("exercise", 30, 0.70, "Aktive Bewegung in letzten 30 Min"),
]


class RuleLayer:
    """Apply multiplicative adjustments based on the last events."""

    def adjust(
        self,
        base_p: float,
        now: datetime,
        recent_cigarettes: Iterable[datetime],
        recent_tags: Iterable[tuple[str, datetime]],
        today_target: int | None = None,
        today_smoked: int = 0,
    ) -> RuleAdjustment:
        factor = 1.0
        reasons: list[str] = []

        # Recent cigarette cools craving for ~20 min.
        last = max(recent_cigarettes, default=None)
        if last is not None:
            delta = (now - last).total_seconds() / 60.0
            if delta < 5:
                factor *= 0.15
                reasons.append("Zigarette gerade geraucht")
            elif delta < 20:
                factor *= 0.40
                reasons.append(f"letzte Zigarette vor {int(delta)} Min")

        # Trigger tags boost or dampen.
        for tag, ts in recent_tags:
            for rule_tag, within, mult, reason in _TRIGGER_RULES:
                if tag == rule_tag and (now - ts) <= timedelta(minutes=within):
                    factor *= mult
                    reasons.append(reason)

        # Social pressure: if already close to daily target, the app nudges
        # the probability *down* slightly to encourage resisting.
        if today_target is not None and today_target > 0:
            ratio = today_smoked / today_target
            if ratio >= 1.0:
                factor *= 0.85
                reasons.append("Tagesziel erreicht — durchhalten!")
            elif ratio >= 0.8:
                factor *= 0.92
                reasons.append("nahe am Tagesziel")

        adjusted = max(0.0, min(1.0, base_p * factor))
        return RuleAdjustment(factor=adjusted / base_p if base_p > 0 else factor,
                              reasons=reasons)
