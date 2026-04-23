"""Beta-Bernoulli online update per context bucket.

State is materialised on demand from the events table (no separate bucket
table needed for the MVP). This keeps the store simple and lets us change
bucket granularity without migrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from app.model.features import Bucket


# Informed priors per hour-block for a typical smoker. α is "crave weight",
# β is "no-crave weight"; mean of Beta(α, β) = α / (α+β).
_HOUR_PRIORS: dict[int, tuple[float, float]] = {
    0: (0.5, 8.0),  1: (0.5, 10.0), 2: (0.5, 10.0),
    3: (2.0, 6.0),  4: (3.0, 5.0),  5: (2.0, 6.0),   # morning peak 6-12
    6: (2.0, 6.0),  7: (3.0, 6.0),  8: (3.0, 6.0),   # afternoon mid 12-18
    9: (4.0, 5.0), 10: (4.0, 5.0), 11: (2.5, 7.0),   # evening peak 18-24
}


@dataclass(slots=True)
class PosteriorStats:
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        total = self.alpha + self.beta
        return self.alpha / total if total > 0 else 0.0

    @property
    def n(self) -> int:
        return int(round(self.alpha + self.beta))


class BayesianUpdater:
    """Compute per-bucket posterior statistics from observed events.

    Input: iterable of `(bucket, is_crave)` pairs observed over the training
    window (last `decay_days` days). Older evidence is weighted down
    exponentially with `decay_per_day`.
    """

    def __init__(
        self,
        decay_days: int = 60,
        decay_per_day: float = 0.995,
        prior_weight: float = 1.0,
    ) -> None:
        self.decay_days = decay_days
        self.decay_per_day = decay_per_day
        self.prior_weight = prior_weight

    def prior_for(self, bucket: Bucket) -> tuple[float, float]:
        alpha, beta = _HOUR_PRIORS.get(bucket.hour_block, (2.0, 6.0))
        # Context modifiers: "elsewhere"/social apps evening → more temptation.
        if bucket.app_category.value == "social":
            alpha += 1.0
        if bucket.app_category.value == "work":
            beta += 0.5
        if bucket.activity.value == "active":
            beta += 0.5
        return self.prior_weight * alpha, self.prior_weight * beta

    def fit(
        self,
        observations: Iterable[tuple[Bucket, bool, datetime]],
        now: datetime,
    ) -> dict[str, PosteriorStats]:
        """Return the posterior stats per bucket key."""
        stats: dict[str, PosteriorStats] = {}
        cutoff = now - timedelta(days=self.decay_days)
        for bucket, is_crave, ts in observations:
            if ts < cutoff:
                continue
            age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
            weight = self.decay_per_day ** age_days
            entry = stats.get(bucket.key)
            if entry is None:
                a, b = self.prior_for(bucket)
                entry = PosteriorStats(alpha=a, beta=b)
                stats[bucket.key] = entry
            if is_crave:
                entry.alpha += weight
            else:
                entry.beta += weight
        return stats

    def posterior(
        self,
        bucket: Bucket,
        stats: dict[str, PosteriorStats],
    ) -> PosteriorStats:
        """Return posterior for one bucket, falling back to the prior."""
        existing = stats.get(bucket.key)
        if existing is not None:
            return existing
        a, b = self.prior_for(bucket)
        return PosteriorStats(alpha=a, beta=b)
