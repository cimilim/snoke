"""Model validation helpers: metrics, baselines, and lightweight ablations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import isnan

from sqlalchemy.orm import Session

from app.model.engine import CravingEngine
from app.model.state_space import CravingModel, CravingModelParameters
from app.models import Event, User


@dataclass(slots=True)
class ValidationMetrics:
    brier: float
    auc: float | None
    calibration_error: float
    sample_count: int


@dataclass(slots=True)
class ValidationReport:
    model: ValidationMetrics
    baselines: dict[str, ValidationMetrics]
    ablations: dict[str, ValidationMetrics]


@dataclass(slots=True)
class _Observation:
    ts: datetime
    label: int
    p_model: float
    p_hour_baseline: float
    p_recent_baseline: float
    p_no_kalman: float
    p_no_sport: float
    p_no_rules: float


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _brier_score(points: list[tuple[float, int]]) -> float:
    if not points:
        return 0.0
    err = sum((p - y) ** 2 for p, y in points)
    return float(err / len(points))


def _roc_auc(points: list[tuple[float, int]]) -> float | None:
    if not points:
        return None
    pos = sum(1 for _, y in points if y == 1)
    neg = len(points) - pos
    if pos == 0 or neg == 0:
        return None
    ranked = sorted(points, key=lambda x: x[0])
    rank_sum_pos = 0.0
    i = 0
    while i < len(ranked):
        j = i + 1
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            if ranked[k][1] == 1:
                rank_sum_pos += avg_rank
        i = j
    u = rank_sum_pos - (pos * (pos + 1) / 2.0)
    return float(u / (pos * neg))


def _ece(points: list[tuple[float, int]], bins: int = 10) -> float:
    if not points:
        return 0.0
    n = len(points)
    total = 0.0
    for b in range(bins):
        lo = b / bins
        hi = (b + 1) / bins
        if b == bins - 1:
            bucket = [(p, y) for p, y in points if lo <= p <= hi]
        else:
            bucket = [(p, y) for p, y in points if lo <= p < hi]
        if not bucket:
            continue
        conf = sum(p for p, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        total += abs(conf - acc) * (len(bucket) / n)
    return float(total)


def _metrics(points: list[tuple[float, int]]) -> ValidationMetrics:
    auc = _roc_auc(points)
    return ValidationMetrics(
        brier=round(_brier_score(points), 4),
        auc=None if auc is None or isnan(auc) else round(float(auc), 4),
        calibration_error=round(_ece(points), 4),
        sample_count=len(points),
    )


def _context_until(engine: CravingEngine, events: list[Event], ts: datetime) -> dict | None:
    hist = [e for e in events if e.occurred_at <= ts]
    return engine._latest_context(hist, ts)  # noqa: SLF001 - validation helper


def _probability_from_history(
    engine: CravingEngine,
    *,
    parameters: CravingModelParameters,
    events: list[Event],
    ts: datetime,
    apply_rules: bool,
) -> float:
    hist = [e for e in events if e.occurred_at <= ts]
    model = CravingModel(parameters)
    model.reset()
    context = _context_until(engine, events, ts)
    p_raw = engine._simulate_latent(model, hist, ts, context)  # noqa: SLF001
    if not apply_rules:
        return _clip01(p_raw)
    day_start = datetime(ts.year, ts.month, ts.day, tzinfo=UTC)
    smoked_today = sum(1 for e in hist if e.kind == "cigarette" and e.occurred_at >= day_start)
    recent_cigs = [e.occurred_at for e in hist if e.kind == "cigarette" and (ts - e.occurred_at) <= timedelta(hours=2)]
    recent_tags = list(engine._recent_tags(hist, ts))  # noqa: SLF001
    adj = engine.rules.adjust(
        base_p=p_raw,
        now=ts,
        recent_cigarettes=recent_cigs,
        recent_tags=recent_tags,
        today_target=None,
        today_smoked=smoked_today,
    )
    return _clip01(p_raw * adj.factor)


def build_validation_report(
    db: Session,
    user: User,
    engine: CravingEngine,
    parameters: CravingModelParameters,
    *,
    now: datetime | None = None,
    max_samples: int = 120,
) -> ValidationReport | None:
    now = now or datetime.now(UTC)
    events = engine._load_events(db, user, now)  # noqa: SLF001 - validation helper
    observations = list(engine._observations(events))  # noqa: SLF001 - validation helper
    if len(observations) < 8:
        return None
    observations = observations[-max_samples:]

    # Running hour-baseline by hour block from past observations only.
    hour_stats: dict[int, tuple[int, int]] = {}
    recent_window = timedelta(hours=4)
    enriched: list[_Observation] = []
    no_kalman_params = replace(parameters, enable_kalman=False)

    for bucket, observed_bool, ts in observations:
        label = 1 if observed_bool else 0
        pos, total = hour_stats.get(bucket.hour_block, (1, 2))  # weak Beta-like prior mean 0.5
        p_hour = pos / total

        prev = [
            e for e in events
            if e.occurred_at <= ts and (ts - e.occurred_at) <= recent_window and e.kind in ("cigarette", "craving")
        ]
        p_recent = 0.5 if not prev else min(1.0, len(prev) / 8.0)

        p_model = _probability_from_history(
            engine,
            parameters=parameters,
            events=events,
            ts=ts,
            apply_rules=True,
        )
        p_no_kalman = _probability_from_history(
            engine,
            parameters=no_kalman_params,
            events=events,
            ts=ts,
            apply_rules=True,
        )
        no_sport_events = [e for e in events if e.kind != "nutrition_activity"]
        p_no_sport = _probability_from_history(
            engine,
            parameters=parameters,
            events=no_sport_events,
            ts=ts,
            apply_rules=True,
        )
        p_no_rules = _probability_from_history(
            engine,
            parameters=parameters,
            events=events,
            ts=ts,
            apply_rules=False,
        )
        enriched.append(
            _Observation(
                ts=ts,
                label=label,
                p_model=p_model,
                p_hour_baseline=p_hour,
                p_recent_baseline=p_recent,
                p_no_kalman=p_no_kalman,
                p_no_sport=p_no_sport,
                p_no_rules=p_no_rules,
            )
        )

        old_pos, old_total = hour_stats.get(bucket.hour_block, (1, 2))
        hour_stats[bucket.hour_block] = (old_pos + label, old_total + 1)

    model_points = [(o.p_model, o.label) for o in enriched]
    base_hour_points = [(o.p_hour_baseline, o.label) for o in enriched]
    base_recent_points = [(o.p_recent_baseline, o.label) for o in enriched]
    no_kalman_points = [(o.p_no_kalman, o.label) for o in enriched]
    no_sport_points = [(o.p_no_sport, o.label) for o in enriched]
    no_rules_points = [(o.p_no_rules, o.label) for o in enriched]

    return ValidationReport(
        model=_metrics(model_points),
        baselines={
            "hour_block": _metrics(base_hour_points),
            "recent_event_rate": _metrics(base_recent_points),
        },
        ablations={
            "ohne_kalman": _metrics(no_kalman_points),
            "ohne_sport": _metrics(no_sport_points),
            "ohne_rules": _metrics(no_rules_points),
        },
    )
