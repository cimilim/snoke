"""High-level craving probability engine.

This module keeps the existing bucket/rule architecture, but extends it with
an internal dynamic state-space model (dopamine/withdrawal/habit) to produce
time-evolving craving probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Iterable

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, User
from app.model.bayesian import BayesianUpdater, PosteriorStats
from app.model.features import AppCategory, Bucket, FeatureExtractor, StressLevel
from app.model.rules import RuleAdjustment, RuleLayer
from app.model.state_space import CravingModel, CravingModelParameters


@dataclass(slots=True)
class TriggerScore:
    label: str
    bucket_key: str
    mean: float
    samples: int


@dataclass(slots=True)
class CravingResult:
    now: datetime
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
    rule_reasons: list[str] = field(default_factory=list)
    top_triggers: list[TriggerScore] = field(default_factory=list)


class CravingEngine:
    def __init__(
        self,
        extractor: FeatureExtractor | None = None,
        updater: BayesianUpdater | None = None,
        rules: RuleLayer | None = None,
        dynamic_model: CravingModel | None = None,
    ) -> None:
        self.extractor = extractor or FeatureExtractor()
        self.updater = updater or BayesianUpdater()
        self.rules = rules or RuleLayer()
        self.dynamic_model = dynamic_model or CravingModel(
            CravingModelParameters(enable_kalman=True)
        )

    def compute(self, db: Session, user: User, now: datetime | None = None) -> CravingResult:
        return self.compute_with_parameters(db, user, model_parameters=None, now=now)

    def compute_with_parameters(
        self,
        db: Session,
        user: User,
        model_parameters: CravingModelParameters | None,
        now: datetime | None = None,
    ) -> CravingResult:
        now = now or datetime.now(UTC)
        events = self._load_events(db, user, now)

        # Keep Bayesian bucket statistics as explainability layer (top triggers).
        observations = list(self._observations(events))
        stats = self.updater.fit(observations, now)
        latest_context = self._latest_context(events, now)
        current_bucket = self.extractor.extract(now, latest_context)

        # Dynamic state-space simulation across event history up to "now".
        model = (
            CravingModel(model_parameters)
            if model_parameters is not None
            else self.dynamic_model.clone()
        )
        model.reset()
        p_now_raw = self._simulate_latent(model, events, now, latest_context)
        latent = model.get_state()
        base_params = model_parameters or model.params

        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        smoked_today = sum(
            1 for e in events if e.kind == "cigarette" and e.occurred_at >= today_start
        )
        recent_cigs = [
            e.occurred_at for e in events
            if e.kind == "cigarette" and (now - e.occurred_at) <= timedelta(hours=2)
        ]
        recent_tags = list(self._recent_tags(events, now))

        adj = self.rules.adjust(
            base_p=p_now_raw,
            now=now,
            recent_cigarettes=recent_cigs,
            recent_tags=recent_tags,
            today_target=None,
            today_smoked=smoked_today,
        )
        p_now = max(0.0, min(1.0, p_now_raw * adj.factor))
        p_low, p_high = self._estimate_probability_interval(
            events=events,
            now=now,
            latest_context=latest_context,
            base_parameters=base_params,
            recent_cigarettes=recent_cigs,
            recent_tags=recent_tags,
            smoked_today=smoked_today,
        )
        p_low = min(p_low, p_now)
        p_high = max(p_high, p_now)
        uncertainty_width = max(0.0, p_high - p_low)
        if uncertainty_width <= 0.12:
            confidence_level = "hoch"
        elif uncertainty_width <= 0.24:
            confidence_level = "mittel"
        else:
            confidence_level = "niedrig"

        # Forward look with latent state evolution and no nicotine/reward pulses.
        p_next_hour, next_peak_at = self._forward(model, latest_context, now, adj.factor)

        top = self._top_triggers(stats)
        return CravingResult(
            now=now,
            p_now=round(p_now, 3),
            p_low=round(p_low, 3),
            p_high=round(p_high, 3),
            uncertainty_width=round(uncertainty_width, 3),
            confidence_level=confidence_level,
            p_next_hour=round(p_next_hour, 3),
            next_peak_at=next_peak_at,
            bucket_key=current_bucket.key,
            dopamine=round(latent["dopamine"], 3),
            withdrawal=round(latent["withdrawal"], 3),
            habit=round(latent["habit"], 3),
            rule_reasons=adj.reasons,
            top_triggers=top,
        )

    # ---- helpers ---------------------------------------------------------

    def _load_events(self, db: Session, user: User, now: datetime) -> list[Event]:
        cutoff = now - timedelta(days=self.updater.decay_days)
        rows = list(
            db.execute(
                select(Event)
                .where(
                    Event.user_id == user.id,
                    Event.occurred_at >= cutoff,
                    Event.occurred_at <= now,
                )
                .order_by(Event.occurred_at.asc())
            ).scalars()
        )
        # SQLite drops tzinfo on read — normalise everything back to UTC-aware.
        for e in rows:
            if e.occurred_at.tzinfo is None:
                e.occurred_at = e.occurred_at.replace(tzinfo=UTC)
        return rows

    def _observations(
        self, events: list[Event]
    ) -> Iterable[tuple[Bucket, bool, datetime]]:
        # A context event is a "no-crave" observation unless a cigarette or
        # craving event occurred within the same 15-min window.
        crave_times = sorted(
            e.occurred_at for e in events if e.kind in ("cigarette", "craving")
        )

        def has_crave_near(ts: datetime) -> bool:
            # binary search-ish linear scan is fine for typical volumes
            for ct in crave_times:
                if abs((ct - ts).total_seconds()) <= 450:  # 7.5 min
                    return True
                if ct > ts + timedelta(minutes=10):
                    break
            return False

        for e in events:
            if e.kind == "cigarette" or e.kind == "craving":
                bucket = self.extractor.extract(e.occurred_at, e.payload)
                yield bucket, True, e.occurred_at
            elif e.kind == "context":
                bucket = self.extractor.extract(e.occurred_at, e.payload)
                yield bucket, has_crave_near(e.occurred_at), e.occurred_at

    @staticmethod
    def _latest_context(events: list[Event], now: datetime) -> dict | None:
        for e in reversed(events):
            if e.kind == "context" and (now - e.occurred_at) <= timedelta(minutes=15):
                return dict(e.payload)
        return None

    @staticmethod
    def _recent_tags(events: list[Event], now: datetime):
        window = timedelta(hours=2)
        for e in events:
            if (now - e.occurred_at) > window:
                continue
            tag = None
            if isinstance(e.payload, dict):
                tag = e.payload.get("trigger")
            if tag:
                yield tag, e.occurred_at

    def _forward(
        self,
        model: CravingModel,
        context: dict | None,
        now: datetime,
        rule_factor: float,
    ) -> tuple[float, datetime | None]:
        best_p = 0.0
        best_t: datetime | None = None
        sim = model.clone()
        stress, cue = self._context_proxies(context)
        for i in range(1, 5):
            t = now + timedelta(minutes=15 * i)
            out = sim.update(
                dt=0.25,  # 15 min
                nicotine=0.0,
                reward=0.0,
                stress=stress,
                cue=cue,
                action=None,
            )
            p = float(out["craving_probability"]) * rule_factor
            p = max(0.0, min(1.0, p))
            if p > best_p:
                best_p = p
                best_t = t
        return best_p, best_t

    def _simulate_latent(
        self,
        model: CravingModel,
        events: list[Event],
        now: datetime,
        latest_context: dict | None,
    ) -> float:
        """Replay event history as discrete-time simulation.

        The latent model integrates:
        - context events (stress/cue),
        - cigarettes (nicotine pulse),
        - craving events (optional observation for Kalman correction),
        - nudge events (action placeholder hook).
        """
        if not events:
            stress, cue = self._context_proxies(latest_context)
            return float(
                model.update(dt=0.25, nicotine=0.0, reward=0.0, stress=stress, cue=cue)[
                    "craving_probability"
                ]
            )

        context = latest_context or {}
        t_prev = events[0].occurred_at
        # Warm-up: short passive step to stabilize initial state.
        model.update(dt=0.1, nicotine=0.0, reward=0.0, stress=0.2, cue=0.2)

        for ev in events:
            if ev.kind == "context" and isinstance(ev.payload, dict):
                context = dict(ev.payload)
            dt_h = max(1.0 / 60.0, (ev.occurred_at - t_prev).total_seconds() / 3600.0)
            nicotine, reward, stress, cue = self._inputs_for_step(ev, context)
            action = self._event_action(ev)
            observed = self._event_observed_craving(ev)
            model.update(
                dt=dt_h,
                nicotine=nicotine,
                reward=reward,
                stress=stress,
                cue=cue,
                action=action,
                observed_craving=observed,
            )
            t_prev = ev.occurred_at

        # Final drift from last event timestamp to now.
        dt_tail = max(1.0 / 60.0, (now - t_prev).total_seconds() / 3600.0)
        stress, cue = self._context_proxies(context)
        out = model.update(
            dt=dt_tail,
            nicotine=0.0,
            reward=0.0,
            stress=stress,
            cue=cue,
            action=None,
        )
        return float(out["craving_probability"])

    def _adjusted_probability_for_parameters(
        self,
        *,
        parameters: CravingModelParameters,
        events: list[Event],
        now: datetime,
        latest_context: dict | None,
        recent_cigarettes: list[datetime],
        recent_tags: list[tuple[str, datetime]],
        smoked_today: int,
    ) -> float:
        model = CravingModel(parameters)
        model.reset()
        p_raw = self._simulate_latent(model, events, now, latest_context)
        adj = self.rules.adjust(
            base_p=p_raw,
            now=now,
            recent_cigarettes=recent_cigarettes,
            recent_tags=recent_tags,
            today_target=None,
            today_smoked=smoked_today,
        )
        return float(np.clip(p_raw * adj.factor, 0.0, 1.0))

    def _estimate_probability_interval(
        self,
        *,
        events: list[Event],
        now: datetime,
        latest_context: dict | None,
        base_parameters: CravingModelParameters,
        recent_cigarettes: list[datetime],
        recent_tags: list[tuple[str, datetime]],
        smoked_today: int,
    ) -> tuple[float, float]:
        scenarios: list[CravingModelParameters] = [base_parameters]
        perturbations = (
            ("lambda_nicotine", 0.85, 1.15),
            ("k_withdrawal", 0.80, 1.20),
            ("habit_learning", 0.85, 1.15),
            ("w_D", 0.90, 1.10),
            ("w_W", 0.90, 1.10),
            ("w_H", 0.90, 1.10),
            ("w_stress", 0.85, 1.15),
            ("w_cue", 0.85, 1.15),
        )
        for name, lo, hi in perturbations:
            base_value = float(getattr(base_parameters, name))
            lo_val = max(1e-6, base_value * lo) if base_value > 0 else base_value * lo
            hi_val = max(1e-6, base_value * hi) if base_value > 0 else base_value * hi
            scenarios.append(replace(base_parameters, **{name: lo_val}))
            scenarios.append(replace(base_parameters, **{name: hi_val}))

        probs: list[float] = []
        for p in scenarios:
            probs.append(
                self._adjusted_probability_for_parameters(
                    parameters=p,
                    events=events,
                    now=now,
                    latest_context=latest_context,
                    recent_cigarettes=recent_cigarettes,
                    recent_tags=recent_tags,
                    smoked_today=smoked_today,
                )
            )
        if not probs:
            return 0.0, 1.0
        return float(np.quantile(probs, 0.1)), float(np.quantile(probs, 0.9))

    def _inputs_for_step(
        self,
        ev: Event,
        context: dict,
    ) -> tuple[float, float, float, float]:
        """Map app events into latent-model exogenous inputs in [0,1]."""
        nicotine = 0.0
        reward = 0.0
        stress, cue = self._context_proxies(context)

        payload = ev.payload if isinstance(ev.payload, dict) else {}
        trigger = str(payload.get("trigger", "")).lower()

        if ev.kind == "cigarette":
            nicotine = 1.0
            reward = 0.55
            cue = max(cue, 0.5)
            if trigger in {"coffee", "stress", "social", "alcohol"}:
                cue = max(cue, 0.8)
            if trigger == "stress":
                stress = max(stress, 0.8)
        elif ev.kind == "craving":
            # Resisting an urge can be intrinsically rewarding.
            if bool(payload.get("resisted")):
                reward = 0.25
            intensity = float(np.clip(float(payload.get("intensity", 5.0)) / 10.0, 0.0, 1.0))
            stress = max(stress, intensity * 0.8)
            cue = max(cue, 0.4)
        elif ev.kind == "nutrition_activity":
            # Exercise is modeled as a short-term positive reward signal and
            # slight stress/cue dampening, scaled by duration and intensity.
            sport = str(payload.get("sport_type", "")).lower()
            minutes = float(payload.get("minutes", 0.0))
            burned = float(payload.get("kcal_burned", 0.0))
            intensity_map = {
                "gehen": 0.25,
                "yoga": 0.30,
                "krafttraining": 0.55,
                "radfahren": 0.50,
                "joggen": 0.65,
                "laufen": 0.75,
                "schwimmen": 0.70,
                "fussball": 0.75,
                "tennis": 0.65,
                "wandern": 0.45,
            }
            intensity = intensity_map.get(sport, 0.45)
            dur_scale = float(np.clip(minutes / 45.0, 0.2, 1.8))
            burn_scale = float(np.clip(burned / 400.0, 0.0, 1.0))
            reward = max(reward, float(np.clip((0.18 + 0.42 * intensity) * dur_scale, 0.0, 0.85)))
            stress = float(np.clip(stress * (1.0 - 0.20 * intensity - 0.10 * burn_scale), 0.0, 1.0))
            cue = float(np.clip(cue * (1.0 - 0.08 * intensity), 0.0, 1.0))
        elif ev.kind == "nudge":
            reward = 0.10 if bool(payload.get("accepted")) else 0.0
        # context kind keeps stress/cue from context proxies.

        return (
            float(np.clip(nicotine, 0.0, 1.0)),
            float(np.clip(reward, 0.0, 1.0)),
            float(np.clip(stress, 0.0, 1.0)),
            float(np.clip(cue, 0.0, 1.0)),
        )

    def _context_proxies(self, context: dict | None) -> tuple[float, float]:
        ctx = context or {}
        bucket = self.extractor.extract(datetime.now(UTC), ctx)

        stress_map = {
            StressLevel.low: 0.2,
            StressLevel.mid: 0.5,
            StressLevel.high: 0.85,
            StressLevel.unknown: 0.35,
        }
        cue = 0.2
        if bucket.app_category == AppCategory.social:
            cue = 0.85
        elif bucket.app_category == AppCategory.media:
            cue = 0.65
        elif bucket.app_category == AppCategory.idle:
            cue = 0.35
        elif bucket.app_category == AppCategory.work:
            cue = 0.15
        return float(stress_map.get(bucket.stress, 0.35)), float(cue)

    @staticmethod
    def _event_observed_craving(ev: Event) -> float | None:
        """Observed craving signal for optional Kalman correction."""
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        if ev.kind == "craving":
            intensity = float(payload.get("intensity", 7))
            return float(np.clip(intensity / 10.0, 0.0, 1.0))
        if ev.kind == "cigarette":
            # smoking implies high craving context immediately before.
            return 0.9
        return None

    @staticmethod
    def _event_action(ev: Event) -> dict[str, float] | None:
        """Intervention hook for future RL policies."""
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        if ev.kind == "nutrition_activity":
            sport = str(payload.get("sport_type", "")).lower()
            minutes = float(payload.get("minutes", 0.0))
            burned = float(payload.get("kcal_burned", 0.0))
            intensity_map = {
                "gehen": 0.20,
                "yoga": 0.25,
                "krafttraining": 0.55,
                "radfahren": 0.50,
                "joggen": 0.65,
                "laufen": 0.75,
                "schwimmen": 0.70,
                "fussball": 0.80,
                "tennis": 0.65,
                "wandern": 0.40,
            }
            intensity = intensity_map.get(sport, 0.45)
            dur_scale = float(np.clip(minutes / 45.0, 0.2, 1.8))
            burn_scale = float(np.clip(burned / 450.0, 0.0, 1.0))
            dopamine_boost = float(np.clip((0.04 + 0.12 * intensity) * dur_scale, 0.0, 0.26))
            withdrawal_relief = float(np.clip((0.03 + 0.10 * intensity) * (0.6 + 0.4 * burn_scale), 0.0, 0.22))
            return {"dopamine_boost": dopamine_boost, "withdrawal_relief": withdrawal_relief}
        if ev.kind != "nudge":
            return None
        if bool(payload.get("accepted")):
            return {"dopamine_boost": 0.10, "withdrawal_relief": 0.12}
        return {"dopamine_boost": 0.02, "withdrawal_relief": 0.03}

    @staticmethod
    def _top_triggers(
        stats: dict[str, PosteriorStats], limit: int = 3
    ) -> list[TriggerScore]:
        ranked = sorted(
            stats.items(),
            key=lambda kv: (kv[1].mean, kv[1].n),
            reverse=True,
        )
        out: list[TriggerScore] = []
        for key, st in ranked[:limit]:
            out.append(
                TriggerScore(
                    label=_humanize(key),
                    bucket_key=key,
                    mean=round(st.mean, 3),
                    samples=st.n,
                )
            )
        return out


_LABELS = {
    "we": "Wochenende", "wd": "Werktag",
    "still": "ruhig", "active": "aktiv", "unknown": "unbekannt",
    "low": "entspannt", "mid": "fokussiert", "high": "angespannt",
    "work": "Arbeit", "social": "Social Media", "media": "Medien",
    "game": "Gaming", "idle": "idle", "other": "sonstige App",
}


def _humanize(bucket_key: str) -> str:
    parts = bucket_key.split("|")
    if len(parts) != 5:
        return bucket_key
    hb, wd, act, st, app = parts
    start = int(hb) * 2
    return (
        f"{start:02d}–{start+2:02d} Uhr, {_LABELS.get(wd, wd)}, "
        f"{_LABELS.get(act, act)}, {_LABELS.get(st, st)}, {_LABELS.get(app, app)}"
    )
